"""Unit tests for the full lint flow (v0.6.0).

Tests cover:
- run_full_lint: SHACL score gate + shape bundle violations
- pgc:LintFinding triple generation
- run_nightly_lint: Prefect flow wrapper
"""
from __future__ import annotations

import unittest.mock as mock


def test_run_full_lint_empty_violations_passes() -> None:
    """run_full_lint passes when score >= threshold and no violations."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()
    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.85):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=[]):
            result = run_full_lint(conn, "http://example.com/g", threshold=0.7)

    assert result["passed"] is True
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["shacl_score"] == 0.85


def test_run_full_lint_violation_marks_as_failed() -> None:
    """A single shape violation causes the lint to fail."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()
    violations = [
        {
            "focus_node": "entity:X",
            "constraint_component": "sh:MinCountConstraintComponent",
            "result_message": "prefLabel missing",
            "severity": "violation",
        }
    ]
    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.9):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=violations):
            result = run_full_lint(conn, "http://example.com/g")

    assert result["passed"] is False
    assert result["finding_count"] == 1
    f = result["findings"][0]
    assert f["subject_iri"] == "entity:X"
    assert "prefLabel missing" in f["message"]


def test_run_full_lint_multiple_violations() -> None:
    """run_full_lint reports all violations."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()
    violations = [
        {"focus_node": f"entity:E{i}", "constraint_component": "sh:Violation",
         "result_message": f"msg {i}", "severity": "warning"}
        for i in range(5)
    ]
    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.8):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=violations):
            result = run_full_lint(conn, "http://example.com/g")

    assert result["finding_count"] == 5
    assert len(result["findings"]) == 5


def test_lint_finding_contains_required_keys() -> None:
    """Each finding in the lint result has subject_iri, finding_type, message, severity."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()
    violations = [
        {
            "focus_node": "entity:Alpha",
            "constraint_component": "sh:PatternConstraintComponent",
            "result_message": "IRI does not match pattern",
            "severity": "error",
        }
    ]
    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.9):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=violations):
            result = run_full_lint(conn, "http://example.com/g")

    f = result["findings"][0]
    assert set(f.keys()) >= {"subject_iri", "finding_type", "message", "severity"}
    assert f["severity"] == "error"


def test_write_lint_finding_handles_pg_ripple_unavailable() -> None:
    """_write_lint_finding does not raise when pg_ripple is not available."""
    from riverbank.observability import _write_lint_finding

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    # Should not raise
    _write_lint_finding(
        conn,
        "http://example.com/g",
        "sh:Violation",
        "entity:X",
        "test message",
        "warning",
    )


def test_run_nightly_lint_processes_all_graphs() -> None:
    """run_nightly_lint returns one summary per graph."""
    from riverbank.observability import run_nightly_lint

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    graphs = [
        "http://riverbank.example/graph/trusted",
        "http://riverbank.example/graph/vocab",
    ]

    with mock.patch("riverbank.observability.create_engine", return_value=mock_engine):
        with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.93):
            with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=[]):
                results = run_nightly_lint(
                    named_graphs=graphs,
                    db_dsn="postgresql://test@localhost/test",
                )

    assert len(results) == 2
    assert all(r["passed"] for r in results)
