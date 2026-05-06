"""Unit tests for the assumption registry (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_assumption_record_fields() -> None:
    """AssumptionRecord stores all required fields."""
    from riverbank.assumptions import AssumptionRecord

    rec = AssumptionRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        object_value="http://example.org/person/Alice",
        assumption_text="Assumes Alice held the CEO role at time of writing.",
        confidence=0.85,
        source_iri="file:///data/intro.md#intro",
    )

    assert rec.subject == "http://example.org/entity/Acme"
    assert rec.predicate == "http://example.org/ns/hasCEO"
    assert rec.object_value == "http://example.org/person/Alice"
    assert "CEO" in rec.assumption_text
    assert rec.confidence == 0.85
    assert rec.source_iri == "file:///data/intro.md#intro"


def test_assumption_record_default_confidence() -> None:
    """AssumptionRecord defaults confidence to 1.0."""
    from riverbank.assumptions import AssumptionRecord

    rec = AssumptionRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        object_value="http://example.org/person/Alice",
        assumption_text="Default confidence assumption.",
    )
    assert rec.confidence == 1.0


def test_write_assumption_calls_pg_ripple() -> None:
    """write_assumption calls pg_ripple.load_triples_with_confidence."""
    from riverbank.assumptions import AssumptionRecord, write_assumption

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    rec = AssumptionRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        object_value="http://example.org/person/Alice",
        assumption_text="Alice was CEO at the time.",
        confidence=0.9,
    )

    result = write_assumption(conn, rec)

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "load_triples_with_confidence" in sql


def test_write_assumption_includes_all_fields() -> None:
    """write_assumption writes type, aboutSubject, aboutPredicate, assumptionText triples."""
    import json

    from riverbank.assumptions import (
        AssumptionRecord,
        _PGC_ASSUMPTION,
        _PGC_ABOUT_SUBJECT,
        _PGC_ABOUT_PREDICATE,
        _PGC_ASSUMPTION_TEXT,
        write_assumption,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    rec = AssumptionRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        object_value="http://example.org/person/Alice",
        assumption_text="Alice was CEO at the time.",
    )

    write_assumption(conn, rec)

    params = conn.execute.call_args[0][1]
    triples = json.loads(params[0])
    types = {t["predicate"]: t["object"] for t in triples}

    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    assert types.get(rdf_type) == _PGC_ASSUMPTION
    subjects = [t["object"] for t in triples if t["predicate"] == _PGC_ABOUT_SUBJECT]
    assert subjects == ["http://example.org/entity/Acme"]
    predicates = [t["object"] for t in triples if t["predicate"] == _PGC_ABOUT_PREDICATE]
    assert predicates == ["http://example.org/ns/hasCEO"]
    texts = [t["object"] for t in triples if t["predicate"] == _PGC_ASSUMPTION_TEXT]
    assert texts == ["Alice was CEO at the time."]


def test_write_assumption_returns_false_on_pg_ripple_missing() -> None:
    """write_assumption returns False when pg_ripple is unavailable."""
    from riverbank.assumptions import AssumptionRecord, write_assumption

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    rec = AssumptionRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        object_value="http://example.org/person/Alice",
        assumption_text="Assumption text.",
    )

    result = write_assumption(conn, rec)
    assert result is False


def test_write_assumption_deterministic_iri() -> None:
    """The same (subject, predicate, object, text) produces the same assumption IRI."""
    from riverbank.assumptions import AssumptionRecord, write_assumption

    conn1 = mock.MagicMock()
    conn1.execute.return_value = mock.MagicMock()
    conn2 = mock.MagicMock()
    conn2.execute.return_value = mock.MagicMock()

    rec = AssumptionRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        object_value="http://example.org/person/Alice",
        assumption_text="Deterministic IRI test.",
    )

    write_assumption(conn1, rec)
    write_assumption(conn2, rec)

    import json

    triples1 = json.loads(conn1.execute.call_args[0][1][0])
    triples2 = json.loads(conn2.execute.call_args[0][1][0])

    # Subject IRI of the first triple (the assumption node) should be identical
    assert triples1[0]["subject"] == triples2[0]["subject"]


def test_get_assumptions_for_fact_returns_empty_without_pg_ripple() -> None:
    """get_assumptions_for_fact returns [] when pg_ripple is unavailable."""
    from riverbank.assumptions import get_assumptions_for_fact

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = get_assumptions_for_fact(
        conn,
        "http://example.org/entity/Acme",
        "http://example.org/ns/hasCEO",
        "http://example.org/person/Alice",
    )

    assert result == []


def test_get_assumptions_for_fact_returns_texts() -> None:
    """get_assumptions_for_fact returns assumption texts from pg_ripple rows."""
    from riverbank.assumptions import get_assumptions_for_fact

    conn = mock.MagicMock()
    row = mock.MagicMock()
    row._mapping = {"assumption_text": "Alice was CEO at time of writing."}
    conn.execute.return_value.fetchall.return_value = [row]

    result = get_assumptions_for_fact(
        conn,
        "http://example.org/entity/Acme",
        "http://example.org/ns/hasCEO",
        "http://example.org/person/Alice",
    )

    assert len(result) == 1
    assert result[0] == "Alice was CEO at time of writing."
