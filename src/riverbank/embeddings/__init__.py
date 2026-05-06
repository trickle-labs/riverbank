"""sentence-transformers embedding generation (v0.5.0).

Provides :class:`EmbeddingGenerator` for generating dense vector embeddings
per compiled fragment summary, and :func:`store_entity_embedding` for
persisting the embedding via pg_ripple / pgVector.

Entity-cluster centroid views are maintained as ``avg(embedding)::vector``
in pg_trickle stream tables (pgVector IVM, v0.37+): the centroid updates
incrementally with no full scan on each new fact.

Falls back gracefully when sentence-transformers is not installed.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """sentence-transformers backed embedding generator.

    Produces a dense float vector for each text string.  Designed for
    fragment summaries and entity descriptions; the resulting vectors are
    stored per entity so that pg_trickle can maintain the cluster centroid
    view incrementally.

    Falls back gracefully (returns ``[]``) when sentence-transformers is
    not installed — install it with ``pip install 'riverbank[ingest]'``.
    """

    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, text: str) -> list[float]:
        """Generate a dense embedding for *text*.

        Returns:
            List of ``float`` values representing the embedding vector.
            Empty list when sentence-transformers is unavailable.
        """
        model = self._get_model()
        if model is False:
            return []
        embedding = model.encode(text)
        # Convert numpy array to a plain Python list for JSON serialisability.
        if hasattr(embedding, "tolist"):
            return list(embedding.tolist())
        return list(embedding)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> Any:
        """Lazy-load and cache the sentence-transformers model.

        Returns ``False`` when sentence-transformers is not installed.
        """
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                self._model = SentenceTransformer(self._model_name)
            except ImportError:
                logger.debug(
                    "sentence-transformers not installed — embedding generation "
                    "will be skipped.  Install it with: pip install 'riverbank[ingest]'"
                )
                self._model = False
        return self._model


# ---------------------------------------------------------------------------
# pg_ripple / pgVector storage
# ---------------------------------------------------------------------------


def store_entity_embedding(
    conn: Any,
    entity_iri: str,
    embedding: list[float],
) -> bool:
    """Store an entity embedding via pg_ripple / pgVector.

    Calls ``pg_ripple.store_embedding(entity_iri, embedding::vector)`` which
    writes the embedding into the entity-cluster table.  pg_trickle then
    maintains the ``avg(embedding)::vector`` centroid view incrementally
    (pgVector IVM, v0.37+) — no full scan is required on each insert.

    Args:
        conn:        Active SQLAlchemy connection.
        entity_iri:  IRI of the entity to attach the embedding to.
        embedding:   Dense float vector produced by :class:`EmbeddingGenerator`.

    Returns:
        ``True`` on success, ``False`` on graceful fallback (pg_ripple /
        pgVector not available, or empty embedding).
    """
    if not embedding:
        return False

    import json  # noqa: PLC0415

    from sqlalchemy import text  # noqa: PLC0415

    try:
        # Use a nested transaction (savepoint) so a pg_ripple failure doesn't
        # abort the surrounding transaction.
        with conn.begin_nested():
            conn.execute(
                text("SELECT pg_ripple.store_embedding(:iri, :emb::vector)"),
                {"iri": entity_iri, "emb": json.dumps(embedding)},
            )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in (
                "does not exist",
                "not found",
                "undefined function",
                "type",
                "vector",
            )
        ):
            logger.debug(
                "store_entity_embedding: pg_ripple.store_embedding not available: %s",
                exc,
            )
        else:
            logger.debug("store_entity_embedding failed: %s", exc)
        return False
