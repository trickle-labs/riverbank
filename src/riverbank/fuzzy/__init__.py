"""Fuzzy entity matching — Python-side candidate preparation (v0.5.0).

Provides:
* :func:`prepare_candidates` — RapidFuzz-based pre-LLM candidate ranking.
* :func:`suggest_sameas` — pg_ripple ``suggest_sameas()`` wrapper.
* :func:`find_duplicates` — pg_ripple ``pagerank_find_duplicates()`` wrapper.
* :func:`fuzzy_match_entities` — pg_ripple ``pg:fuzzy_match()`` wrapper.

All pg_ripple wrappers fall back gracefully to empty results when pg_ripple
is not available in the connected database.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FuzzyCandidate:
    """A fuzzy-match candidate with an entity IRI, label, and similarity score."""

    iri: str
    label: str
    score: float  # 0.0 – 100.0 (WRatio scale)


# ---------------------------------------------------------------------------
# Python-side RapidFuzz preparation
# ---------------------------------------------------------------------------


def prepare_candidates(
    query: str,
    candidates: list[tuple[str, str]],
    threshold: float = 80.0,
) -> list[FuzzyCandidate]:
    """Rank entity candidates against *query* using RapidFuzz WRatio.

    This is the pre-LLM Python-side step: before the LLM call we compute
    fuzzy similarity between the raw entity text and all known concept labels,
    filtering to those above *threshold*.  Results are sorted descending by
    score.

    Args:
        query: The raw entity text to match.
        candidates: ``[(iri, label), ...]`` pairs to score.
        threshold: Minimum WRatio score (0–100) to include.  Default ``80.0``.

    Returns:
        Sorted :class:`FuzzyCandidate` list; empty when RapidFuzz is not
        installed or no candidates meet the threshold.
    """
    if not candidates:
        return []

    try:
        from rapidfuzz import fuzz, process as rf_process  # noqa: PLC0415
    except ImportError:
        logger.debug(
            "rapidfuzz not installed — fuzzy candidate preparation skipped. "
            "Install it with: pip install 'riverbank[ingest]'"
        )
        return []

    # Build label→iri index; handle duplicate labels by keeping last.
    iri_by_label: dict[str, str] = {label: iri for iri, label in candidates}
    labels = list(iri_by_label.keys())

    matches = rf_process.extract(
        query,
        labels,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
        limit=None,
    )

    results = [
        FuzzyCandidate(iri=iri_by_label[label], label=label, score=float(score))
        for label, score, _ in matches
        if label in iri_by_label
    ]
    results.sort(key=lambda c: c.score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# pg_ripple wrappers
# ---------------------------------------------------------------------------


def suggest_sameas(
    conn: Any,
    iri: str,
    named_graph: str | None = None,
) -> list[str]:
    """Suggest ``owl:sameAs`` candidates for *iri* via pg_ripple.

    Calls ``pg_ripple.suggest_sameas(iri)`` (or the two-argument form with
    *named_graph*) and returns a list of candidate IRI strings.

    Falls back to ``[]`` when pg_ripple is not available.
    """
    try:
        if named_graph:
            rows = conn.execute(
                "SELECT * FROM pg_ripple.suggest_sameas($1, $2)",
                (iri, named_graph),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pg_ripple.suggest_sameas($1)",
                (iri,),
            ).fetchall()
        if not rows:
            return []
        result: list[str] = []
        for row in rows:
            if hasattr(row, "_mapping"):
                row_dict = dict(row._mapping)
                result.append(str(next(iter(row_dict.values()))))
            else:
                result.append(str(row[0]))
        return result
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(kw in msg for kw in ("does not exist", "not found", "undefined function")):
            logger.debug(
                "suggest_sameas: pg_ripple.suggest_sameas not available: %s", exc
            )
        else:
            logger.debug("suggest_sameas failed: %s", exc)
        return []


def find_duplicates(
    conn: Any,
    named_graph: str,
) -> list[dict]:
    """Find duplicate entity candidates via pg_ripple PageRank dedup.

    Calls ``pg_ripple.pagerank_find_duplicates(named_graph)`` and returns
    a list of dicts with candidate duplicate pairs.

    Falls back to ``[]`` when pg_ripple is not available.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.pagerank_find_duplicates($1)",
            (named_graph,),
        ).fetchall()
        if not rows:
            return []
        return [
            dict(row._mapping) if hasattr(row, "_mapping") else dict(enumerate(row))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(kw in msg for kw in ("does not exist", "not found", "undefined function")):
            logger.debug(
                "find_duplicates: pg_ripple.pagerank_find_duplicates not available: %s",
                exc,
            )
        else:
            logger.debug("find_duplicates failed: %s", exc)
        return []


def fuzzy_match_entities(
    conn: Any,
    query: str,
    named_graph: str,
) -> list[dict]:
    """Match *query* against entity labels in *named_graph* via pg_ripple GIN index.

    Calls ``pg_ripple.fuzzy_match(query, named_graph)`` (which uses the
    trigram GIN index for sub-millisecond lookup) and returns a list of
    match dicts.

    Falls back to ``[]`` when pg_ripple is not available.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.fuzzy_match($1, $2)",
            (query, named_graph),
        ).fetchall()
        if not rows:
            return []
        return [
            dict(row._mapping) if hasattr(row, "_mapping") else dict(enumerate(row))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(kw in msg for kw in ("does not exist", "not found", "undefined function")):
            logger.debug(
                "fuzzy_match_entities: pg_ripple.fuzzy_match not available: %s", exc
            )
        else:
            logger.debug("fuzzy_match_entities failed: %s", exc)
        return []
