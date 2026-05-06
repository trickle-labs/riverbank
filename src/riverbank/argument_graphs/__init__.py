from __future__ import annotations

"""Argument graph records for structured reasoning (v0.8.0).

Implements ``pgc:ArgumentRecord`` — a structured representation of claims,
evidence, objections, and rebuttals extracted from text.  Argument graphs
allow SPARQL navigation of the reasoning structure: "which policy conclusions
have a recorded objection but no rebuttal?"

The Label Studio annotation template (side-by-side span annotation) is
defined in the Label Studio profile for this extractor.  riverbank's Python
side handles:
- Extraction of argument structure from text (via ``ArgumentExtractor``).
- Persistence of ``pgc:ArgumentRecord`` triples via pg_ripple.
- SPARQL query helpers for navigating the argument graph.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pgc: vocabulary IRIs for argument graphs
# ---------------------------------------------------------------------------

_PGC_ARGUMENT_RECORD = "http://schema.pgc.example/ArgumentRecord"
_PGC_HAS_CLAIM = "http://schema.pgc.example/hasClaim"
_PGC_HAS_EVIDENCE = "http://schema.pgc.example/hasEvidence"
_PGC_HAS_OBJECTION = "http://schema.pgc.example/hasObjection"
_PGC_HAS_REBUTTAL = "http://schema.pgc.example/hasRebuttal"
_PGC_CLAIM_TEXT = "http://schema.pgc.example/claimText"
_PGC_EVIDENCE_TEXT = "http://schema.pgc.example/evidenceText"
_PGC_OBJECTION_TEXT = "http://schema.pgc.example/objectionText"
_PGC_REBUTTAL_TEXT = "http://schema.pgc.example/rebuttalText"
_PROV_WAS_DERIVED_FROM = "http://www.w3.org/ns/prov#wasDerivedFrom"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ArgumentSpan:
    """A single span (claim, evidence, objection, or rebuttal) within an ArgumentRecord."""

    text: str
    char_start: int = 0
    char_end: int = 0
    source_iri: str = ""


@dataclass
class ArgumentRecord:
    """A structured argument extracted from a source fragment.

    Attributes:
        record_iri:  IRI identifying this argument record.
        claim:       The central claim being argued.
        evidence:    Supporting evidence nodes (at least one required).
        objections:  Recorded objections to the claim.
        rebuttals:   Rebuttals addressing the objections.
        source_iri:  Source fragment IRI for provenance.
        named_graph: Target named graph.
    """

    record_iri: str
    claim: ArgumentSpan
    evidence: list[ArgumentSpan] = field(default_factory=list)
    objections: list[ArgumentSpan] = field(default_factory=list)
    rebuttals: list[ArgumentSpan] = field(default_factory=list)
    source_iri: str = ""
    named_graph: str = "http://riverbank.example/graph/trusted"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_argument_record(
    conn: Any,
    record: ArgumentRecord,
) -> bool:
    """Write a ``pgc:ArgumentRecord`` to the graph via pg_ripple.

    Writes the record type triple plus all claim, evidence, objection, and
    rebuttal triples.  Falls back gracefully when pg_ripple is unavailable.
    """
    import json as _json  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    def _span_iri(role: str, index: int) -> str:
        h = hashlib.sha256(
            f"{record.record_iri}|{role}|{index}".encode()
        ).hexdigest()[:12]
        return f"http://riverbank.example/arg/{h}"

    triples: list[dict] = [
        {
            "subject": record.record_iri,
            "predicate": _RDF_TYPE,
            "object": _PGC_ARGUMENT_RECORD,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
    ]

    # Claim
    claim_iri = _span_iri("claim", 0)
    triples += [
        {
            "subject": record.record_iri,
            "predicate": _PGC_HAS_CLAIM,
            "object": claim_iri,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": record.claim.char_start,
            "prov_char_end": record.claim.char_end,
            "prov_excerpt": record.claim.text[:200],
        },
        {
            "subject": claim_iri,
            "predicate": _PGC_CLAIM_TEXT,
            "object": record.claim.text,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": record.claim.char_start,
            "prov_char_end": record.claim.char_end,
            "prov_excerpt": record.claim.text[:200],
        },
    ]

    # Evidence nodes
    for i, ev in enumerate(record.evidence):
        ev_iri = _span_iri("evidence", i)
        triples += [
            {
                "subject": record.record_iri,
                "predicate": _PGC_HAS_EVIDENCE,
                "object": ev_iri,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": ev.char_start,
                "prov_char_end": ev.char_end,
                "prov_excerpt": ev.text[:200],
            },
            {
                "subject": ev_iri,
                "predicate": _PGC_EVIDENCE_TEXT,
                "object": ev.text,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": ev.char_start,
                "prov_char_end": ev.char_end,
                "prov_excerpt": ev.text[:200],
            },
        ]

    # Objections
    for i, obj in enumerate(record.objections):
        obj_iri = _span_iri("objection", i)
        triples += [
            {
                "subject": record.record_iri,
                "predicate": _PGC_HAS_OBJECTION,
                "object": obj_iri,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": obj.char_start,
                "prov_char_end": obj.char_end,
                "prov_excerpt": obj.text[:200],
            },
            {
                "subject": obj_iri,
                "predicate": _PGC_OBJECTION_TEXT,
                "object": obj.text,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": obj.char_start,
                "prov_char_end": obj.char_end,
                "prov_excerpt": obj.text[:200],
            },
        ]

    # Rebuttals
    for i, reb in enumerate(record.rebuttals):
        reb_iri = _span_iri("rebuttal", i)
        triples += [
            {
                "subject": record.record_iri,
                "predicate": _PGC_HAS_REBUTTAL,
                "object": reb_iri,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": reb.char_start,
                "prov_char_end": reb.char_end,
                "prov_excerpt": reb.text[:200],
            },
            {
                "subject": reb_iri,
                "predicate": _PGC_REBUTTAL_TEXT,
                "object": reb.text,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": reb.char_start,
                "prov_char_end": reb.char_end,
                "prov_excerpt": reb.text[:200],
            },
        ]

    # Provenance
    if record.source_iri:
        triples.append(
            {
                "subject": record.record_iri,
                "predicate": _PROV_WAS_DERIVED_FROM,
                "object": record.source_iri,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": 0,
                "prov_char_end": 0,
                "prov_excerpt": "",
            }
        )

    try:
        import json as _json2  # noqa: PLC0415

        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)",
            (_json2.dumps(triples), record.named_graph),
        )
        logger.debug(
            "write_argument_record: wrote %d triples for record_iri=%s",
            len(triples),
            record.record_iri,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.warning(
                "pg_ripple not available — argument record not written. error=%s",
                exc,
            )
            return False
        raise


# ---------------------------------------------------------------------------
# SPARQL query helpers
# ---------------------------------------------------------------------------

_UNANSWERED_OBJECTIONS_SPARQL = """\
SELECT ?record ?claim_text ?objection_text WHERE {{
  GRAPH <{graph}> {{
    ?record a <{arg_class}> .
    ?record <{has_claim}>     ?claim .
    ?record <{has_objection}> ?objection .
    ?claim  <{claim_text}>    ?claim_text .
    ?objection <{objection_text}> ?objection_text .
    FILTER NOT EXISTS {{
      ?record <{has_rebuttal}> ?rebuttal .
    }}
  }}
}}
""".format(
    graph="http://riverbank.example/graph/trusted",
    arg_class=_PGC_ARGUMENT_RECORD,
    has_claim=_PGC_HAS_CLAIM,
    has_objection=_PGC_HAS_OBJECTION,
    claim_text=_PGC_CLAIM_TEXT,
    objection_text=_PGC_OBJECTION_TEXT,
    has_rebuttal=_PGC_HAS_REBUTTAL,
)


def query_unanswered_objections(
    conn: Any,
    named_graph: str = "http://riverbank.example/graph/trusted",
) -> list[dict]:
    """Return argument records that have objections but no rebuttals.

    Useful for finding policy conclusions that are contested but unresolved.
    Falls back to ``[]`` when pg_ripple is unavailable.
    """
    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    
    sparql = _UNANSWERED_OBJECTIONS_SPARQL.replace(
        "http://riverbank.example/graph/trusted", named_graph
    )
    try:
        rows = sparql_query(conn, sparql, named_graph=named_graph)
        if not rows:
            return []
        return rows
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.debug("query_unanswered_objections: pg_ripple not available: %s", exc)
        else:
            logger.debug("query_unanswered_objections failed: %s", exc)
        return []
