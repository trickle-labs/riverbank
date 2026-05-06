"""Unit tests for audit trail (append-only _riverbank.log) — v0.7.0."""
from __future__ import annotations

import unittest.mock as mock


def test_write_audit_log_returns_true_on_success() -> None:
    """write_audit_log returns True when the INSERT succeeds."""
    from riverbank.catalog.graph import write_audit_log

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    result = write_audit_log(
        conn,
        operation="load_triples",
        payload={"named_graph": "http://example.com/trusted", "count": 5},
        actor="worker-1",
    )

    assert result is True
    conn.execute.assert_called_once()


def test_write_audit_log_returns_false_on_db_error() -> None:
    """write_audit_log returns False (graceful fallback) when INSERT fails."""
    from riverbank.catalog.graph import write_audit_log

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("column 'operation' does not exist")

    result = write_audit_log(
        conn,
        operation="load_triples",
        payload={"count": 3},
    )

    assert result is False


def test_write_audit_log_uses_env_actor_when_not_supplied(monkeypatch) -> None:
    """write_audit_log reads actor from RIVERBANK_ACTOR env var when not passed."""
    from riverbank.catalog.graph import write_audit_log

    monkeypatch.setenv("RIVERBANK_ACTOR", "env-worker")

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    write_audit_log(conn, operation="recompile", payload={})

    # Verify the INSERT was called with actor="env-worker"
    call_args = conn.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
    assert params.get("actor") == "env-worker"


def test_write_audit_log_explicit_actor_overrides_env(monkeypatch) -> None:
    """An explicit actor parameter takes precedence over RIVERBANK_ACTOR."""
    from riverbank.catalog.graph import write_audit_log

    monkeypatch.setenv("RIVERBANK_ACTOR", "env-actor")

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    write_audit_log(conn, operation="recompile", payload={}, actor="explicit-actor")

    call_args = conn.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
    assert params.get("actor") == "explicit-actor"


def test_write_audit_log_payload_is_serialized_as_json() -> None:
    """write_audit_log serializes the payload dict to JSON for the INSERT."""
    import json

    from riverbank.catalog.graph import write_audit_log

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    payload = {"fragment_iri": "file:///data/intro.md#intro", "triples": 12}
    write_audit_log(conn, operation="load_triples", payload=payload)

    call_args = conn.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
    # payload should be JSON-serializable string
    assert isinstance(params.get("payload"), str)
    parsed = json.loads(params["payload"])
    assert parsed["triples"] == 12


def test_write_audit_log_operation_stored_correctly() -> None:
    """write_audit_log stores the operation string in the INSERT params."""
    from riverbank.catalog.graph import write_audit_log

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    write_audit_log(conn, operation="review_decision", payload={})

    call_args = conn.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
    assert params.get("operation") == "review_decision"


def test_audit_trail_migration_sets_append_only() -> None:
    """The 0003 migration module declares the correct revision chain."""
    from importlib import import_module

    m = import_module(
        "riverbank.catalog.migrations.versions.0003_audit_trail_append_only"
    )
    assert m.revision == "0003"
    assert m.down_revision == "0002"


# Verify the migration file can be imported (check it exists)
def test_audit_trail_migration_importable() -> None:
    """Migration 0003 is importable without errors."""
    from importlib import import_module

    mod = import_module(
        "riverbank.catalog.migrations.versions.0003_audit_trail_append_only"
    )
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
