from __future__ import annotations

"""Assumption registry — RDF-star annotations for extracted assumptions (v0.8.0).

Every fact that depends on an unstated assumption can carry an
``pgc:assumption`` RDF-star annotation.  The assumption is surfaced by
``rag_context()`` alongside answers, making epistemic caveats visible to
consumers.

riverbank's Python side:
- Provides ``AssumptionRecord`` to represent a single assumption.
- Writes assumption annotations as reified triples (since pg_ripple may not
  yet expose a full RDF-star surface; reification is the safe default).
- Provides ``get_assumptions_for_fact`` to retrieve assumptions attached to
  a given subject–predicate–object triple.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pgc: vocabulary IRIs
# ---------------------------------------------------------------------------

_PGC_ASSUMPTION = "http://schema.pgc.example/Assumption"
_PGC_HAS_ASSUMPTION = "http://schema.pgc.example/hasAssumption"
_PGC_ASSUMPTION_TEXT = "http://schema.pgc.example/assumptionText"
_PGC_ASSUMPTION_CONFIDENCE = "http://schema.pgc.example/assumptionConfidence"
_PGC_ABOUT_SUBJECT = "http://schema.pgc.example/aboutSubject"
_PGC_ABOUT_PREDICATE = "http://schema.pgc.example/aboutPredicate"
_PGC_ABOUT_OBJECT = "http://schema.pgc.example/aboutObject"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class AssumptionRecord:
    """An assumption attached to a specific fact.

    Attributes:
        subject:      IRI of the fact's subject.
        predicate:    IRI of the fact's predicate.
        object_value: Object of the fact (IRI or literal string).
        assumption_text: Human-readable description of the assumption.
        confidence:   Confidence that the assumption is valid [0.0, 1.0].
        source_iri:   Source fragment IRI.
        named_graph:  Target named graph.
    """

    subject: str
    predicate: str
    object_value: str
    assumption_text: str
    confidence: float = 1.0
    source_iri: str = ""
    named_graph: str = "http://riverbank.example/graph/trusted"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_assumption(
    conn: Any,
    record: AssumptionRecord,
) -> bool:
    """Write an assumption annotation to the graph via pg_ripple.

    Uses reification (not RDF-star syntax) for maximum compatibility:
    creates a blank-node-like IRI for the reified statement and attaches
    ``pgc:assumptionText``, ``pgc:assumptionConfidence``, and links back
    to subject/predicate/object.

    Falls back gracefully when pg_ripple is unavailable.
    """
    import json as _json  # noqa: PLC0415

    # Deterministic IRI for the reification node
    digest = hashlib.sha256(
        f"{record.subject}|{record.predicate}|{record.object_value}|{record.assumption_text}".encode()
    ).hexdigest()[:16]
    assumption_iri = f"http://riverbank.example/assumption/{digest}"

    triples: list[dict] = [
        {
            "subject": assumption_iri,
            "predicate": _RDF_TYPE,
            "object": _PGC_ASSUMPTION,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": assumption_iri,
            "predicate": _PGC_ABOUT_SUBJECT,
            "object": record.subject,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": assumption_iri,
            "predicate": _PGC_ABOUT_PREDICATE,
            "object": record.predicate,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": assumption_iri,
            "predicate": _PGC_ABOUT_OBJECT,
            "object": record.object_value,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": assumption_iri,
            "predicate": _PGC_ASSUMPTION_TEXT,
            "object": record.assumption_text,
            "confidence": record.confidence,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": assumption_iri,
            "predicate": _PGC_ASSUMPTION_CONFIDENCE,
            "object": str(record.confidence),
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
    ]

    try:
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)",
            (_json.dumps(triples), record.named_graph),
        )
        logger.debug(
            "write_assumption: wrote %d triples for assumption_iri=%s",
            len(triples),
            assumption_iri,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.warning(
                "pg_ripple not available — assumption not written. error=%s",
                exc,
            )
            return False
        raise


def get_assumptions_for_fact(
    conn: Any,
    subject: str,
    predicate: str,
    object_value: str,
    named_graph: str = "http://riverbank.example/graph/trusted",
) -> list[str]:
    """Retrieve assumption texts attached to a given fact.

    Returns a list of assumption text strings, or ``[]`` when none exist or
    pg_ripple is unavailable.
    """
    sparql = f"""\
SELECT ?assumption_text WHERE {{
  GRAPH <{named_graph}> {{
    ?a a <{_PGC_ASSUMPTION}> .
    ?a <{_PGC_ABOUT_SUBJECT}>    <{subject}> .
    ?a <{_PGC_ABOUT_PREDICATE}>  <{predicate}> .
    ?a <{_PGC_ASSUMPTION_TEXT}>  ?assumption_text .
  }}
}}
"""
    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    
    try:
        rows = sparql_query(conn, sparql, named_graph=named_graph)
        if not rows:
            return []
        result = []
        for row in rows:
            val = next(iter(row.values())) if isinstance(row, dict) else next(iter(row))
            if val:
                result.append(str(val))
        return result
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.debug("get_assumptions_for_fact: pg_ripple not available: %s", exc)
        else:
            logger.debug("get_assumptions_for_fact failed: %s", exc)
        return []
