"""Integration tests for Alembic catalog migrations.

These tests require a live PostgreSQL instance (provided by the
``db_dsn`` fixture from conftest.py via testcontainers-python).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text


def test_initial_migrations_create_all_tables(
    db_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alembic upgrade head must create all _riverbank catalog tables."""
    monkeypatch.setenv("RIVERBANK_DB__DSN", db_dsn)

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    engine = create_engine(db_dsn)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = '_riverbank'"
                " ORDER BY tablename"
            )
        ).fetchall()
    engine.dispose()

    found = {row[0] for row in rows}
    expected = {"profiles", "sources", "fragments", "runs", "artifact_deps", "log"}
    assert expected <= found, f"Missing tables: {expected - found}"


def test_alembic_version_table_exists(
    db_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After upgrade head, Alembic version table must be in _riverbank schema."""
    monkeypatch.setenv("RIVERBANK_DB__DSN", db_dsn)

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    engine = create_engine(db_dsn)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT version_num FROM _riverbank.alembic_version"
            )
        ).fetchone()
    engine.dispose()

    assert row is not None
    assert row[0] == "0001"


def test_downgrade_removes_application_tables(
    db_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Downgrade base must drop all application tables (alembic_version stays)."""
    monkeypatch.setenv("RIVERBANK_DB__DSN", db_dsn)

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    # Ensure we start from head
    command.upgrade(cfg, "head")
    # Downgrade to base (removes application tables; alembic_version remains)
    command.downgrade(cfg, "base")

    engine = create_engine(db_dsn)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = '_riverbank'"
                " AND tablename != 'alembic_version'"
            )
        ).fetchall()
    engine.dispose()

    assert rows == [], f"Application tables still exist after downgrade: {[r[0] for r in rows]}"
