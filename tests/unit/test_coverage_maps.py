"""Unit tests for coverage maps (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_coverage_map_entry_fields() -> None:
    """CoverageMapEntry stores all required fields."""
    from riverbank.coverage import CoverageMapEntry

    entry = CoverageMapEntry(
        topic_iri="http://example.org/topic/HighAvailability",
        source_density=12,
        mean_confidence=0.87,
        contradiction_count=2,
        unanswered_cq_count=1,
    )

    assert entry.topic_iri == "http://example.org/topic/HighAvailability"
    assert entry.source_density == 12
    assert entry.mean_confidence == 0.87
    assert entry.contradiction_count == 2
    assert entry.unanswered_cq_count == 1


def test_coverage_map_entry_defaults() -> None:
    """CoverageMapEntry has sensible defaults."""
    from riverbank.coverage import CoverageMapEntry

    entry = CoverageMapEntry(topic_iri="http://example.org/topic/X")
    assert entry.source_density == 0
    assert entry.mean_confidence == 0.0
    assert entry.contradiction_count == 0
    assert entry.unanswered_cq_count == 0


def test_refresh_coverage_map_calls_pg_ripple() -> None:
    """refresh_coverage_map calls pg_ripple.refresh_coverage_map."""
    from riverbank.coverage import refresh_coverage_map

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    result = refresh_coverage_map(conn)

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "refresh_coverage_map" in sql


def test_refresh_coverage_map_returns_false_when_unavailable() -> None:
    """refresh_coverage_map returns False when pg_ripple is unavailable."""
    from riverbank.coverage import refresh_coverage_map

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple.refresh_coverage_map does not exist")

    result = refresh_coverage_map(conn)
    assert result is False


def test_write_coverage_map_entry_calls_pg_ripple() -> None:
    """write_coverage_map_entry writes triples via pg_ripple."""
    from riverbank.coverage import CoverageMapEntry, write_coverage_map_entry

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    entry = CoverageMapEntry(
        topic_iri="http://example.org/topic/HighAvailability",
        source_density=5,
        mean_confidence=0.9,
    )

    result = write_coverage_map_entry(conn, entry)

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "load_triples_with_confidence" in sql


def test_write_coverage_map_entry_includes_all_metrics() -> None:
    """write_coverage_map_entry writes all 5 metric triples."""
    import json

    from riverbank.coverage import (
        CoverageMapEntry,
        _PGC_SOURCE_DENSITY,
        _PGC_MEAN_CONFIDENCE,
        _PGC_CONTRADICTION_COUNT,
        _PGC_UNANSWERED_CQ_COUNT,
        _PGC_TOPIC_IRI,
        write_coverage_map_entry,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    entry = CoverageMapEntry(
        topic_iri="http://example.org/topic/HA",
        source_density=7,
        mean_confidence=0.88,
        contradiction_count=3,
        unanswered_cq_count=2,
    )

    write_coverage_map_entry(conn, entry)

    params = conn.execute.call_args[0][1]
    triples = json.loads(params[0])
    predicates = {t["predicate"] for t in triples}

    assert _PGC_TOPIC_IRI in predicates
    assert _PGC_SOURCE_DENSITY in predicates
    assert _PGC_MEAN_CONFIDENCE in predicates
    assert _PGC_CONTRADICTION_COUNT in predicates
    assert _PGC_UNANSWERED_CQ_COUNT in predicates


def test_write_coverage_map_entry_returns_false_on_pg_ripple_missing() -> None:
    """write_coverage_map_entry returns False when pg_ripple is unavailable."""
    from riverbank.coverage import CoverageMapEntry, write_coverage_map_entry

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    entry = CoverageMapEntry(topic_iri="http://example.org/topic/X")
    result = write_coverage_map_entry(conn, entry)
    assert result is False


def test_compute_unanswered_cq_count_returns_total_when_pg_ripple_missing() -> None:
    """compute_unanswered_cq_count returns total count when pg_ripple is unavailable."""
    from riverbank.coverage import compute_unanswered_cq_count

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    cqs = [
        {"sparql": "ASK { ?s ?p ?o }"},
        {"sparql": "ASK { ?s a <http://example.org/Thing> }"},
    ]

    count = compute_unanswered_cq_count(conn, cqs)
    assert count == 2  # total count when pg_ripple is unavailable


def test_compute_unanswered_cq_count_returns_zero_for_empty_list() -> None:
    """compute_unanswered_cq_count returns 0 for empty competency questions."""
    from riverbank.coverage import compute_unanswered_cq_count

    conn = mock.MagicMock()
    count = compute_unanswered_cq_count(conn, [])
    assert count == 0


def test_compute_unanswered_cq_count_counts_false_asks() -> None:
    """compute_unanswered_cq_count counts CQs that return False from pg_ripple."""
    from riverbank.coverage import compute_unanswered_cq_count

    conn = mock.MagicMock()

    responses = [
        # First CQ: ASK returns True (answered)
        mock.MagicMock(**{"fetchall.return_value": [mock.MagicMock(_mapping={"result": True})]}),
        # Second CQ: ASK returns False (unanswered)
        mock.MagicMock(**{"fetchall.return_value": [mock.MagicMock(_mapping={"result": False})]}),
    ]
    conn.execute.side_effect = responses

    cqs = [
        {"sparql": "ASK { ?s a <http://example.org/A> }"},
        {"sparql": "ASK { ?s a <http://example.org/B> }"},
    ]

    count = compute_unanswered_cq_count(conn, cqs)
    assert count == 1


def test_coverage_map_entry_deterministic_iri() -> None:
    """The same topic IRI always produces the same coverage map IRI."""
    import json

    from riverbank.coverage import CoverageMapEntry, write_coverage_map_entry

    conn1 = mock.MagicMock()
    conn1.execute.return_value = mock.MagicMock()
    conn2 = mock.MagicMock()
    conn2.execute.return_value = mock.MagicMock()

    entry = CoverageMapEntry(topic_iri="http://example.org/topic/HA")

    write_coverage_map_entry(conn1, entry)
    write_coverage_map_entry(conn2, entry)

    triples1 = json.loads(conn1.execute.call_args[0][1][0])
    triples2 = json.loads(conn2.execute.call_args[0][1][0])

    assert triples1[0]["subject"] == triples2[0]["subject"]
