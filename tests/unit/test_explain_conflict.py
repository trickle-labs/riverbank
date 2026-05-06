"""Unit tests for the explain-conflict CLI command (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock

from typer.testing import CliRunner

from riverbank.cli import app


def test_explain_conflict_command_exists() -> None:
    """'riverbank explain-conflict --help' must succeed."""
    runner = CliRunner()
    result = runner.invoke(app, ["explain-conflict", "--help"])
    assert result.exit_code == 0
    assert "iri" in result.output.lower() or "iRI" in result.output or "IRI" in result.output


def test_explain_conflict_no_contradictions_exits_0() -> None:
    """explain-conflict exits 0 and prints 'No contradictions found' when pg_ripple returns {}."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    # pg_ripple.explain_contradiction returns empty — no contradictions
    mock_conn.execute.return_value.fetchall.return_value = []

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(app, ["explain-conflict", "entity:Acme"])

    assert result.exit_code == 0
    assert "no contradictions" in result.output.lower()


def test_explain_conflict_shows_result_when_contradiction_found() -> None:
    """explain-conflict shows a table when pg_ripple returns contradiction data."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    # Simulate a pg_ripple row with contradiction explanation
    row = mock.MagicMock()
    row._mapping = {
        "cause_iri": "http://example.org/fact/old-ceo",
        "conflict_type": "owl:differentFrom violation",
        "explanation": "Alice and Bob cannot both be CEO",
    }
    mock_conn.execute.return_value.fetchall.return_value = [row]

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(app, ["explain-conflict", "entity:Acme"])

    assert result.exit_code == 0
    assert "contradiction" in result.output.lower()


def test_explain_conflict_graceful_when_pg_ripple_missing() -> None:
    """explain-conflict exits 0 and reports deferred when pg_ripple is unavailable."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    # Simulate pg_ripple function not available
    mock_conn.execute.side_effect = Exception("function pg_ripple.explain_contradiction does not exist")

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(app, ["explain-conflict", "entity:Acme"])

    assert result.exit_code == 0
    assert "no contradictions" in result.output.lower()


def test_explain_contradiction_function_returns_empty_on_missing_extension() -> None:
    """explain_contradiction in graph.py returns {} when pg_ripple is unavailable."""
    from riverbank.catalog.graph import explain_contradiction

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = explain_contradiction(conn, "entity:Acme")
    assert result == {}


def test_explain_contradiction_function_returns_row_dict() -> None:
    """explain_contradiction returns a dict when pg_ripple provides a result."""
    from riverbank.catalog.graph import explain_contradiction

    conn = mock.MagicMock()
    row = mock.MagicMock()
    row._mapping = {"cause_iri": "http://example.org/fact/old-ceo", "conflict_type": "owl:differentFrom"}
    conn.execute.return_value.fetchall.return_value = [row]

    result = explain_contradiction(conn, "entity:Acme")
    assert result["cause_iri"] == "http://example.org/fact/old-ceo"


def test_explain_contradiction_returns_empty_when_no_rows() -> None:
    """explain_contradiction returns {} when pg_ripple returns no rows."""
    from riverbank.catalog.graph import explain_contradiction

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    result = explain_contradiction(conn, "entity:Acme")
    assert result == {}


def test_explain_conflict_with_named_graph_option() -> None:
    """explain-conflict accepts --graph option."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = []

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(
            app,
            ["explain-conflict", "entity:Acme", "--graph", "http://example.org/graph/test"],
        )

    assert result.exit_code == 0
