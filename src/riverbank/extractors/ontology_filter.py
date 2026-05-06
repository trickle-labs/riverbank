"""Ontology-grounded pre-write structural filtering and literal normalization (v0.12.0).

The ``OntologyFilter`` is applied immediately before any triple enters either
the trusted or tentative graph.  It performs two jobs:

1. **Structural filtering** — rejects triples whose predicate is not in the
   ``allowed_predicates`` allowlist (when the allowlist is non-empty).  This is
   a zero-cost, zero-latency gate: no graph queries, no LLM calls.

2. **Literal normalization** — normalises string literals (lowercase + strip),
   dates to ISO 8601 canonical form, and IRIs before comparison/dedup.  The
   highest-confidence instance of normalised duplicates is kept.

Usage::

    from riverbank.extractors.ontology_filter import OntologyFilter
    filt = OntologyFilter(allowed_predicates=["ex:hasName", "ex:relatedTo"])
    kept, rejected_count = filt.filter(triples)
    normalised = filt.normalize_triples(kept)
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Sequence

logger = logging.getLogger(__name__)

# ISO date/datetime patterns used for normalisation
_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}$"  # already ISO
    r"|^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$"  # MM/DD/YYYY or DD-MM-YYYY
)
_FULL_IRI_RE = re.compile(r"^<(.+)>$")


class OntologyFilter:
    """Pre-write structural filter and literal normaliser.

    Parameters
    ----------
    allowed_predicates:
        If non-empty, only triples whose predicate appears in this list are
        kept.  Local names are compared case-insensitively and prefix-stripped
        before matching so that ``ex:hasName``, ``hasName``, and
        ``<http://example.org/hasName>`` all match an allowlist entry of
        ``ex:hasName``.
    allowed_classes:
        Optional; reserved for domain/range checks in a future iteration.
        Currently unused.
    """

    def __init__(
        self,
        allowed_predicates: list[str] | None = None,
        allowed_classes: list[str] | None = None,
    ) -> None:
        self._raw_predicates: list[str] = list(allowed_predicates or [])
        self._allowed_classes: list[str] = list(allowed_classes or [])
        # Build a normalised lookup set for fast membership tests
        self._pred_set: frozenset[str] = frozenset(
            _normalise_predicate(p) for p in self._raw_predicates
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter(self, triples: Sequence[object]) -> tuple[list[object], int]:
        """Return ``(kept_triples, rejected_count)``.

        When ``allowed_predicates`` is empty every triple passes through.
        """
        if not self._pred_set:
            return list(triples), 0

        kept: list[object] = []
        rejected = 0
        for triple in triples:
            pred = str(getattr(triple, "predicate", ""))
            if _normalise_predicate(pred) in self._pred_set:
                kept.append(triple)
            else:
                logger.debug(
                    "OntologyFilter: rejecting triple (predicate not in allowlist): %s",
                    pred,
                )
                rejected += 1

        return kept, rejected

    def normalize_triples(self, triples: Sequence[object]) -> list[object]:
        """Return a deduplicated, normalised copy of *triples*.

        Normalisation:
        - String literals: lowercase + strip
        - Date literals: ISO 8601
        - IRIs: strip angle brackets, normalise percent-encoding

        Deduplication: when two triples share the same normalised
        ``(subject, predicate, object_value)`` key, the one with the higher
        confidence is kept.
        """
        seen: dict[tuple[str, str, str], object] = {}
        for triple in triples:
            subj = _normalise_iri(str(getattr(triple, "subject", "")))
            pred = _normalise_iri(str(getattr(triple, "predicate", "")))
            obj = _normalise_object(str(getattr(triple, "object_value", "")))
            key = (subj, pred, obj)
            existing = seen.get(key)
            if existing is None:
                seen[key] = triple
            else:
                # Keep the higher-confidence instance
                new_conf = float(getattr(triple, "confidence", 0.0))
                old_conf = float(getattr(existing, "confidence", 0.0))
                if new_conf > old_conf:
                    seen[key] = triple
        return list(seen.values())


# ---------------------------------------------------------------------------
# Module-level helpers (also exported for testing)
# ---------------------------------------------------------------------------


def _normalise_predicate(pred: str) -> str:
    """Strip IRI brackets and prefix; return lowercase local name."""
    pred = pred.strip()
    # <http://...#localName> or <http://.../localName>
    m = _FULL_IRI_RE.match(pred)
    if m:
        iri = m.group(1)
        # Return the fragment or last path segment
        if "#" in iri:
            return iri.rsplit("#", 1)[-1].lower()
        return iri.rsplit("/", 1)[-1].lower()
    # prefix:localName
    if ":" in pred:
        return pred.split(":", 1)[1].lower()
    return pred.lower()


def _normalise_iri(value: str) -> str:
    """Strip angle brackets from full IRIs; return as-is otherwise."""
    value = value.strip()
    m = _FULL_IRI_RE.match(value)
    if m:
        return m.group(1)
    return value


def _normalise_object(value: str) -> str:
    """Normalise a triple object: IRI → stripped; literal → lowercase + ISO date."""
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        return _normalise_iri(value)
    # Try ISO date normalisation
    normalised_date = _try_iso_date(value)
    if normalised_date is not None:
        return normalised_date
    # Plain string literal: lowercase + strip
    return value.lower().strip().strip('"').strip("'")


def _try_iso_date(value: str) -> str | None:
    """Attempt to parse *value* as a date and return ISO 8601 form, or None."""
    stripped = value.strip().strip('"').strip("'")
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", stripped):
        return stripped
    # Common ambiguous formats — try MM/DD/YYYY then DD/MM/YYYY
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(stripped, fmt).date().isoformat()
        except ValueError:
            pass
    return None
