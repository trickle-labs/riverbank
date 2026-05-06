from __future__ import annotations

"""Coverage maps via pg_ripple.refresh_coverage_map() (v0.8.0).

``pg_ripple.refresh_coverage_map()`` computes per-topic source density, mean
confidence, contradiction count, and recency into the ``<coverage>`` named
graph.

riverbank's contribution is the Prefect flow that:
1. Calls ``pg_ripple.refresh_coverage_map()`` to refresh the coverage data.
2. Joins the result against ``_riverbank.profiles.competency_questions`` to
   compute the unanswered-question count (the one join that requires
   riverbank's catalog).
3. Writes enriched ``pgc:CoverageMap`` triples surfaced by ``rag_context()``.

When pg_ripple is unavailable, the module degrades gracefully — coverage map
generation is deferred (consistent with the roadmap mitigation policy).
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pgc: vocabulary IRIs
# ---------------------------------------------------------------------------

_PGC_COVERAGE_MAP = "http://schema.pgc.example/CoverageMap"
_PGC_TOPIC_IRI = "http://schema.pgc.example/topicIri"
_PGC_SOURCE_DENSITY = "http://schema.pgc.example/sourceDensity"
_PGC_MEAN_CONFIDENCE = "http://schema.pgc.example/meanConfidence"
_PGC_CONTRADICTION_COUNT = "http://schema.pgc.example/contradictionCount"
_PGC_UNANSWERED_CQ_COUNT = "http://schema.pgc.example/unansweredCompetencyQuestionCount"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

_COVERAGE_GRAPH = "http://riverbank.example/graph/coverage"

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class CoverageMapEntry:
    """A single entry in the coverage map.

    Attributes:
        topic_iri:          IRI identifying the topic or concept.
        source_density:     Number of source fragments covering this topic.
        mean_confidence:    Mean confidence of facts about this topic [0, 1].
        contradiction_count: Number of known contradictions for this topic.
        unanswered_cq_count: Number of competency questions still unanswered.
    """

    topic_iri: str
    source_density: int = 0
    mean_confidence: float = 0.0
    contradiction_count: int = 0
    unanswered_cq_count: int = 0


# ---------------------------------------------------------------------------
# pg_ripple delegation
# ---------------------------------------------------------------------------

def refresh_coverage_map(
    conn: Any,
    named_graph: str = "http://riverbank.example/graph/trusted",
    coverage_graph: str = _COVERAGE_GRAPH,
) -> bool:
    """Call ``pg_ripple.refresh_coverage_map()`` to update the coverage graph.

    Falls back gracefully (returns ``False``) when pg_ripple is unavailable.
    The roadmap mitigation policy allows coverage map generation to be
    deferred when ``pg_ripple.refresh_coverage_map()`` is unavailable.
    """
    try:
        conn.execute(
            "SELECT pg_ripple.refresh_coverage_map($1, $2)",
            (named_graph, coverage_graph),
        )
        logger.info(
            "refresh_coverage_map: refreshed coverage graph %s from %s",
            coverage_graph,
            named_graph,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function",
                       "refresh_coverage_map")
        ):
            logger.warning(
                "pg_ripple.refresh_coverage_map not available — "
                "coverage map generation deferred (roadmap mitigation). error=%s",
                exc,
            )
            return False
        raise


def compute_unanswered_cq_count(
    conn: Any,
    competency_questions: list[dict],
    named_graph: str = "http://riverbank.example/graph/trusted",
) -> int:
    """Compute the number of competency questions not yet answered by the graph.

    Each competency question is a dict with a ``sparql`` key (an ASK query).
    Returns the count of questions whose ASK query returns False, or the total
    count when pg_ripple is unavailable.
    """
    if not competency_questions:
        return 0

    from riverbank.catalog.graph import sparql_query
    
    unanswered = 0
    for cq in competency_questions:
        sparql = str(cq.get("sparql", ""))
        if not sparql:
            continue
        try:
            rows = sparql_query(conn, sparql, named_graph=named_graph)
            # ASK query returns a single row with the boolean result
            if rows:
                row = rows[0]
                result_val = next(iter(row.values())) if isinstance(row, dict) else row[0]
                answered = bool(result_val)
            else:
                answered = False
            if not answered:
                unanswered += 1
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if any(
                kw in msg
                for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
            ):
                logger.debug("compute_unanswered_cq_count: pg_ripple not available: %s", exc)
                return len(competency_questions)
            logger.debug("compute_unanswered_cq_count: CQ evaluation failed: %s", exc)
            unanswered += 1

    return unanswered


def write_coverage_map_entry(
    conn: Any,
    entry: CoverageMapEntry,
    coverage_graph: str = _COVERAGE_GRAPH,
) -> bool:
    """Write a ``pgc:CoverageMap`` entry to the coverage graph.

    Falls back gracefully when pg_ripple is unavailable.
    """
    import json as _json  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    map_iri = (
        "http://riverbank.example/coverage/"
        + hashlib.sha256(entry.topic_iri.encode()).hexdigest()[:16]
    )

    triples: list[dict] = [
        {
            "subject": map_iri,
            "predicate": _RDF_TYPE,
            "object": _PGC_COVERAGE_MAP,
            "confidence": 1.0,
            "named_graph": coverage_graph,
            "prov_fragment_iri": "",
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": map_iri,
            "predicate": _PGC_TOPIC_IRI,
            "object": entry.topic_iri,
            "confidence": 1.0,
            "named_graph": coverage_graph,
            "prov_fragment_iri": "",
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": map_iri,
            "predicate": _PGC_SOURCE_DENSITY,
            "object": str(entry.source_density),
            "confidence": 1.0,
            "named_graph": coverage_graph,
            "prov_fragment_iri": "",
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": map_iri,
            "predicate": _PGC_MEAN_CONFIDENCE,
            "object": str(round(entry.mean_confidence, 4)),
            "confidence": 1.0,
            "named_graph": coverage_graph,
            "prov_fragment_iri": "",
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": map_iri,
            "predicate": _PGC_CONTRADICTION_COUNT,
            "object": str(entry.contradiction_count),
            "confidence": 1.0,
            "named_graph": coverage_graph,
            "prov_fragment_iri": "",
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": map_iri,
            "predicate": _PGC_UNANSWERED_CQ_COUNT,
            "object": str(entry.unanswered_cq_count),
            "confidence": 1.0,
            "named_graph": coverage_graph,
            "prov_fragment_iri": "",
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
    ]

    try:
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)",
            (_json.dumps(triples), coverage_graph),
        )
        logger.debug(
            "write_coverage_map_entry: wrote %d triples for topic=%s",
            len(triples),
            entry.topic_iri,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.warning(
                "pg_ripple not available — coverage map entry not written. error=%s",
                exc,
            )
            return False
        raise
