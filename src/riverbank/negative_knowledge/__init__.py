from __future__ import annotations

"""Negative knowledge records for explicit denials and absences (v0.8.0).

Records ``pgc:NegativeKnowledge`` triples for:
- Explicit denials: "X does NOT have property P"
- Exhaustive search failures: "We searched and found nothing for predicate P"
- Superseded facts: "Fact F was true but is now replaced by F'"

Compiler profiles can declare ``absence_rules`` per predicate.  When an
extraction pass finds no evidence for a declared predicate, a negative
knowledge record is written to the ``<trusted>`` named graph rather than
simply emitting nothing — making the absence explicit and queryable.

The ``pgc:NegativeKnowledge`` vocabulary class and its properties are defined
in the ``pgc:`` ontology that ships with pg_ripple.  riverbank's contribution
is the Python-side logic that decides *when* to write a negative record and
*what* evidence to attach.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Negative knowledge kind enum
# ---------------------------------------------------------------------------

class NegativeKnowledgeKind(str, Enum):
    """Controlled vocabulary for the kind of negative knowledge being recorded."""

    EXPLICIT_DENIAL = "explicit_denial"
    """The source text explicitly states that a relationship does not hold."""

    EXHAUSTIVE_SEARCH = "exhaustive_search"
    """A thorough search of the source found no evidence for the predicate."""

    SUPERSEDED = "superseded"
    """A fact that was previously true has been replaced by a newer fact."""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class NegativeKnowledgeRecord:
    """A single negative knowledge record.

    Attributes:
        subject:       IRI of the entity about which the absence is recorded.
        predicate:     IRI of the predicate for which no value was found.
        kind:          One of the three ``NegativeKnowledgeKind`` values.
        source_iri:    IRI of the source fragment that triggered this record.
        search_summary: Human-readable note on what was searched / why absent.
        superseded_by: IRI of the fact that supersedes this one (kind=SUPERSEDED
                        only).
        named_graph:   Target named graph IRI; defaults to the trusted graph.
    """

    subject: str
    predicate: str
    kind: NegativeKnowledgeKind
    source_iri: str = ""
    search_summary: str = ""
    superseded_by: str = ""
    named_graph: str = "http://riverbank.example/graph/trusted"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

_PGC_NEGATIVE_KNOWLEDGE = "http://schema.pgc.example/NegativeKnowledge"
_PGC_NK_KIND = "http://schema.pgc.example/negativeKnowledgeKind"
_PGC_NK_SEARCH_SUMMARY = "http://schema.pgc.example/searchSummary"
_PGC_NK_SUPERSEDED_BY = "http://schema.pgc.example/supersededBy"
_PROV_WAS_DERIVED_FROM = "http://www.w3.org/ns/prov#wasDerivedFrom"


def write_negative_knowledge(
    conn: Any,
    record: NegativeKnowledgeRecord,
) -> bool:
    """Write a ``pgc:NegativeKnowledge`` record to the graph via pg_ripple.

    Writes four triples per record:
    1. ``<subject> rdf:type pgc:NegativeKnowledge``
    2. ``<subject> pgc:negativeKnowledgeKind "<kind>"``
    3. ``<subject> pgc:searchSummary "<summary>"`` (when non-empty)
    4. ``<subject> prov:wasDerivedFrom <source_iri>`` (when non-empty)

    Falls back gracefully (logs a warning, returns ``False``) when pg_ripple
    is not available.
    """
    import json as _json  # noqa: PLC0415

    # Build a synthetic IRI for the negative knowledge node
    import hashlib  # noqa: PLC0415

    nk_id = hashlib.sha256(
        f"{record.subject}|{record.predicate}|{record.kind.value}".encode()
    ).hexdigest()[:16]
    nk_iri = f"http://riverbank.example/nk/{nk_id}"

    triples: list[dict] = [
        {
            "subject": nk_iri,
            "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "object": _PGC_NEGATIVE_KNOWLEDGE,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": nk_iri,
            "predicate": "http://schema.pgc.example/aboutSubject",
            "object": record.subject,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": nk_iri,
            "predicate": "http://schema.pgc.example/absentPredicate",
            "object": record.predicate,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
        {
            "subject": nk_iri,
            "predicate": _PGC_NK_KIND,
            "object": record.kind.value,
            "confidence": 1.0,
            "named_graph": record.named_graph,
            "prov_fragment_iri": record.source_iri,
            "prov_char_start": 0,
            "prov_char_end": 0,
            "prov_excerpt": "",
        },
    ]

    if record.search_summary:
        triples.append(
            {
                "subject": nk_iri,
                "predicate": _PGC_NK_SEARCH_SUMMARY,
                "object": record.search_summary,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": 0,
                "prov_char_end": 0,
                "prov_excerpt": "",
            }
        )

    if record.superseded_by:
        triples.append(
            {
                "subject": nk_iri,
                "predicate": _PGC_NK_SUPERSEDED_BY,
                "object": record.superseded_by,
                "confidence": 1.0,
                "named_graph": record.named_graph,
                "prov_fragment_iri": record.source_iri,
                "prov_char_start": 0,
                "prov_char_end": 0,
                "prov_excerpt": "",
            }
        )

    if record.source_iri:
        triples.append(
            {
                "subject": nk_iri,
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
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)",
            (_json.dumps(triples), record.named_graph),
        )
        logger.debug(
            "write_negative_knowledge: wrote %d triples for nk_iri=%s",
            len(triples),
            nk_iri,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "undefined function", "unknown function")
        ):
            logger.warning(
                "pg_ripple not available — negative knowledge record not written. error=%s",
                exc,
            )
            return False
        raise


def evaluate_absence_rules(
    extraction_results: list[dict],
    absence_rules: list[dict],
    subject: str,
    source_iri: str = "",
) -> list[NegativeKnowledgeRecord]:
    """Evaluate ``absence_rules`` from a compiler profile against extraction results.

    For each rule specifying a required predicate, if no triple with that
    predicate appears in *extraction_results*, returns a
    ``NegativeKnowledgeRecord`` with kind ``EXHAUSTIVE_SEARCH``.

    Args:
        extraction_results: List of extracted triple dicts with a ``predicate``
                            key.
        absence_rules:      List of rule dicts from the profile, each with a
                            ``predicate`` key and an optional ``summary`` key.
        subject:            The subject IRI being checked.
        source_iri:         The source fragment IRI for provenance.

    Returns:
        A (possibly empty) list of ``NegativeKnowledgeRecord`` objects.
    """
    extracted_predicates = {str(t.get("predicate", "")) for t in extraction_results}
    records: list[NegativeKnowledgeRecord] = []

    for rule in absence_rules:
        predicate = str(rule.get("predicate", ""))
        if not predicate:
            continue
        if predicate not in extracted_predicates:
            records.append(
                NegativeKnowledgeRecord(
                    subject=subject,
                    predicate=predicate,
                    kind=NegativeKnowledgeKind.EXHAUSTIVE_SEARCH,
                    source_iri=source_iri,
                    search_summary=str(rule.get("summary", f"No evidence for {predicate} found in source.")),
                )
            )

    return records
