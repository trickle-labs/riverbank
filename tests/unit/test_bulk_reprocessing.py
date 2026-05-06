"""Unit tests for bulk reprocessing (riverbank recompile) — v0.7.0."""
from __future__ import annotations

import unittest.mock as mock

from typer.testing import CliRunner

from riverbank.cli import app


def test_recompile_command_exists() -> None:
    """'riverbank recompile --help' must succeed (command is registered)."""
    runner = CliRunner()
    result = runner.invoke(app, ["recompile", "--help"])
    assert result.exit_code == 0
    assert "profile" in result.output.lower()
    assert "version" in result.output.lower()


def test_recompile_dry_run_lists_sources_without_running() -> None:
    """--dry-run prints candidate sources and exits 0 without recompiling."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    # Profile lookup returns a row with id=1
    profile_row = (1,)
    # Sources lookup returns two source IRIs
    source_rows = [
        ("file:///data/intro.md",),
        ("file:///data/concepts.md",),
    ]
    mock_conn.execute.return_value.fetchone.return_value = profile_row
    mock_conn.execute.return_value.fetchall.return_value = source_rows

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(
            app,
            [
                "recompile",
                "--profile", "docs-policy-v1",
                "--version", "1",
                "--dry-run",
            ],
        )

    assert result.exit_code == 0
    assert "dry-run" in result.output.lower()


def test_recompile_exits_1_when_profile_not_found() -> None:
    """recompile exits 1 when the profile does not exist in the catalog."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    # Profile lookup returns None
    mock_conn.execute.return_value.fetchone.return_value = None

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(
            app,
            [
                "recompile",
                "--profile", "nonexistent-profile",
                "--version", "99",
            ],
        )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_recompile_no_sources_exits_0() -> None:
    """recompile exits 0 with a helpful message when no sources are found."""
    runner = CliRunner()

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    # Profile found, no sources
    mock_conn.execute.return_value.fetchone.return_value = (1,)
    mock_conn.execute.return_value.fetchall.return_value = []

    with mock.patch("sqlalchemy.create_engine", return_value=mock_engine):
        result = runner.invoke(
            app,
            [
                "recompile",
                "--profile", "docs-policy-v1",
                "--version", "1",
            ],
        )

    assert result.exit_code == 0
    assert "no sources found" in result.output.lower()


def test_recompile_help_shows_limit_option() -> None:
    """--limit option is documented in help."""
    runner = CliRunner()
    result = runner.invoke(app, ["recompile", "--help"])
    assert result.exit_code == 0
    assert "limit" in result.output.lower()
