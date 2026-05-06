"""Unit tests for the ``riverbank explain`` CLI command (v0.4.0)."""
from __future__ import annotations

import unittest.mock as mock

from typer.testing import CliRunner

from riverbank.cli import app


runner = CliRunner()


def test_explain_no_deps_prints_not_found() -> None:
    with mock.patch("riverbank.catalog.graph.get_artifact_deps", return_value=[]):
        with mock.patch("sqlalchemy.create_engine"):
            result = runner.invoke(app, ["explain", "entity:Unknown"])
    assert result.exit_code == 0
    assert "No dependency records" in result.output


def test_explain_with_deps_prints_table() -> None:
    deps = [
        {"dep_kind": "fragment", "dep_ref": "file:///doc.md#intro"},
        {"dep_kind": "profile_version", "dep_ref": "default@v1"},
        {"dep_kind": "rule_set", "dep_ref": "default"},
    ]
    with mock.patch("riverbank.catalog.graph.get_artifact_deps", return_value=deps):
        with mock.patch("sqlalchemy.create_engine"):
            result = runner.invoke(app, ["explain", "entity:Acme"])
    assert result.exit_code == 0
    assert "fragment" in result.output
    assert "profile_version" in result.output
    assert "file:///doc.md#intro" in result.output


def test_explain_db_error_exits_nonzero() -> None:
    with mock.patch("sqlalchemy.create_engine") as mock_engine:
        mock_engine.return_value.connect.side_effect = Exception("db down")
        result = runner.invoke(app, ["explain", "entity:X"])
    assert result.exit_code != 0


def test_explain_artifact_iri_in_output() -> None:
    with mock.patch("riverbank.catalog.graph.get_artifact_deps", return_value=[]):
        with mock.patch("sqlalchemy.create_engine"):
            result = runner.invoke(app, ["explain", "entity:Acme"])
    assert "entity:Acme" in result.output
