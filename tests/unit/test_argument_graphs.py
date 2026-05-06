"""Unit tests for argument graph records (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_argument_record_fields() -> None:
    """ArgumentRecord stores all required span fields."""
    from riverbank.argument_graphs import ArgumentRecord, ArgumentSpan

    claim = ArgumentSpan(text="All services must be HA.", char_start=0, char_end=23)
    ev1 = ArgumentSpan(text="Section 3 mandates HA for critical paths.", char_start=100, char_end=140)
    obj = ArgumentSpan(text="Cost is prohibitive for dev environments.", char_start=200, char_end=240)
    reb = ArgumentSpan(text="Dev VMs can be excluded via annotation.", char_start=300, char_end=338)

    rec = ArgumentRecord(
        record_iri="http://riverbank.example/arg/abc123",
        claim=claim,
        evidence=[ev1],
        objections=[obj],
        rebuttals=[reb],
        source_iri="file:///data/policy.md#ha",
    )

    assert rec.record_iri == "http://riverbank.example/arg/abc123"
    assert rec.claim.text == "All services must be HA."
    assert len(rec.evidence) == 1
    assert len(rec.objections) == 1
    assert len(rec.rebuttals) == 1


def test_write_argument_record_calls_pg_ripple() -> None:
    """write_argument_record calls pg_ripple.load_triples_with_confidence."""
    from riverbank.argument_graphs import ArgumentRecord, ArgumentSpan, write_argument_record

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    claim = ArgumentSpan(text="All services must be HA.", char_start=0, char_end=23)
    ev = ArgumentSpan(text="Section 3 mandates HA.", char_start=100, char_end=121)

    rec = ArgumentRecord(
        record_iri="http://riverbank.example/arg/test1",
        claim=claim,
        evidence=[ev],
        source_iri="file:///data/policy.md",
    )

    result = write_argument_record(conn, rec)

    assert result is True
    conn.execute.assert_called_once()
    call_sql = conn.execute.call_args[0][0]
    assert "load_triples_with_confidence" in call_sql


def test_write_argument_record_includes_all_span_types() -> None:
    """write_argument_record writes claim, evidence, objection, and rebuttal triples."""
    import json

    from riverbank.argument_graphs import (
        ArgumentRecord,
        ArgumentSpan,
        _PGC_HAS_CLAIM,
        _PGC_HAS_EVIDENCE,
        _PGC_HAS_OBJECTION,
        _PGC_HAS_REBUTTAL,
        write_argument_record,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    rec = ArgumentRecord(
        record_iri="http://riverbank.example/arg/test2",
        claim=ArgumentSpan(text="Claim text"),
        evidence=[ArgumentSpan(text="Evidence 1"), ArgumentSpan(text="Evidence 2")],
        objections=[ArgumentSpan(text="Objection text")],
        rebuttals=[ArgumentSpan(text="Rebuttal text")],
        source_iri="file:///data/policy.md",
    )

    write_argument_record(conn, rec)

    call_args = conn.execute.call_args[0]
    params = call_args[1]
    triples = json.loads(params[0])
    predicates = {t["predicate"] for t in triples}

    assert _PGC_HAS_CLAIM in predicates
    assert _PGC_HAS_EVIDENCE in predicates
    assert _PGC_HAS_OBJECTION in predicates
    assert _PGC_HAS_REBUTTAL in predicates


def test_write_argument_record_returns_false_on_pg_ripple_missing() -> None:
    """write_argument_record returns False when pg_ripple is unavailable."""
    from riverbank.argument_graphs import ArgumentRecord, ArgumentSpan, write_argument_record

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    rec = ArgumentRecord(
        record_iri="http://riverbank.example/arg/test3",
        claim=ArgumentSpan(text="Claim"),
        source_iri="file:///data/policy.md",
    )

    result = write_argument_record(conn, rec)
    assert result is False


def test_query_unanswered_objections_returns_empty_without_pg_ripple() -> None:
    """query_unanswered_objections returns [] when pg_ripple is unavailable."""
    from riverbank.argument_graphs import query_unanswered_objections

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = query_unanswered_objections(conn)
    assert result == []


def test_query_unanswered_objections_returns_rows() -> None:
    """query_unanswered_objections returns parsed rows when pg_ripple responds."""
    from riverbank.argument_graphs import query_unanswered_objections

    conn = mock.MagicMock()
    row = mock.MagicMock()
    row._mapping = {
        "record": "http://riverbank.example/arg/abc",
        "claim_text": "All services must be HA.",
        "objection_text": "Too expensive.",
    }
    conn.execute.return_value.fetchall.return_value = [row]

    result = query_unanswered_objections(conn)
    assert len(result) == 1
    assert result[0]["claim_text"] == "All services must be HA."


def test_argument_record_default_named_graph() -> None:
    """ArgumentRecord defaults to the trusted named graph."""
    from riverbank.argument_graphs import ArgumentRecord, ArgumentSpan

    rec = ArgumentRecord(
        record_iri="http://riverbank.example/arg/test",
        claim=ArgumentSpan(text="Claim"),
    )
    assert rec.named_graph == "http://riverbank.example/graph/trusted"


def test_argument_span_defaults() -> None:
    """ArgumentSpan char offsets default to 0."""
    from riverbank.argument_graphs import ArgumentSpan

    span = ArgumentSpan(text="Hello")
    assert span.char_start == 0
    assert span.char_end == 0
    assert span.source_iri == ""
