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
    assert row[0] == "0002"


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


def test_tenant_id_column_exists_after_migration(
    db_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After upgrade head (0002), all catalog tables must have a nullable tenant_id column."""
    monkeypatch.setenv("RIVERBANK_DB__DSN", db_dsn)

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    tables = ["profiles", "sources", "fragments", "runs", "artifact_deps", "log"]
    engine = create_engine(db_dsn)
    with engine.connect() as conn:
        for table in tables:
            row = conn.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = '_riverbank' "
                    "  AND table_name = :table "
                    "  AND column_name = 'tenant_id'"
                ),
                {"table": table},
            ).fetchone()
            assert row is not None, f"tenant_id missing from _riverbank.{table}"
            assert row[1] == "YES", f"tenant_id in {table} must be nullable"
    engine.dispose()


def test_migration_0001_to_0002_is_incremental(
    db_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration 0001 must be a valid stopping point before 0002 applies."""
    monkeypatch.setenv("RIVERBANK_DB__DSN", db_dsn)

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    # Upgrade to the specific revision 0001 only
    command.upgrade(cfg, "0001")

    engine = create_engine(db_dsn)
    with engine.connect() as conn:
        ver = conn.execute(
            text("SELECT version_num FROM _riverbank.alembic_version")
        ).fetchone()
        # tenant_id must NOT exist yet
        row = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = '_riverbank' "
                "  AND table_name = 'profiles' "
                "  AND column_name = 'tenant_id'"
            )
        ).fetchone()
    engine.dispose()

    assert ver is not None and ver[0] == "0001"
    assert row is None, "tenant_id should not exist before migration 0002"

    # Now apply 0002
    command.upgrade(cfg, "head")
    engine = create_engine(db_dsn)
    with engine.connect() as conn:
        ver2 = conn.execute(
            text("SELECT version_num FROM _riverbank.alembic_version")
        ).fetchone()
        row2 = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = '_riverbank' "
                "  AND table_name = 'profiles' "
                "  AND column_name = 'tenant_id'"
            )
        ).fetchone()
    engine.dispose()

    assert ver2 is not None and ver2[0] == "0002"
    assert row2 is not None, "tenant_id must exist after migration 0002"

