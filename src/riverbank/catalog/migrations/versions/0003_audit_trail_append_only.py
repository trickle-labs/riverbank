"""Audit trail: append-only _riverbank.log enforcement (v0.7.0)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-06

Makes the ``_riverbank.log`` table truly append-only at the database level:

* Revokes UPDATE and DELETE privileges from the ``riverbank`` role.
* Creates a ``log_append_only`` trigger that raises an exception if any
  UPDATE or DELETE is attempted on the ``log`` table.
* Adds a GIN index on ``payload`` for efficient JSON querying.

Note: ``operation`` and ``actor`` columns were already added in migration 0001
(initial schema) — this migration only adds the enforcement mechanism.

This satisfies the v0.7.0 requirement:
  "Every graph-mutating operation writes to _riverbank.log;
   append-only at the database level (REVOKE UPDATE, DELETE)."
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION _riverbank.log_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'The _riverbank.log table is append-only. '
        'UPDATE and DELETE are not permitted. '
        'TG_OP=%', TG_OP;
END;
$$;
"""

_TRIGGER_SQL = """
CREATE TRIGGER log_no_update_delete
BEFORE UPDATE OR DELETE ON _riverbank.log
FOR EACH ROW EXECUTE FUNCTION _riverbank.log_append_only();
"""

_DROP_TRIGGER_SQL = "DROP TRIGGER IF EXISTS log_no_update_delete ON _riverbank.log;"
_DROP_FUNCTION_SQL = "DROP FUNCTION IF EXISTS _riverbank.log_append_only();"


def upgrade() -> None:
    # 1. Add GIN index on payload for efficient JSON querying
    op.create_index(
        "ix_log_payload_gin",
        "log",
        ["payload"],
        schema="_riverbank",
        postgresql_using="gin",
    )

    # 2. Create the append-only trigger function and trigger
    conn = op.get_bind()
    conn.execute(sa.text(_TRIGGER_FUNCTION_SQL))
    conn.execute(sa.text(_TRIGGER_SQL))

    # 3. Revoke UPDATE and DELETE on the log table from the riverbank role.
    #    We use a DO block so that the migration does not fail in environments
    #    where the role does not exist (e.g. plain-PostgreSQL CI without the
    #    riverbank role).
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'riverbank') THEN
                REVOKE UPDATE, DELETE ON _riverbank.log FROM riverbank;
            END IF;
        END;
        $$;
    """))


def downgrade() -> None:
    conn = op.get_bind()

    # Re-grant UPDATE and DELETE (downgrade path only)
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'riverbank') THEN
                GRANT UPDATE, DELETE ON _riverbank.log TO riverbank;
            END IF;
        END;
        $$;
    """))

    # Drop trigger and function
    conn.execute(sa.text(_DROP_TRIGGER_SQL))
    conn.execute(sa.text(_DROP_FUNCTION_SQL))

    # Drop GIN index
    op.drop_index("ix_log_payload_gin", table_name="log", schema="_riverbank")
