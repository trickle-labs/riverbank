from __future__ import annotations

"""Epistemic status layer — all 9 pgc:epistemicStatus values (v0.8.0).

Every fact in the knowledge graph can carry a ``pgc:epistemicStatus``
annotation.  The nine status values cover the full lifecycle of a fact:

- ``observed``   — directly witnessed / measured
- ``extracted``  — derived by the LLM compiler from source text
- ``inferred``   — derived by Datalog forward-chaining rules
- ``verified``   — confirmed by a human reviewer via Label Studio
- ``deprecated`` — superseded; retained for provenance but excluded from
                   default query results
- ``normative``  — authoritative by declaration (e.g. policy definition)
- ``predicted``  — output of a predictive model; not yet observed
- ``disputed``   — contested by at least one objection in the argument graph
- ``speculative``— low-confidence; may be revised on next compile

Status transitions:
  extracted → verified (after Label Studio review)
  extracted → disputed (when an objection is written)
  inferred  → deprecated (when the derivation rule is removed)
  verified  → deprecated (when a newer version supersedes the fact)

riverbank's Python side:
- Defines the ``EpistemicStatus`` enum with all 9 values.
- Provides ``annotate_epistemic_status`` to write/update the annotation.
- Provides ``get_epistemic_status`` to read the current annotation.
- Provides ``transition_status`` to enforce valid state transitions.
"""

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The 9 epistemic status values
# ---------------------------------------------------------------------------

class EpistemicStatus(str, Enum):
    """All 9 pgc:epistemicStatus annotation values."""

    OBSERVED = "observed"
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"
    NORMATIVE = "normative"
    PREDICTED = "predicted"
    DISPUTED = "disputed"
    SPECULATIVE = "speculative"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[EpistemicStatus, set[EpistemicStatus]] = {
    EpistemicStatus.OBSERVED:    {EpistemicStatus.VERIFIED, EpistemicStatus.DEPRECATED},
    EpistemicStatus.EXTRACTED:   {EpistemicStatus.VERIFIED, EpistemicStatus.DISPUTED,
                                  EpistemicStatus.DEPRECATED, EpistemicStatus.SPECULATIVE},
    EpistemicStatus.INFERRED:    {EpistemicStatus.VERIFIED, EpistemicStatus.DEPRECATED,
                                  EpistemicStatus.DISPUTED},
    EpistemicStatus.VERIFIED:    {EpistemicStatus.DEPRECATED, EpistemicStatus.DISPUTED},
    EpistemicStatus.DEPRECATED:  set(),  # terminal
    EpistemicStatus.NORMATIVE:   {EpistemicStatus.DEPRECATED},
    EpistemicStatus.PREDICTED:   {EpistemicStatus.OBSERVED, EpistemicStatus.DEPRECATED,
                                  EpistemicStatus.DISPUTED},
    EpistemicStatus.DISPUTED:    {EpistemicStatus.VERIFIED, EpistemicStatus.DEPRECATED},
    EpistemicStatus.SPECULATIVE: {EpistemicStatus.EXTRACTED, EpistemicStatus.DEPRECATED,
                                  EpistemicStatus.DISPUTED},
}


def is_valid_transition(
    from_status: EpistemicStatus,
    to_status: EpistemicStatus,
) -> bool:
    """Return True if the transition from_status → to_status is valid."""
    allowed = _VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed


# ---------------------------------------------------------------------------
# pgc: vocabulary IRIs
# ---------------------------------------------------------------------------

_PGC_EPISTEMIC_STATUS = "http://schema.pgc.example/epistemicStatus"
_PGC_EPISTEMIC_STATUS_ANNOTATION = "http://schema.pgc.example/EpistemicStatusAnnotation"
_PGC_ABOUT_SUBJECT = "http://schema.pgc.example/aboutSubject"
_PGC_ABOUT_PREDICATE = "http://schema.pgc.example/aboutPredicate"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

