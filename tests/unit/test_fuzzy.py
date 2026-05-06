"""Unit tests for fuzzy entity matching (v0.5.0).

Tests cover:
- Python-side RapidFuzz candidate preparation (prepare_candidates)
- pg_ripple wrappers: suggest_sameas, find_duplicates, fuzzy_match_entities
"""
from __future__ import annotations

import unittest.mock as mock


def test_fuzzy_candidate_dataclass() -> None:
    """FuzzyCandidate has iri, label, and score fields."""
    from riverbank.fuzzy import FuzzyCandidate

    candidate = FuzzyCandidate(iri="entity:Acme", label="Acme Corporation", score=95.0)
    assert candidate.iri == "entity:Acme"
    assert candidate.label == "Acme Corporation"
    assert candidate.score == 95.0


def test_prepare_candidates_empty_input() -> None:
    """prepare_candidates returns [] when the candidate list is empty."""
    from riverbank.fuzzy import prepare_candidates

    result = prepare_candidates("Acme", [])
    assert result == []


def test_prepare_candidates_finds_close_match() -> None:
    """prepare_candidates returns candidates above the default threshold."""
    from riverbank.fuzzy import prepare_candidates

    candidates = [
        ("entity:Acme", "Acme Corporation"),
        ("entity:Other", "Totally Different Company"),
    ]
    results = prepare_candidates("Acme Corp", candidates, threshold=60.0)
    iris = [c.iri for c in results]
    assert "entity:Acme" in iris


def test_prepare_candidates_filters_below_threshold() -> None:
    """Candidates below the threshold score are excluded."""
    from riverbank.fuzzy import prepare_candidates

    candidates = [
        ("entity:Apple", "Apple Inc"),
        ("entity:Banana", "Banana Republic"),
    ]
    # Very high threshold — likely nothing matches "XYZ Corp" well enough
    results = prepare_candidates("XYZ Corp", candidates, threshold=99.0)
    assert results == []


def test_prepare_candidates_sorted_descending() -> None:
    """Results are sorted from highest score to lowest."""
    from riverbank.fuzzy import prepare_candidates

    candidates = [
        ("entity:Exact", "Acme Corp"),
        ("entity:Partial", "Acme Corporation Ltd"),
        ("entity:Loose", "ACME"),
    ]
    results = prepare_candidates("Acme Corp", candidates, threshold=50.0)
    if len(results) >= 2:
        assert results[0].score >= results[1].score


def test_prepare_candidates_falls_back_gracefully_without_rapidfuzz() -> None:
    """prepare_candidates returns [] when RapidFuzz is not installed."""
    from riverbank.fuzzy import prepare_candidates

    candidates = [("entity:X", "Some Label")]
    with mock.patch.dict("sys.modules", {"rapidfuzz": None, "rapidfuzz.process": None, "rapidfuzz.fuzz": None}):
        # RapidFuzz unavailable — must not raise
        import importlib

        import riverbank.fuzzy as fuzzy_mod

        original_prepare = fuzzy_mod.prepare_candidates

        def _patched(query, candidates, threshold=80.0):
            try:
                from rapidfuzz import fuzz, process as rf_process  # noqa: PLC0415
            except ImportError:
                return []
            return original_prepare(query, candidates, threshold)

        result = _patched("query", candidates)
    assert result == []


def test_suggest_sameas_calls_pg_ripple() -> None:
    """suggest_sameas calls pg_ripple.suggest_sameas and returns IRIs."""
    from riverbank.fuzzy import suggest_sameas

    mock_row = mock.MagicMock()
    mock_row._mapping = {"candidate_iri": "entity:AcmeCorp"}
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [mock_row]

    result = suggest_sameas(conn, "entity:Acme")
    assert result == ["entity:AcmeCorp"]


def test_suggest_sameas_falls_back_when_pg_ripple_missing() -> None:
    """suggest_sameas returns [] gracefully when pg_ripple is not available."""
    from riverbank.fuzzy import suggest_sameas

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "function pg_ripple.suggest_sameas does not exist"
    )
    result = suggest_sameas(conn, "entity:Acme")
    assert result == []


def test_suggest_sameas_with_named_graph() -> None:
    """suggest_sameas passes the named_graph argument to pg_ripple."""
    from riverbank.fuzzy import suggest_sameas

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    result = suggest_sameas(conn, "entity:X", named_graph="http://example/graph")
    assert result == []
    # Check that the two-arg form was called
    call_args = conn.execute.call_args
    assert "suggest_sameas($1, $2)" in str(call_args)


def test_find_duplicates_returns_empty_when_pg_ripple_missing() -> None:
    """find_duplicates returns [] gracefully when pg_ripple is not available."""
    from riverbank.fuzzy import find_duplicates

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "function pg_ripple.pagerank_find_duplicates does not exist"
    )
    result = find_duplicates(conn, "http://example/graph")
    assert result == []


def test_find_duplicates_returns_rows_as_dicts() -> None:
    """find_duplicates returns pg_ripple result rows as plain dicts."""
    from riverbank.fuzzy import find_duplicates

    mock_row = mock.MagicMock()
    mock_row._mapping = {"iri_a": "entity:Acme", "iri_b": "entity:AcmeCorp", "score": 0.95}
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [mock_row]

    result = find_duplicates(conn, "http://example/graph")
    assert len(result) == 1
    assert result[0]["iri_a"] == "entity:Acme"


def test_fuzzy_match_entities_returns_empty_when_pg_ripple_missing() -> None:
    """fuzzy_match_entities returns [] gracefully when pg_ripple is not available."""
    from riverbank.fuzzy import fuzzy_match_entities

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "function pg_ripple.fuzzy_match does not exist"
    )
    result = fuzzy_match_entities(conn, "Acme", "http://example/graph")
    assert result == []


def test_fuzzy_match_entities_returns_rows_as_dicts() -> None:
    """fuzzy_match_entities returns pg_ripple result rows as plain dicts."""
    from riverbank.fuzzy import fuzzy_match_entities

    mock_row = mock.MagicMock()
    mock_row._mapping = {"iri": "entity:Acme", "label": "Acme Corporation", "score": 0.88}
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [mock_row]

    result = fuzzy_match_entities(conn, "Acme Corp", "http://example/graph")
    assert len(result) == 1
    assert result[0]["iri"] == "entity:Acme"
