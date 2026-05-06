"""Unit tests for SHACL score history and Prefect flows (v0.6.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_prefect_available_flag() -> None:
    """_PREFECT_AVAILABLE is a boolean (True or False depending on install)."""
    from riverbank.observability import _PREFECT_AVAILABLE

    assert isinstance(_PREFECT_AVAILABLE, bool)


def test_snapshot_shacl_scores_returns_list() -> None:
    """snapshot_shacl_scores returns a list with one entry per graph."""
    from riverbank.observability import snapshot_shacl_scores

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    graphs = [
        "http://riverbank.example/graph/trusted",
        "http://riverbank.example/graph/draft",
    ]

    with mock.patch("riverbank.observability.create_engine", return_value=mock_engine):
        with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.92):
            results = snapshot_shacl_scores(
                named_graphs=graphs,
                db_dsn="postgresql://test:test@localhost/test",
            )

    assert isinstance(results, list)
    assert len(results) == 2
    for r in results:
        assert "named_graph" in r
        assert "score" in r


def test_snapshot_shacl_scores_calls_shacl_score_per_graph() -> None:
    """snapshot_shacl_scores calls shacl_score once per named graph."""
    from riverbank.observability import snapshot_shacl_scores

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    graphs = ["http://example.com/g1", "http://example.com/g2", "http://example.com/g3"]

    with mock.patch("riverbank.observability.create_engine", return_value=mock_engine):
        with mock.patch(
            "riverbank.catalog.graph.shacl_score", return_value=0.85
        ) as mock_score:
            snapshot_shacl_scores(
                named_graphs=graphs,
                db_dsn="postgresql://test:test@localhost/test",
            )

    assert mock_score.call_count == 3


def test_run_full_lint_returns_summary() -> None:
    """run_full_lint returns a dict with expected keys."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()

    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.9):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=[]):
            result = run_full_lint(conn, "http://example.com/graph/trusted")

    assert "named_graph" in result
    assert "shacl_score" in result
    assert "passed" in result
    assert "finding_count" in result
    assert "findings" in result


def test_run_full_lint_passes_when_score_above_threshold() -> None:
    """run_full_lint reports passed=True when shacl_score >= threshold and no violations."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()

    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.95):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=[]):
            result = run_full_lint(conn, "http://example.com/g", threshold=0.7)

    assert result["passed"] is True
    assert result["finding_count"] == 0


def test_run_full_lint_fails_when_score_below_threshold() -> None:
    """run_full_lint reports passed=False when shacl_score < threshold."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()

    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.5):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=[]):
            result = run_full_lint(conn, "http://example.com/g", threshold=0.7)

    assert result["passed"] is False


def test_run_full_lint_records_violations_as_findings() -> None:
    """run_full_lint reports findings for shape bundle violations."""
    from riverbank.observability import run_full_lint

    conn = mock.MagicMock()
    violations = [
        {
            "focus_node": "entity:Acme",
            "constraint_component": "shacl:MinCountConstraintComponent",
            "result_message": "prefLabel required",
            "severity": "violation",
        }
    ]

    with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.9):
        with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=violations):
            result = run_full_lint(conn, "http://example.com/g")

    assert result["finding_count"] == 1
    assert result["findings"][0]["subject_iri"] == "entity:Acme"
    assert result["passed"] is False  # violations present even if score is OK


def test_run_nightly_lint_returns_list_of_summaries() -> None:
    """run_nightly_lint returns one summary dict per named graph."""
    from riverbank.observability import run_nightly_lint

    mock_engine = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_engine.connect.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = mock.MagicMock(return_value=False)

    graphs = ["http://example.com/g1", "http://example.com/g2"]

    with mock.patch("riverbank.observability.create_engine", return_value=mock_engine):
        with mock.patch("riverbank.catalog.graph.shacl_score", return_value=0.88):
            with mock.patch("riverbank.catalog.graph.run_shape_bundle", return_value=[]):
                results = run_nightly_lint(
                    named_graphs=graphs,
                    db_dsn="postgresql://test:test@localhost/test",
                )

    assert len(results) == 2
    for r in results:
        assert r["shacl_score"] == 0.88


def test_default_tracked_graphs_count() -> None:
    """The module exposes exactly four default tracked graphs."""
    from riverbank.observability import _DEFAULT_TRACKED_GRAPHS

    assert len(_DEFAULT_TRACKED_GRAPHS) == 4
    assert "http://riverbank.example/graph/trusted" in _DEFAULT_TRACKED_GRAPHS
    assert "http://riverbank.example/graph/human-review" in _DEFAULT_TRACKED_GRAPHS
