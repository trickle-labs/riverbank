"""Confidence consolidation (noisy-OR) with source diversity scoring (v0.12.1).

When the same triple ``(s, p, o)`` is extracted from multiple fragments, this
module consolidates the per-extraction confidence values into a single final
confidence using the noisy-OR formula:

    c_final = 1 − ∏ᵢ (1 − cᵢ)

**Source diversity scoring:** Corroboration from multiple fragments of the
*same* document counts as a single "vote" rather than independent evidence.
This prevents correlated hallucinations from templated or copied documents
from crossing the trusted threshold.  Multi-provenance evidence spans are
accumulated per triple so that every source remains traceable.

Usage::

    from riverbank.postprocessors.consolidate import NoisyORConsolidator

    consolidator = NoisyORConsolidator(trusted_threshold=0.75)
    results = consolidator.consolidate(triples_with_fragments)
    promoted, remaining = consolidator.split_by_threshold(results)

Data flow (called from ``riverbank promote-tentative``)::

    1. Query the tentative graph for all triples
    2. Group by normalised (subject, predicate, object_value) key
    3. Compute noisy-OR confidence with source-diversity weighting
    4. Return ConsolidatedTriple list sorted by final confidence descending
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# Triple key: (subject, predicate, object_value) — normalised to lowercase
TripleKey = tuple[str, str, str]


@dataclass
class ProvenanceRecord:
    """One extraction event contributing to a consolidated triple."""

    source_iri: str          # document IRI
    fragment_key: str        # heading-path fragment key
    confidence: float        # per-extraction confidence
    excerpt: str = ""        # verbatim evidence excerpt


@dataclass
class ConsolidatedTriple:
    """A triple whose confidence has been consolidated across multiple extractions.

    Attributes
    ----------
    subject, predicate, object_value:
        The canonical triple components (as extracted — not normalised).
    final_confidence:
        Noisy-OR confidence after source-diversity weighting.
    raw_confidences:
        List of per-extraction confidence values before consolidation.
    provenance:
        List of :class:`ProvenanceRecord` for every contributing extraction.
    source_diversity:
        Number of *distinct* source documents that produced this triple.
        Fragments within the same document are de-duplicated before
        applying noisy-OR (one vote per document).
    """

    subject: str
    predicate: str
    object_value: str
    final_confidence: float
    raw_confidences: list[float] = field(default_factory=list)
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    source_diversity: int = 1


class NoisyORConsolidator:
    """Consolidate per-fragment confidence values using noisy-OR.

    Parameters
    ----------
    trusted_threshold:
        Confidence at or above which a consolidated triple is considered
        trusted.  Default 0.75 matches the per-triple routing threshold from
        v0.12.0.
    """

    def __init__(self, trusted_threshold: float = 0.75) -> None:
        self.trusted_threshold = trusted_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consolidate(
        self,
        triples: Sequence[Any],
    ) -> list[ConsolidatedTriple]:
        """Consolidate a flat list of (possibly duplicate) extracted triples.

        Each element of *triples* must expose the attributes:
        ``subject``, ``predicate``, ``object_value``, ``confidence``,
        ``evidence`` (with ``.source_iri``, ``.excerpt``), and optionally
        ``fragment_key``.

        Returns a deduplicated list of :class:`ConsolidatedTriple` sorted by
        ``final_confidence`` descending.
        """
        # Group raw extractions by normalised triple key
        groups: dict[TripleKey, list[Any]] = {}
        for t in triples:
            key = _normalise_key(t)
            groups.setdefault(key, []).append(t)

        results: list[ConsolidatedTriple] = []
        for key, group in groups.items():
            subj, pred, obj = key
            # Pick canonical (non-normalised) values from the highest-confidence instance
            best = max(group, key=lambda t: float(getattr(t, "confidence", 0.0)))
            canon_subj = getattr(best, "subject", subj)
            canon_pred = getattr(best, "predicate", pred)
            canon_obj = getattr(best, "object_value", obj)

            prov_records, raw_confs, source_diversity = _build_provenance(group)
            final_conf = _noisy_or_with_diversity(group)

            results.append(
                ConsolidatedTriple(
                    subject=canon_subj,
                    predicate=canon_pred,
                    object_value=canon_obj,
                    final_confidence=round(final_conf, 6),
                    raw_confidences=raw_confs,
                    provenance=prov_records,
                    source_diversity=source_diversity,
                )
            )

        results.sort(key=lambda ct: ct.final_confidence, reverse=True)
        return results

    def split_by_threshold(
        self,
        consolidated: Sequence[ConsolidatedTriple],
    ) -> tuple[list[ConsolidatedTriple], list[ConsolidatedTriple]]:
        """Split consolidated triples into (above_threshold, below_threshold).

        Returns ``(trusted_candidates, remaining)`` where ``trusted_candidates``
        are those whose ``final_confidence >= trusted_threshold``.
        """
        trusted: list[ConsolidatedTriple] = []
        remaining: list[ConsolidatedTriple] = []
        for ct in consolidated:
            if ct.final_confidence >= self.trusted_threshold:
                trusted.append(ct)
            else:
                remaining.append(ct)
        return trusted, remaining


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalise_key(triple: Any) -> TripleKey:
    """Return a lowercase, stripped normalisation of the triple components."""
    def _norm(v: str) -> str:
        return v.strip().lower()

    return (
        _norm(str(getattr(triple, "subject", ""))),
        _norm(str(getattr(triple, "predicate", ""))),
        _norm(str(getattr(triple, "object_value", ""))),
    )


def _build_provenance(
    group: list[Any],
) -> tuple[list[ProvenanceRecord], list[float], int]:
    """Build provenance records and return ``(provenance, raw_confidences, source_diversity)``."""
    records: list[ProvenanceRecord] = []
    raw_confs: list[float] = []
    sources_seen: set[str] = set()

    for t in group:
        ev = getattr(t, "evidence", None)
        source_iri = str(getattr(ev, "source_iri", "")) if ev else ""
        fragment_key = str(getattr(t, "fragment_key", ""))
        excerpt = str(getattr(ev, "excerpt", "")) if ev else ""
        conf = float(getattr(t, "confidence", 0.0))

        records.append(ProvenanceRecord(
            source_iri=source_iri,
            fragment_key=fragment_key,
            confidence=conf,
            excerpt=excerpt,
        ))
        raw_confs.append(conf)
        sources_seen.add(source_iri)

    return records, raw_confs, len(sources_seen)


def _noisy_or_with_diversity(group: list[Any]) -> float:
    """Compute noisy-OR confidence with source diversity de-duplication.

    Corroboration from multiple fragments of the *same document* counts as one
    vote.  For each unique source_iri, take the maximum confidence across all
    fragments from that source.  Then apply noisy-OR across the per-source
    max confidences.

    Formula::

        # source_max_confs = [max(c for c in source_group)]
        c_final = 1 − ∏_sources (1 − c_source_max)

    This prevents a single document with many fragments from inflating
    confidence beyond what independent corroboration would warrant.
    """
    # Collect max confidence per unique source IRI
    source_max: dict[str, float] = {}
    for t in group:
        ev = getattr(t, "evidence", None)
        source_iri = str(getattr(ev, "source_iri", "__unknown__")) if ev else "__unknown__"
        conf = float(getattr(t, "confidence", 0.0))
        current = source_max.get(source_iri, 0.0)
        if conf > current:
            source_max[source_iri] = conf

    # Noisy-OR across per-source max confidences
    product = 1.0
    for c in source_max.values():
        product *= max(0.0, 1.0 - c)

    return min(1.0, max(0.0, 1.0 - product))