def annotate_epistemic_status(
    conn: Any,
    subject: str,
    predicate: str,
    status: EpistemicStatus,
    named_graph: str = "http://riverbank.example/graph/trusted",
    source_iri: str = "",
) -> bool:
    """Write a ``pgc:epistemicStatus`` annotation for a subject–predicate pair.

    Uses reification: creates a deterministic annotation IRI keyed on the
    (subject, predicate) pair and writes the status value as a triple.

    Falls back gracefully when pg_ripple is unavailable.
    """
    import json as _json  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    annotation_iri = (
        "http://riverbank.example/epistemic/"
        + hashlib.sha256(f"{subject}|{predicate}".encode()).hexdigest()[:16]
    )

    triples: list[dict] = [
        {
            "subject": annotation_iri,
            "predicate": _RDF_TYPE,
            "object": _PGC_EPISTEMIC_STATUS_ANNOTATION,
            "confidence": 1.0,
            "named_graph": named_graph,
            "prov_fragment_iri": source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": annotation_iri,
            "predicate": _PGC_ABOUT_SUBJECT,
            "object": subject,
            "confidence": 1.0,
            "named_graph": named_graph,
            "prov_fragment_iri": source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": annotation_iri,
            "predicate": _PGC_ABOUT_PREDICATE,
            "object": predicate,
            "confidence": 1.0,
            "named_graph": named_graph,
            "prov_fragment_iri": source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": annotation_iri,
            "predicate": _PGC_EPISTEMIC_STATUS,
            "object": status.value,
            "confidence": 1.0,
            "named_graph": named_graph,
            "prov_fragment_iri": source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
    ]

    try:
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)",
            (_json.dumps(triples), named_graph),
        )
        logger.debug(
            "annotate_epistemic_status: %s → %s [%s]", subject, predicate, status.value
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.warning(
                "pg_ripple not available — epistemic annotation not written. error=%s",
                exc,
            )
            return False
        raise


def get_epistemic_status(
    conn: Any,
    subject: str,
    predicate: str,
    named_graph: str = "http://riverbank.example/graph/trusted",
) -> EpistemicStatus | None:
    """Return the current epistemic status for a subject–predicate pair.

    Returns ``None`` when no annotation exists or pg_ripple is unavailable.
    """
    import hashlib  # noqa: PLC0415

    annotation_iri = (
        "http://riverbank.example/epistemic/"
        + hashlib.sha256(f"{subject}|{predicate}".encode()).hexdigest()[:16]
    )

    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    
    sparql = f"""\
SELECT ?status WHERE {{
  GRAPH <{named_graph}> {{
    <{annotation_iri}> <{_PGC_EPISTEMIC_STATUS}> ?status .
  }}
}}
"""
    try:
        rows = sparql_query(conn, sparql, named_graph=named_graph)
        if not rows:
            return None
        row = rows[0]
        val = next(iter(row.values())) if isinstance(row, dict) else row.get("status")
        if val is None:
            return None
        try:
            return EpistemicStatus(str(val))
        except ValueError:
            return None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.debug("get_epistemic_status: pg_ripple not available: %s", exc)
        else:
            logger.debug("get_epistemic_status failed: %s", exc)
        return None


def transition_status(
    conn: Any,
    subject: str,
    predicate: str,
    to_status: EpistemicStatus,
    named_graph: str = "http://riverbank.example/graph/trusted",
    source_iri: str = "",
) -> tuple[bool, str]:
    """Transition the epistemic status of a fact to a new state.

    Reads the current status, validates the transition, and writes the new
    annotation.

    Returns:
        (True, "") on success; (False, reason) when the transition is invalid
        or the write fails.
    """
    current = get_epistemic_status(conn, subject, predicate, named_graph)

    if current is not None and not is_valid_transition(current, to_status):
        reason = f"invalid transition {current.value} → {to_status.value}"
        logger.warning("transition_status: %s for %s %s", reason, subject, predicate)
        return False, reason

    ok = annotate_epistemic_status(
        conn, subject, predicate, to_status, named_graph=named_graph, source_iri=source_iri
    )
    return ok, "" if ok else "write failed"
