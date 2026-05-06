"""spaCy NER pre-resolution and vocabulary lookup (v0.5.0).

Extracts named entities before the LLM call.  When a vocabulary pass has run,
the pre-resolution step queries the ``skos:prefLabel`` / ``skos:altLabel``
index via pg_ripple and injects matched preferred-label IRIs into the
structured context block that is sent to the extractor.

Falls back gracefully (returns empty ``NERResult``) when spaCy is not installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class NEREntity:
    """A named entity extracted from a text span."""

    text: str
    label: str
    start_char: int
    end_char: int


@dataclass
class NERResult:
    """Result of NER extraction on a text fragment."""

    entities: list[NEREntity] = field(default_factory=list)


class SpacyNERExtractor:
    """spaCy-backed named entity recogniser.

    Runs spaCy NER before the LLM extraction call so that entity spans are
    known before any LLM prompt is constructed.  When a vocabulary pass has
    already run, :func:`lookup_vocabulary` can be used to snap each entity
    to its canonical preferred-label IRI.

    Falls back gracefully (returns an empty :class:`NERResult`) when spaCy
    or the requested model is not installed.
    """

    name = "spacy"

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        self._model_name = model_name
        self._nlp: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, text: str) -> NERResult:
        """Extract named entities from *text*.

        Returns:
            :class:`NERResult` with entities found; empty when spaCy is
            unavailable or the model is not installed.
        """
        nlp = self._get_nlp()
        if nlp is False:
            return NERResult()
        doc = nlp(text)
        entities = [
            NEREntity(
                text=ent.text,
                label=ent.label_,
                start_char=ent.start_char,
                end_char=ent.end_char,
            )
            for ent in doc.ents
        ]
        return NERResult(entities=entities)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_nlp(self) -> Any:
        """Lazy-load and cache the spaCy model.  Returns ``False`` on failure."""
        if self._nlp is None:
            try:
                import spacy  # noqa: PLC0415

                self._nlp = spacy.load(self._model_name)
            except ImportError:
                logger.debug(
                    "spaCy not installed — NER pre-resolution step will be skipped. "
                    "Install it with: pip install 'riverbank[ingest]'"
                )
                self._nlp = False
            except OSError:
                logger.debug(
                    "spaCy model %r not found — NER step will be skipped. "
                    "Download it with: python -m spacy download %s",
                    self._model_name,
                    self._model_name,
                )
                self._nlp = False
        return self._nlp


# ---------------------------------------------------------------------------
# Vocabulary lookup
# ---------------------------------------------------------------------------


def lookup_vocabulary(conn: Any, entity_text: str) -> Optional[str]:
    """Look up a canonical concept IRI for *entity_text* via SKOS labels.

    Queries pg_ripple for a ``skos:prefLabel`` or ``skos:altLabel`` that
    matches *entity_text* (case-insensitive).  Returns the canonical concept
    IRI if found, or ``None`` otherwise.

    Falls back gracefully (returns ``None``) when pg_ripple is not available
    or the query fails.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        # Use a nested transaction (savepoint) so a pg_ripple failure doesn't
        # abort the surrounding transaction.
        row = None
        with conn.begin_nested():
            row = conn.execute(
                text("SELECT pg_ripple.skos_label_lookup(:entity_text)"),
                {"entity_text": entity_text},
            ).fetchone()
        if row and row[0]:
            return str(row[0])
        return None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("does not exist", "not found", "undefined function", "column")
        ):
            logger.debug(
                "lookup_vocabulary: pg_ripple.skos_label_lookup not available: %s", exc
            )
        else:
            logger.debug("lookup_vocabulary failed: %s", exc)
        return None
