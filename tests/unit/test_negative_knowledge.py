"""Unit tests for negative knowledge records (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_negative_knowledge_kind_has_three_values() -> None:
    """NegativeKnowledgeKind enum has exactly 3 values."""
    from riverbank.negative_knowledge import NegativeKnowledgeKind

    assert len(list(NegativeKnowledgeKind)) == 3
    assert NegativeKnowledgeKind.EXPLICIT_DENIAL.value == "explicit_denial"
    assert NegativeKnowledgeKind.EXHAUSTIVE_SEARCH.value == "exhaustive_search"
    assert NegativeKnowledgeKind.SUPERSEDED.value == "superseded"


def test_negative_knowledge_record_fields() -> None:
    """NegativeKnowledgeRecord stores all required fields."""
    from riverbank.negative_knowledge import NegativeKnowledgeKind, NegativeKnowledgeRecord

    rec = NegativeKnowledgeRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        kind=NegativeKnowledgeKind.EXHAUSTIVE_SEARCH,
        source_iri="file:///data/intro.md#intro",
        search_summary="No CEO mentioned in the introduction section.",
    )

    assert rec.subject == "http://example.org/entity/Acme"
    assert rec.predicate == "http://example.org/ns/hasCEO"
    assert rec.kind == NegativeKnowledgeKind.EXHAUSTIVE_SEARCH
    assert rec.source_iri == "file:///data/intro.md#intro"
    assert "CEO" in rec.search_summary


def test_write_negative_knowledge_calls_pg_ripple() -> None:
    """write_negative_knowledge calls pg_ripple.load_triples_with_confidence."""
    from riverbank.negative_knowledge import (
        NegativeKnowledgeKind,
        NegativeKnowledgeRecord,
        write_negative_knowledge,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    rec = NegativeKnowledgeRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        kind=NegativeKnowledgeKind.EXHAUSTIVE_SEARCH,
        source_iri="file:///data/intro.md#intro",
    )

    result = write_negative_knowledge(conn, rec)

    assert result is True
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert "load_triples_with_confidence" in call_args[0]


def test_write_negative_knowledge_returns_false_on_pg_ripple_missing() -> None:
    """write_negative_knowledge returns False when pg_ripple is unavailable."""
    from riverbank.negative_knowledge import (
        NegativeKnowledgeKind,
        NegativeKnowledgeRecord,
        write_negative_knowledge,
    )

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pg_ripple.load_triples_with_confidence does not exist")

    rec = NegativeKnowledgeRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        kind=NegativeKnowledgeKind.EXHAUSTIVE_SEARCH,
    )

    result = write_negative_knowledge(conn, rec)
    assert result is False


def test_write_negative_knowledge_includes_search_summary() -> None:
    """write_negative_knowledge includes the search_summary in the payload."""
    import json

    from riverbank.negative_knowledge import (
        NegativeKnowledgeKind,
        NegativeKnowledgeRecord,
        write_negative_knowledge,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    rec = NegativeKnowledgeRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        kind=NegativeKnowledgeKind.EXHAUSTIVE_SEARCH,
        search_summary="Searched 5 pages, found nothing.",
    )

    write_negative_knowledge(conn, rec)

    call_args = conn.execute.call_args[0]
    # call_args is (sql, (json_str, graph)) — [1] is the params tuple
    params = call_args[1]
    payload = json.loads(params[0])
    objects = [t.get("object", "") for t in payload]
    assert any("Searched 5 pages" in str(o) for o in objects)


def test_write_negative_knowledge_includes_superseded_by() -> None:
    """write_negative_knowledge includes superseded_by when set."""
    import json

    from riverbank.negative_knowledge import (
        NegativeKnowledgeKind,
        NegativeKnowledgeRecord,
        write_negative_knowledge,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    rec = NegativeKnowledgeRecord(
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        kind=NegativeKnowledgeKind.SUPERSEDED,
        superseded_by="http://example.org/fact/acme-ceo-v2",
    )

    write_negative_knowledge(conn, rec)

    call_args = conn.execute.call_args[0]
    params = call_args[1]
    payload = json.loads(params[0])
    objects = [t.get("object", "") for t in payload]
    assert "http://example.org/fact/acme-ceo-v2" in objects


def test_evaluate_absence_rules_returns_records_for_missing_predicates() -> None:
    """evaluate_absence_rules returns NKRs for predicates absent from extraction."""
    from riverbank.negative_knowledge import (
        NegativeKnowledgeKind,
        evaluate_absence_rules,
    )

    extraction_results = [
        {"predicate": "http://example.org/ns/hasName", "object_value": "Acme Corp"},
    ]
    absence_rules = [
        {"predicate": "http://example.org/ns/hasCEO", "summary": "No CEO found."},
        {"predicate": "http://example.org/ns/hasName"},  # present — no NKR
    ]

    records = evaluate_absence_rules(
        extraction_results,
        absence_rules,
        subject="http://example.org/entity/Acme",
        source_iri="file:///data/intro.md",
    )

    assert len(records) == 1
    assert records[0].predicate == "http://example.org/ns/hasCEO"
    assert records[0].kind == NegativeKnowledgeKind.EXHAUSTIVE_SEARCH
    assert records[0].search_summary == "No CEO found."


def test_evaluate_absence_rules_empty_when_all_predicates_present() -> None:
    """evaluate_absence_rules returns [] when all required predicates are found."""
    from riverbank.negative_knowledge import evaluate_absence_rules

    extraction_results = [
        {"predicate": "http://example.org/ns/hasCEO"},
        {"predicate": "http://example.org/ns/hasName"},
    ]
    absence_rules = [
        {"predicate": "http://example.org/ns/hasCEO"},
        {"predicate": "http://example.org/ns/hasName"},
    ]

    records = evaluate_absence_rules(
        extraction_results,
        absence_rules,
        subject="http://example.org/entity/Acme",
    )

    assert records == []


def test_evaluate_absence_rules_ignores_rules_without_predicate() -> None:
    """evaluate_absence_rules skips rules that have no predicate key."""
    from riverbank.negative_knowledge import evaluate_absence_rules

    records = evaluate_absence_rules(
        extraction_results=[],
        absence_rules=[{"summary": "no predicate set"}],
        subject="http://example.org/entity/Acme",
    )

    assert records == []
