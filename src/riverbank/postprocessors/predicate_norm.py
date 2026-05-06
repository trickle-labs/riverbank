"""Predicate normalization — embed, cluster, map to canonical forms (v0.13.0).

**Problem:** Unconstrained extraction produces a long tail of near-duplicate
predicates: ``ex:hasName``, ``ex:name``, ``ex:named`` all express the same
relationship.  Without normalization, SPARQL queries miss corroborating triples
and the graph grows with redundant predicate vocabulary.

**Approach:**

1. Query the named graph for all unique predicate IRIs.
2. Derive a human-readable label from the IRI local name (camelCase/snake_case
   splitting, e.g. ``hasDefinition`` → ``has definition``).
3. Embed each label using sentence-transformers (same model as entity dedup).
4. Greedy cosine-similarity clustering (default threshold 0.88 — slightly
   lower than entity dedup because predicate synonymy is more liberal).
5. Within each cluster, promote the shortest / most-frequent predicate as
   canonical; write ``owl:equivalentProperty`` links for the others.
6. Optionally map non-canonical predicates to their canonical forms in all
   existing triples (rewrite pass — off by default).

CLI::

    riverbank normalize-predicates \\
        --graph http://riverbank.example/graph/trusted \\
        --threshold 0.88 \\
        --dry-run

Falls back gracefully when sentence-transformers is not installed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# SPARQL — all unique predicates in the named graph
_PREDICATES_SPARQL = """\
SELECT DISTINCT ?p (COUNT(*) AS ?freq) WHERE {{
  GRAPH <{graph}> {{ ?s ?p ?o . }}
}} GROUP BY ?p ORDER BY DESC(?freq)
"""

# SPARQL — rewrite one predicate to canonical form
_REWRITE_SPARQL = """\
INSERT {{
  GRAPH <{graph}> {{ ?s <{canonical}> ?o . }}
}}
WHERE {{
  GRAPH <{graph}> {{ ?s <{non_canonical}> ?o . }}
}}
"""

_DELETE_SPARQL = """\
DELETE {{
  GRAPH <{graph}> {{ ?s <{non_canonical}> ?o . }}
}}
WHERE {{
  GRAPH <{graph}> {{ ?s <{non_canonical}> ?o . }}
}}
"""

# owl:equivalentProperty IRI
_OWL_EQUIVALENT_PROPERTY = "http://www.w3.org/2002/07/owl#equivalentProperty"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _label_from_iri(iri: str) -> str:
    """Derive a human-readable label from an IRI local name.

    Examples::

        >>> _label_from_iri("http://example.org/hasDefinition")
        'has definition'
        >>> _label_from_iri("ex:source_iri")
        'source iri'
    """
    local = iri.split("/")[-1].split("#")[-1].split(":")[-1]
    # camelCase → words
    local = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", local)
    local = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", local)
    # snake_case → words
    local = local.replace("_", " ").replace("-", " ")
    return local.strip().lower()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PredicateCluster:
    """A group of semantically equivalent predicates."""

    canonical: str           # promoted canonical predicate IRI
    aliases: list[str]       # non-canonical predicate IRIs in this cluster
    label: str               # human-readable label of the canonical predicate
    similarity: float        # average intra-cluster cosine similarity


@dataclass
class NormalizationResult:
    """Summary of a predicate normalization run."""

    predicates_examined: int = 0
    clusters_found: int = 0
    equivalent_property_written: int = 0
    triples_rewritten: int = 0
    clusters: list[PredicateCluster] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class PredicateNormalizer:
    """Embed predicate labels, cluster by cosine similarity, map to canonical forms.

    Args:
        model_name: sentence-transformers model identifier.  Defaults to
            ``all-MiniLM-L6-v2``.
        threshold: Cosine-similarity threshold for merging predicates.
            0.88 is a good default for predicate synonymy.
        rewrite: When ``True``, rewrite existing triples from non-canonical
            to canonical predicate IRIs (in addition to writing
            ``owl:equivalentProperty`` links).

    Falls back gracefully (returns an empty :class:`NormalizationResult`) when
    sentence-transformers is not installed or when pg_ripple is unavailable.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        threshold: float = 0.88,
        rewrite: bool = False,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._rewrite = rewrite
        self._model: Any = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(
        self,
        conn: Any,
        named_graph: str,
        dry_run: bool = False,
    ) -> NormalizationResult:
        """Run predicate normalization against *named_graph*.

        Args:
            conn: Active SQLAlchemy connection.
            named_graph: IRI of the named graph to normalize.
            dry_run: When ``True``, compute clusters but do not write any
                ``owl:equivalentProperty`` triples or rewrite predicates.

        Returns:
            :class:`NormalizationResult` with counts and cluster details.
        """
        result = NormalizationResult()

        # Step 1 — collect predicates and their frequencies.
        pred_freq = self._fetch_predicates(conn, named_graph)
        if not pred_freq:
            logger.info("normalize_predicates: no predicates found in <%s>", named_graph)
            return result

        # Filter out well-known ontology predicates that must not be remapped.
        pred_freq = {
            p: f for p, f in pred_freq.items()
            if not any(
                p.startswith(ns)
                for ns in (
                    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                    "http://www.w3.org/2000/01/rdf-schema#",
                    "http://www.w3.org/2002/07/owl#",
                    "http://www.w3.org/2004/02/skos/core#",
                )
            )
        }

        result.predicates_examined = len(pred_freq)
        logger.info(
            "normalize_predicates: examining %d unique predicates in <%s>",
            result.predicates_examined,
            named_graph,
        )

        if result.predicates_examined < 2:
            return result

        # Step 2 — embed predicate labels.
        model = self._get_model()
        if model is False:
            logger.warning(
                "normalize_predicates: sentence-transformers not installed — "
                "predicate normalization skipped"
            )
            return result

        iris = list(pred_freq.keys())
        labels = [_label_from_iri(iri) for iri in iris]
        try:
            embeddings = model.encode(labels, show_progress_bar=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("normalize_predicates: embedding failed — %s", exc)
            return result

        # Step 3 — cluster by cosine similarity.
        clusters = self._cluster(iris, embeddings, pred_freq, self._threshold)
        multi_clusters = [c for c in clusters if c.aliases]
        result.clusters_found = len(multi_clusters)
        result.clusters = multi_clusters

        if not multi_clusters:
            logger.info(
                "normalize_predicates: no equivalent predicates found (threshold=%.2f)",
                self._threshold,
            )
            return result

        logger.info(
            "normalize_predicates: found %d predicate clusters (%d owl:equivalentProperty links needed)",
            len(multi_clusters),
            sum(len(c.aliases) for c in multi_clusters),
        )

        if dry_run:
            logger.info("normalize_predicates: dry-run — not writing equivalentProperty triples")
            return result

        # Step 4 — write owl:equivalentProperty triples.
        written = self._write_equivalent_property(conn, named_graph, multi_clusters)
        result.equivalent_property_written = written
        logger.info(
            "normalize_predicates: wrote %d owl:equivalentProperty triples to <%s>",
            written,
            named_graph,
        )

        # Step 5 — optional predicate rewrite pass.
        if self._rewrite:
            rewritten = self._rewrite_triples(conn, named_graph, multi_clusters)
            result.triples_rewritten = rewritten
            logger.info(
                "normalize_predicates: rewrote %d triples to canonical predicates",
                rewritten,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_predicates(self, conn: Any, named_graph: str) -> dict[str, int]:
        """Return ``{predicate_iri: frequency}`` for all predicates in the graph."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = _PREDICATES_SPARQL.format(graph=named_graph)
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning("normalize_predicates: SPARQL query failed — %s", exc)
            return {}

        result: dict[str, int] = {}
        for row in rows:
            p = str(row.get("p", "")).strip()
            freq_raw = row.get("freq", 1)
            try:
                freq = int(float(str(freq_raw)))
            except (ValueError, TypeError):
                freq = 1
            if p:
                result[p] = freq
        return result

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

    def _cluster(
        self,
        iris: list[str],
        embeddings: Any,
        freq: dict[str, int],
        threshold: float,
    ) -> list[PredicateCluster]:
        """Greedy single-pass cosine-similarity clustering.

        Within each cluster, the predicate with the highest frequency (or
        shortest IRI as tiebreaker) is promoted as canonical.
        """
        n = len(iris)
        assigned: list[int] = [-1] * n  # cluster id for each predicate
        clusters: list[list[int]] = []

        for i in range(n):
            if assigned[i] != -1:
                continue
            cluster_id = len(clusters)
            cluster_members = [i]
            assigned[i] = cluster_id
            for j in range(i + 1, n):
                if assigned[j] != -1:
                    continue
                try:
                    sim = _cosine_similarity(
                        list(embeddings[i]),
                        list(embeddings[j]),
                    )
                except Exception:  # noqa: BLE001
                    sim = 0.0
                if sim >= threshold:
                    cluster_members.append(j)
                    assigned[j] = cluster_id
            clusters.append(cluster_members)

        result: list[PredicateCluster] = []
        for members in clusters:
            if len(members) < 2:
                # Singleton — still create a cluster with no aliases
                i = members[0]
                result.append(
                    PredicateCluster(
                        canonical=iris[i],
                        aliases=[],
                        label=_label_from_iri(iris[i]),
                        similarity=1.0,
                    )
                )
                continue

            # Pick canonical: highest frequency, then shortest IRI.
            sorted_members = sorted(
                members,
                key=lambda i: (-freq.get(iris[i], 0), len(iris[i])),
            )
            canonical_idx = sorted_members[0]
            alias_idxs = sorted_members[1:]

            # Average intra-cluster similarity
            sims: list[float] = []
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    try:
                        sims.append(
                            _cosine_similarity(
                                list(embeddings[members[a]]),
                                list(embeddings[members[b]]),
                            )
                        )
                    except Exception:  # noqa: BLE001
                        pass
            avg_sim = sum(sims) / len(sims) if sims else threshold

            result.append(
                PredicateCluster(
                    canonical=iris[canonical_idx],
                    aliases=[iris[i] for i in alias_idxs],
                    label=_label_from_iri(iris[canonical_idx]),
                    similarity=avg_sim,
                )
            )

        return result

    def _write_equivalent_property(
        self,
        conn: Any,
        named_graph: str,
        clusters: list[PredicateCluster],
    ) -> int:
        """Write ``owl:equivalentProperty`` triples for each alias → canonical mapping."""
        from sqlalchemy import text  # noqa: PLC0415

        written = 0
        for cluster in clusters:
            for alias in cluster.aliases:
                try:
                    conn.execute(
                        text(
                            "SELECT sparql_update(cast(:q as text))"
                        ),
                        {
                            "q": (
                                f"INSERT DATA {{ GRAPH <{named_graph}> {{ "
                                f"<{alias}> <{_OWL_EQUIVALENT_PROPERTY}> <{cluster.canonical}> . "
                                f"}} }}"
                            )
                        },
                    )
                    written += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "normalize_predicates: failed to write equivalentProperty (%s → %s): %s",
                        alias,
                        cluster.canonical,
                        exc,
                    )
        return written

    def _rewrite_triples(
        self,
        conn: Any,
        named_graph: str,
        clusters: list[PredicateCluster],
    ) -> int:
        """Rewrite all triples using non-canonical predicates to use the canonical IRI."""
        from sqlalchemy import text  # noqa: PLC0415

        rewritten = 0
        for cluster in clusters:
            for alias in cluster.aliases:
                try:
                    conn.execute(
                        text("SELECT sparql_update(cast(:q as text))"),
                        {
                            "q": _REWRITE_SPARQL.format(
                                graph=named_graph,
                                canonical=cluster.canonical,
                                non_canonical=alias,
                            )
                        },
                    )
                    conn.execute(
                        text("SELECT sparql_update(cast(:q as text))"),
                        {
                            "q": _DELETE_SPARQL.format(
                                graph=named_graph,
                                non_canonical=alias,
                            )
                        },
                    )
                    rewritten += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "normalize_predicates: rewrite failed (%s → %s): %s",
                        alias,
                        cluster.canonical,
                        exc,
                    )
        return rewritten
