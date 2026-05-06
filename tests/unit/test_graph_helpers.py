"""Unit tests for graph helpers: emit_outbox_event, load_shape_bundle, run_shape_bundle (v0.4.0)."""
from __future__ import annotations

import unittest.mock as mock

from riverbank.catalog.graph import (
    emit_outbox_event,
    load_shape_bundle,
    run_shape_bundle,
)


def test_emit_outbox_event_calls_pgtrickle() -> None:
    conn = mock.MagicMock()
    result = emit_outbox_event(conn, "semantic_diff", {"fragment_iri": "file:///doc.md#s"})
    assert conn.execute.called


def test_emit_outbox_event_falls_back_when_pgtrickle_missing() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pgtrickle.attach_outbox does not exist")
    # Must not raise
    result = emit_outbox_event(conn, "semantic_diff", {"fragment_iri": "x"})
    assert result is False


def test_emit_outbox_event_raises_on_unexpected_error() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = RuntimeError("connection refused")
    import pytest
    with pytest.raises(RuntimeError):
        emit_outbox_event(conn, "semantic_diff", {"x": "y"})


def test_load_shape_bundle_calls_pg_ripple() -> None:
    conn = mock.MagicMock()
    loaded = load_shape_bundle(conn, "skos-integrity")
    assert conn.execute.called
    assert loaded is True


def test_load_shape_bundle_falls_back_when_pg_ripple_missing() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pg_ripple.load_shape_bundle does not exist")
    result = load_shape_bundle(conn, "skos-integrity")
    assert result is False


def test_run_shape_bundle_returns_empty_when_pg_ripple_missing() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pg_ripple.run_shape_bundle does not exist")
    results = run_shape_bundle(conn, "skos-integrity", "http://test/vocab")
    assert results == []


def test_run_shape_bundle_returns_rows_as_dicts() -> None:
    row = mock.MagicMock()
    row._mapping = {"focus_node": "entity:X", "message": "prefLabel missing"}
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [row]
    results = run_shape_bundle(conn, "skos-integrity", "http://test/vocab")
    assert len(results) == 1
    assert results[0]["focus_node"] == "entity:X"
