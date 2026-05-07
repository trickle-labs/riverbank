"""Create required PostgreSQL extensions

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-06

Creates pg_ripple and pg_trickle extensions if available.

Note: PostgreSQL extensions might not be available in all environments.
This migration uses SAVEPOINTs to isolate extension creation attempts,
so that missing extensions don't abort the entire migration.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Try to create extensions using SAVEPOINTs to avoid transaction abort."""
    connection = op.get_context().bind

    # Create pg_ripple extension with SAVEPOINT isolation
    try:
        connection.execute("SAVEPOINT sp_pg_ripple")
        try:
            connection.execute("CREATE EXTENSION IF NOT EXISTS pg_ripple")
            connection.execute("RELEASE sp_pg_ripple")
        except Exception:  # noqa: BLE001
            connection.execute("ROLLBACK TO sp_pg_ripple")
    except Exception:  # noqa: BLE001
        pass

    # Create pg_trickle extension with SAVEPOINT isolation
    try:
        connection.execute("SAVEPOINT sp_pg_trickle")
        try:
            connection.execute("CREATE EXTENSION IF NOT EXISTS pg_trickle")
            connection.execute("RELEASE sp_pg_trickle")
        except Exception:  # noqa: BLE001
            connection.execute("ROLLBACK TO sp_pg_trickle")
    except Exception:  # noqa: BLE001
        pass


def downgrade() -> None:
    """Drop extensions using SAVEPOINTs."""
    connection = op.get_context().bind

    try:
        connection.execute("SAVEPOINT sp_drop_pg_trickle")
        try:
            connection.execute("DROP EXTENSION IF EXISTS pg_trickle CASCADE")
            connection.execute("RELEASE sp_drop_pg_trickle")
        except Exception:  # noqa: BLE001
            connection.execute("ROLLBACK TO sp_drop_pg_trickle")
    except Exception:  # noqa: BLE001
        pass

    try:
        connection.execute("SAVEPOINT sp_drop_pg_ripple")
        try:
            connection.execute("DROP EXTENSION IF EXISTS pg_ripple CASCADE")
            connection.execute("RELEASE sp_drop_pg_ripple")
        except Exception:  # noqa: BLE001
            connection.execute("ROLLBACK TO sp_drop_pg_ripple")
    except Exception:  # noqa: BLE001
        pass
