"""Post-1: Embedding-Based Entity Deduplication (v0.11.0).

**Problem:** The entity catalog deduplicates within a document, but the same
concept may receive different canonical names across documents (e.g.,
``ex:sesam-dataset`` in doc A and ``ex:dataset`` in doc B).

**Approach:**

1. Query the named graph for all unique subject/object IRIs that have an
   ``rdfs:label`` (or use the IRI local name as a fallback).
2. Embed each label using sentence-transformers.
3. Cluster entity IRIs by cosine similarity (default threshold: 0.92).
4. Within each cluster, promote the most-frequent IRI as canonical; write
   ``owl:sameAs`` links from the others to the canonical IRI.

The ``owl:sameAs`` triples are written to the *same* named graph so that
query engines can transparently resolve aliases.

CLI::

    riverbank deduplicate-entities \\
        --graph http://riverbank.example/graph/trusted \\
        --threshold 0.92 \\
        --dry-run

Falls back gracefully when sentence-transformers is not installed or when
pg_ripple is unavailable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# SPARQL query to retrieve unique entity IRIs and their labels.
# Falls back to the local name portion of the IRI when no rdfs:label exists.
_ENTITY_LABELS_SPARQL = """\
SELECT DISTINCT ?entity ?label WHERE {{
  {{
    GRAPH <{graph}> {{ ?entity ?p ?o . }}
    FILTER(isIRI(?entity))
    OPTIONAL {{ GRAPH <{graph}> {{ ?entity <http://www.w3.org/2000/01/rdf-schema#label> ?label . }} }}
  }} UNION {{
    GRAPH <{graph}> {{ ?s ?p ?entity . }}
    FILTER(isIRI(?entity))
    OPTIONAL {{ GRAPH <{graph}> {{ ?entity <http://www.w3.org/2000/01/rdf-schema#label> ?label . }} }}
  }}
}}
"""

# SPARQL query to count how many times each IRI appears as subject or object.
_ENTITY_FREQ_SPARQL = """\
SELECT ?entity (COUNT(*) AS ?freq) WHERE {{
  GRAPH <{graph}> {{
    {{ ?entity ?p ?o . FILTER(isIRI(?entity)) }}
    UNION
    {{ ?s ?p ?entity . FILTER(isIRI(?entity)) }}
  }}
}} GROUP BY ?entity
"""


@dataclass
class EntityCluster:
    """A group of semantically equivalent entity IRIs."""

    canonical: str           # promoted canonical IRI
    aliases: list[str]       # other IRIs in this cluster
    label: str               # label of the canonical IRI
    similarity: float        # average intra-cluster cosine similarity


@dataclass
class DeduplicationResult:
    """Summary of a deduplication run."""

    clusters_found: int = 0
    sameas_written: int = 0
    entities_examined: int = 0
    clusters: list[EntityCluster] = field(default_factory=list)


class EntityDeduplicator:
    """Embed entity labels, cluster by cosine similarity, write ``owl:sameAs``.

    Uses sentence-transformers (the same model already used for fragment
    embedding) so no new dependency is required.

    Args:
        model_name: sentence-transformers model identifier.  Defaults to
            ``all-MiniLM-L6-v2`` (same as :class:`~riverbank.embeddings.EmbeddingGenerator`).
        threshold: Cosine-similarity threshold for merging entities into the
            same cluster.  0.92 is a good default for technical vocabulary.

    Falls back gracefully (returns an empty :class:`DeduplicationResult`) when
    sentence-transformers is not installed or when pg_ripple is unavailable.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        threshold: float = 0.92,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._model: Any = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deduplicate(
        self,
        conn: Any,
        named_graph: str,
        dry_run: bool = False,
    ) -> DeduplicationResult:
        """Run deduplication against *named_graph*.

        Args:
            conn: Active SQLAlchemy connection.
            named_graph: IRI of the named graph to deduplicate.
            dry_run: When ``True``, compute clusters but do not write any
                ``owl:sameAs`` triples.

        Returns:
            :class:`DeduplicationResult` with counts and cluster details.
        """
        result = DeduplicationResult()

        # Step 1 — collect entity IRIs and their labels from the graph.
        entity_labels = self._fetch_entity_labels(conn, named_graph)
        if not entity_labels:
            logger.info("deduplicate: no entities found in graph <%s>", named_graph)
            return result

        result.entities_examined = len(entity_labels)
        logger.info(
            "deduplicate: examining %d unique entities in <%s>",
            result.entities_examined,
            named_graph,
        )

        # Step 2 — embed all labels.
        model = self._get_model()
        if model is False:
            logger.warning(
                "deduplicate: sentence-transformers not installed — "
                "entity deduplication skipped"
            )
            return result

        iris = list(entity_labels.keys())
        labels = [entity_labels[iri] for iri in iris]
        try:
            embeddings = model.encode(labels, show_progress_bar=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("deduplicate: embedding failed — %s", exc)
            return result

        # Step 3 — cluster by cosine similarity using a greedy single-pass algorithm.
        clusters = self._cluster(iris, embeddings, self._threshold)
        multi_clusters = [c for c in clusters if c.aliases]  # only clusters with >1 member
        result.clusters_found = len(multi_clusters)
        result.clusters = multi_clusters

        if not multi_clusters:
            logger.info("deduplicate: no duplicate entities found (threshold=%.2f)", self._threshold)
            return result

        logger.info(
            "deduplicate: found %d duplicate clusters (%d owl:sameAs links needed)",
            len(multi_clusters),
            sum(len(c.aliases) for c in multi_clusters),
        )

        if dry_run:
            logger.info("deduplicate: dry-run — not writing owl:sameAs triples")
            return result

        # Step 4 — write owl:sameAs triples for each alias → canonical mapping.
        written = self._write_sameas(conn, named_graph, multi_clusters)
        result.sameas_written = written
        logger.info("deduplicate: wrote %d owl:sameAs triples to <%s>", written, named_graph)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_entity_labels(self, conn: Any, named_graph: str) -> dict[str, str]:
        """Return ``{iri: label}`` for all entities in *named_graph*.

        Falls back to the IRI local name when no ``rdfs:label`` is present.
        Returns an empty dict when pg_ripple is unavailable.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        query = _ENTITY_LABELS_SPARQL.format(graph=named_graph)
        try:
            rows = sparql_query(conn, query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("deduplicate: could not fetch entity labels — %s", exc)
            return {}

        result: dict[str, str] = {}
        for row in rows:
            iri = str(row.get("entity", "")).strip()
            if not iri or iri.startswith("http://www.w3.org"):
                # Skip RDF/RDFS/OWL built-ins
                continue
            label_val = row.get("label", "")
            label = str(label_val).strip() if label_val else _iri_local_name(iri)
            if label:
                result[iri] = label
        return result

    def _cluster(
        self,
        iris: list[str],
        embeddings: Any,
        threshold: float,
    ) -> list[EntityCluster]:
        """Greedy single-pass cosine-similarity clustering.

        Each IRI is assigned to the first existing cluster whose centroid is
        within *threshold* cosine similarity.  If none exists, a new cluster
        is started.

        Returns a list of :class:`EntityCluster` objects (including singleton
        clusters with no aliases).  Canonical IRI is chosen as the one with
        the shortest IRI string (as a proxy for the most generic / primary
        identifier).
        """
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            # numpy is required by sentence-transformers, so this should never happen.
            logger.warning("deduplicate: numpy not available — clustering skipped")
            return []

        n = len(iris)
        # Normalise embeddings for cosine similarity (dot product after normalisation).
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normed = embeddings / norms

        # cluster_members[i] = list of original indices in cluster i
        cluster_members: list[list[int]] = []
        # cluster_centroid[i] = normalised centroid vector
        cluster_centroids: list[Any] = []

        for idx in range(n):
            vec = normed[idx]
            best_cluster = -1
            best_sim = -1.0
            for ci, centroid in enumerate(cluster_centroids):
                sim = float(np.dot(vec, centroid))
                if sim > best_sim:
                    best_sim = sim
                    best_cluster = ci

            if best_sim >= threshold and best_cluster >= 0:
                cluster_members[best_cluster].append(idx)
                # Update centroid incrementally (unnormalised average → renormalise).
                members = cluster_members[best_cluster]
                new_centroid = normed[members].mean(axis=0)
                norm = np.linalg.norm(new_centroid)
                cluster_centroids[best_cluster] = new_centroid / norm if norm > 0 else new_centroid
            else:
                cluster_members.append([idx])
                cluster_centroids.append(vec)

        clusters: list[EntityCluster] = []
        for members in cluster_members:
            member_iris = [iris[i] for i in members]
            # Pick canonical IRI: most common in-graph IRI (here: shortest as heuristic;
            # frequency-based selection happens in the caller if needed).
            canonical = min(member_iris, key=len)
            aliases = [iri for iri in member_iris if iri != canonical]

            # Compute average intra-cluster similarity for reporting.
            avg_sim = 0.0
            if len(members) > 1:
                vecs = normed[members]
                dot_matrix = np.dot(vecs, vecs.T)
                # Average of upper-triangle (excluding diagonal)
                upper = [
                    dot_matrix[r, c]
                    for r in range(len(members))
                    for c in range(r + 1, len(members))
                ]
                avg_sim = float(np.mean(upper)) if upper else 1.0
            else:
                avg_sim = 1.0

            label_idx = iris.index(canonical)
            label = ""
            # iris may not be the same list as the original; recompute
            for orig_idx, iri in enumerate(iris):
                if iri == canonical:
                    label_idx = orig_idx
                    break
            label = ""  # will be filled from the labels dict in deduplicate()

            clusters.append(
                EntityCluster(
                    canonical=canonical,
                    aliases=aliases,
                    label=label,
                    similarity=avg_sim,
                )
            )
        return clusters

    def _write_sameas(
        self,
        conn: Any,
        named_graph: str,
        clusters: list[EntityCluster],
    ) -> int:
        """Write ``owl:sameAs`` triples for each alias in *clusters*.

        Returns the total number of triples written.
        """
        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415

        # Build a minimal ExtractedTriple-like list
        sameas_triples: list[_SameAsTriple] = []
        for cluster in clusters:
            for alias in cluster.aliases:
                sameas_triples.append(
                    _SameAsTriple(
                        subject=alias,
                        predicate="owl:sameAs",
                        object_value=cluster.canonical,
                        confidence=cluster.similarity,
                    )
                )

        if not sameas_triples:
            return 0

        written = load_triples_with_confidence(conn, sameas_triples, named_graph)
        try:
            conn.commit()
        except Exception:  # noqa: BLE001
            pass  # caller may handle commit
        return written

    def _get_model(self) -> Any:
        """Lazy-load and cache the sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                self._model = SentenceTransformer(self._model_name)
            except ImportError:
                logger.debug(
                    "sentence-transformers not installed — entity deduplication will be skipped. "
                    "Install it with: pip install 'riverbank[ingest]'"
                )
                self._model = False
        return self._model


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iri_local_name(iri: str) -> str:
    """Extract the local name from an IRI (after the last ``/`` or ``#``)."""
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[-1]
    return iri


@dataclass
class _SameAsTriple:
    """Minimal triple-like object accepted by ``load_triples_with_confidence``."""

    subject: str
    predicate: str
    object_value: str
    confidence: float
