"""Unit tests for the `riverbank validate-graph` CLI command."""
from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riverbank.cli import app
from riverbank.pipeline import CompilerProfile

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile_yaml(tmp_path: Path, cqs: list[dict]) -> Path:
    import yaml  # noqa: PLC0415

    data = {
        "name": "test-validate",
        "version": 1,
        "extractor": "noop",
        "named_graph": "http://test/graph",
        "competency_questions": cqs,
    }
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.dump(data))
    return p


def _sparql_returns(result_value: bool):
    """Return a mock sparql_query that always answers ASK with result_value."""
    return mock.MagicMock(return_value=[{"result": result_value}])


# ---------------------------------------------------------------------------
# Profile with no competency questions
# ---------------------------------------------------------------------------


def test_validate_graph_no_cqs(tmp_path: Path) -> None:
    profile_path = _make_profile_yaml(tmp_path, [])
    result = runner.invoke(app, ["validate-graph", "--profile", str(profile_path)])
    assert result.exit_code == 0
    assert "No competency_questions" in result.output


# ---------------------------------------------------------------------------
# All questions pass
# ---------------------------------------------------------------------------


def test_validate_graph_all_pass(tmp_path: Path) -> None:
    cqs = [
        {"id": "cq-01", "description": "Has a triple", "sparql": "ASK { ?s ?p ?o }"},
        {"id": "cq-02", "description": "Has a subject", "sparql": "ASK { ?s a ?t }"},
    ]
    profile_path = _make_profile_yaml(tmp_path, cqs)

    with mock.patch("riverbank.catalog.graph.sparql_query", return_value=[{"result": True}]):
        with mock.patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = mock.MagicMock()
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = mock.MagicMock(return_value=False)
            mock_engine.return_value.connect.return_value = mock_conn

            result = runner.invoke(app, ["validate-graph", "--profile", str(profile_path)])

    assert result.exit_code == 0
    assert "PASS" in result.output
    assert "2/2" in result.output
    assert "All competency questions passed" in result.output


# ---------------------------------------------------------------------------
# One question fails
# ---------------------------------------------------------------------------


def test_validate_graph_one_fail(tmp_path: Path) -> None:
    cqs = [
        {"id": "cq-01", "description": "Has a triple", "sparql": "ASK { ?s ?p ?o }"},
        {"id": "cq-02", "description": "Never true", "sparql": "ASK { ex:missing ex:p ex:q }"},
    ]
    profile_path = _make_profile_yaml(tmp_path, cqs)

    call_count = [0]
    def _side_effect(*args, **kwargs):
        call_count[0] += 1
        return [{"result": call_count[0] == 1}]  # first PASS, second FAIL

    with mock.patch("riverbank.catalog.graph.sparql_query", side_effect=_side_effect):
        with mock.patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = mock.MagicMock()
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = mock.MagicMock(return_value=False)
            mock_engine.return_value.connect.return_value = mock_conn

            result = runner.invoke(app, ["validate-graph", "--profile", str(profile_path)])

    assert "PASS" in result.output
    assert "FAIL" in result.output
    assert "1/2" in result.output
    assert "cq-02" in result.output


# ---------------------------------------------------------------------------
# --fail-below threshold
# ---------------------------------------------------------------------------


def test_validate_graph_fail_below_exits_nonzero(tmp_path: Path) -> None:
    """Coverage < --fail-below must produce exit code 1."""
    cqs = [
        {"id": "cq-01", "description": "Always false", "sparql": "ASK { ex:x ex:y ex:z }"},
    ]
    profile_path = _make_profile_yaml(tmp_path, cqs)

    with mock.patch("riverbank.catalog.graph.sparql_query", return_value=[{"result": False}]):
        with mock.patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = mock.MagicMock()
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = mock.MagicMock(return_value=False)
            mock_engine.return_value.connect.return_value = mock_conn

            result = runner.invoke(
                app,
                ["validate-graph", "--profile", str(profile_path), "--fail-below", "1.0"],
            )

    assert result.exit_code == 1
    assert "below threshold" in result.output


def test_validate_graph_fail_below_not_triggered_when_above(tmp_path: Path) -> None:
    cqs = [
        {"id": "cq-01", "description": "Passes", "sparql": "ASK { ?s ?p ?o }"},
    ]
    profile_path = _make_profile_yaml(tmp_path, cqs)

    with mock.patch("riverbank.catalog.graph.sparql_query", return_value=[{"result": True}]):
        with mock.patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = mock.MagicMock()
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = mock.MagicMock(return_value=False)
            mock_engine.return_value.connect.return_value = mock_conn

            result = runner.invoke(
                app,
                ["validate-graph", "--profile", str(profile_path), "--fail-below", "0.5"],
            )

    assert result.exit_code == 0
