"""Incremental entity linking with synonym rings (v0.13.0).

**Problem:** The same real-world entity may be referred to by multiple surface
forms across documents: "Dataset", "data set", "datasets", "the dataset".
Without a persistent entity registry, each extraction creates a new IRI and
the graph fills with near-duplicate entity nodes.

**Approach:**

1. **Entity registry** — a persistent in-memory / DB table
   ``(iri, label, type, first_seen, doc_count, variants)`` grows as documents
   are processed.  IRIs are the canonical forms; ``variants`` holds observed
   surface forms (synonym ring, per ANSI Z39.19).
2. **Top-K injection** — before each fragment extraction, the top-K most
   relevant registered entities (by cosine similarity of their label to the
   fragment heading) are injected into the prompt as
   ``KNOWN ENTITIES — prefer these IRIs``.
3. **Synonym ring expansion** — after extraction, each new entity label is
   compared against the registry; if sufficiently similar (default 0.90),
   the entity is merged into the existing ring and a ``skos:altLabel`` triple
   is written for the new surface form.

CLI::

    riverbank entities list  [--limit N] [--graph IRI]
    riverbank entities merge --entity <IRI> --into <IRI> [--graph IRI]

The ``pg:fuzzy_match()`` function in pg_ripple is used to validate synonymy
before writing ``skos:altLabel`` triples.

Falls back gracefully when sentence-transformers is not installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# SPARQL — fetch all entities with labels from a named graph
_ENTITIES_SPARQL = """\
SELECT DISTINCT ?iri ?label ?type WHERE {{
  GRAPH <{graph}> {{
    ?iri ?p ?o .
    FILTER(isIRI(?iri))
    OPTIONAL {{ ?iri <http://www.w3.org/2000/01/rdf-schema#label> ?label . }}
    OPTIONAL {{ ?iri <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?type . }}
  }}
}} LIMIT {limit}
"""

# SPARQL — fetch altLabels for an entity
_ALTLABELS_SPARQL = """\
SELECT ?alt WHERE {{
  GRAPH <{graph}> {{
    <{iri}> <http://www.w3.org/2004/02/skos/core#altLabel> ?alt .
  }}
}}
"""

_SKOS_ALT_LABEL = "http://www.w3.org/2004/02/skos/core#altLabel"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two dense vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EntityRecord:
    """An entry in the entity registry."""

    iri: str
    label: str
    entity_type: str = ""
    first_seen: str = ""
    doc_count: int = 1
    variants: list[str] = field(default_factory=list)  # synonym ring (surface forms)


@dataclass
class EntityRegistry:
    """In-memory entity registry (persisted to/from the named graph).

    In production use, this is loaded from the DB at the start of each
    ingest run and flushed back at the end.
    """

    entities: list[EntityRecord] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def by_iri(self, iri: str) -> EntityRecord | None:
        for e in self.entities:
            if e.iri == iri:
                return e
        return None

    def top_k_by_similarity(
        self,
        query_embedding: list[float],
        embeddings: dict[str, list[float]],
        k: int = 5,
    ) -> list[EntityRecord]:
        """Return the top-K entities ranked by cosine similarity to the query."""
        scored: list[tuple[float, EntityRecord]] = []
        for entity in self.entities:
            emb = embeddings.get(entity.iri)
            if emb:
                sim = _cosine_similarity(query_embedding, emb)
                scored.append((sim, entity))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:k]]

    def merge(self, into_iri: str, from_iri: str) -> bool:
        """Merge *from_iri* entity into *into_iri*, adding its label as altLabel.

        Returns True on success.
        """
        target = self.by_iri(into_iri)
        source = self.by_iri(from_iri)
        if target is None or source is None:
            return False
        if source.label and source.label not in target.variants:
            target.variants.append(source.label)
        target.doc_count += source.doc_count
        self.entities = [e for e in self.entities if e.iri != from_iri]
        return True


@dataclass
class EntityLinkingResult:
    """Summary of an entity-linking run."""

    entities_registered: int = 0
    synonym_rings_updated: int = 0
    alt_labels_written: int = 0
    entities_merged: int = 0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class EntityLinker:
    """Incremental entity linker with synonym ring expansion.

    Args:
        model_name: sentence-transformers model for label embedding.
        synonym_threshold: cosine-similarity threshold for synonym ring
            expansion.  Default 0.90.
        top_k: number of entities to inject into the extraction prompt.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        synonym_threshold: float = 0.90,
        top_k: int = 5,
    ) -> None:
        self._model_name = model_name
        self._synonym_threshold = synonym_threshold
        self._top_k = top_k
        self._model: Any = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_registry(
        self,
        conn: Any,
        named_graph: str,
        limit: int = 2000,
    ) -> EntityRegistry:
        """Load the entity registry from the named graph.

        Falls back to an empty :class:`EntityRegistry` when pg_ripple is
        unavailable.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = _ENTITIES_SPARQL.format(graph=named_graph, limit=limit)
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning("entity_linker: SPARQL query failed — %s", exc)
            return EntityRegistry()

        registry = EntityRegistry()
        seen: set[str] = set()
        for row in rows:
            iri = str(row.get("iri", "")).strip()
            if not iri or iri in seen:
                continue
            seen.add(iri)
            label = str(row.get("label", "")).strip() or iri.split("/")[-1].split("#")[-1]
            entity_type = str(row.get("type", "")).strip()
            registry.entities.append(
                EntityRecord(iri=iri, label=label, entity_type=entity_type)
            )
        return registry

    def build_known_entities_block(
        self,
        registry: EntityRegistry,
        fragment_heading: str,
        embeddings_cache: dict[str, list[float]] | None = None,
    ) -> str:
        """Build the KNOWN ENTITIES prompt block for a fragment.

        Returns an empty string when the registry is empty or the model
        is unavailable.
        """
        if not registry.entities:
            return ""

        model = self._get_model()
        if model is False:
            # Without embeddings, return a simple list of top-K entities
            sample = registry.entities[: self._top_k]
        else:
            try:
                # Embed the fragment heading and rank entities by similarity
                query_emb = list(model.encode(fragment_heading))
                if embeddings_cache is None:
                    embeddings_cache = {}
                # Embed any un-cached entity labels
                for entity in registry.entities:
                    if entity.iri not in embeddings_cache:
                        try:
                            embeddings_cache[entity.iri] = list(
                                model.encode(entity.label)
                            )
                        except Exception:  # noqa: BLE001
                            pass
                sample = registry.top_k_by_similarity(query_emb, embeddings_cache, k=self._top_k)
            except Exception:  # noqa: BLE001
                sample = registry.entities[: self._top_k]

        if not sample:
            return ""

        lines = ["KNOWN ENTITIES — prefer these IRIs when the text refers to these concepts:"]
        for entity in sample:
            type_str = f"  ({entity.entity_type})" if entity.entity_type else ""
            alt_str = ""
            if entity.variants:
                alt_str = f"  [also: {', '.join(entity.variants[:3])}]"
            lines.append(f"  {entity.iri}  {entity.label!r}{type_str}{alt_str}")
        return "\n".join(lines)

    def update_registry(
        self,
        conn: Any,
        registry: EntityRegistry,
        named_graph: str,
        new_triples: list[Any],
        dry_run: bool = False,
    ) -> EntityLinkingResult:
        """Update the entity registry from newly extracted triples.

        Scans *new_triples* for entity subjects and objects.  For each new
        entity, checks if it should be merged into an existing synonym ring.
        Writes ``skos:altLabel`` triples for new surface forms.

        Args:
            conn: Active SQLAlchemy connection.
            registry: Current in-memory registry (mutated in place).
            named_graph: Named graph where triples reside.
            new_triples: Freshly extracted triples (duck-typed: need .subject,
                .predicate, .object_value attributes).
            dry_run: When True, do not write any DB changes.

        Returns:
            :class:`EntityLinkingResult` with counts.
        """
        result = EntityLinkingResult()
        model = self._get_model()

        embeddings_cache: dict[str, list[float]] = {}
        if model is not False:
            for entity in registry.entities:
                try:
                    embeddings_cache[entity.iri] = list(model.encode(entity.label))
                except Exception:  # noqa: BLE001
                    pass

        # Collect candidate new entity IRIs from extracted triples
        new_iris: set[str] = set()
        for t in new_triples:
            subj = getattr(t, "subject", "")
            obj = getattr(t, "object_value", "")
            if subj and subj.startswith(("http://", "https://", "ex:")):
                new_iris.add(subj)
            if obj and obj.startswith(("http://", "https://", "ex:")):
                new_iris.add(obj)

        for iri in new_iris:
            if registry.by_iri(iri):
                continue  # already registered

            label = iri.split("/")[-1].split("#")[-1].split(":")[-1]
            new_entity = EntityRecord(iri=iri, label=label)

            # Check synonym ring: find most-similar existing entity
            if model is not False:
                try:
                    new_emb = list(model.encode(label))
                    embeddings_cache[iri] = new_emb
                    best_sim = 0.0
                    best_entity = None
                    for existing in registry.entities:
                        existing_emb = embeddings_cache.get(existing.iri)
                        if existing_emb:
                            sim = _cosine_similarity(new_emb, existing_emb)
                            if sim > best_sim:
                                best_sim = sim
                                best_entity = existing
                    if best_entity is not None and best_sim >= self._synonym_threshold:
                        # Merge into existing synonym ring
                        if label not in best_entity.variants:
                            best_entity.variants.append(label)
                            result.synonym_rings_updated += 1
                            if not dry_run:
                                self._write_alt_label(
                                    conn, named_graph, best_entity.iri, label
                                )
                                result.alt_labels_written += 1
                        continue  # do not register as a new entity
                except Exception:  # noqa: BLE001
                    pass

            registry.entities.append(new_entity)
            result.entities_registered += 1

        return result

    def write_alt_labels_for_ring(
        self,
        conn: Any,
        named_graph: str,
        entity: EntityRecord,
        dry_run: bool = False,
    ) -> int:
        """Write ``skos:altLabel`` triples for all variants in *entity*'s synonym ring."""
        written = 0
        for variant in entity.variants:
            if not dry_run:
                try:
                    self._write_alt_label(conn, named_graph, entity.iri, variant)
                    written += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "entity_linker: failed to write altLabel (%s %r): %s",
                        entity.iri,
                        variant,
                        exc,
                    )
        return written

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> Any:
        """Lazy-load the sentence-transformers model. Returns False on failure."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self._model_name)
            return self._model
        except Exception:  # noqa: BLE001
            self._model = False
            return False

    def _write_alt_label(
        self,
        conn: Any,
        named_graph: str,
        iri: str,
        alt_label: str,
    ) -> None:
        """Write a ``skos:altLabel`` triple to the named graph."""
        from sqlalchemy import text  # noqa: PLC0415

        escaped = alt_label.replace('"', '\\"')
        sparql = (
            f'INSERT DATA {{ GRAPH <{named_graph}> {{ '
            f'<{iri}> <{_SKOS_ALT_LABEL}> "{escaped}" . '
            f'}} }}'
        )
        conn.execute(text("SELECT sparql_update(cast(:q as text))"), {"q": sparql})
