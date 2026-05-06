"""Add tenant_id column to all _riverbank tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06

Adds a nullable ``tenant_id`` column to all _riverbank catalog tables.
Row-level security is *not* activated here — that lands in v0.9.0 — but
the column is present so that all downstream migrations are additive-only.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables that receive the tenant_id column (order matters for indices)
_TABLES = ["profiles", "sources", "fragments", "runs", "artifact_deps", "log"]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.Text, nullable=True),
            schema="_riverbank",
        )
        op.create_index(
            f"ix_{table}_tenant_id",
            table,
            ["tenant_id"],
            schema="_riverbank",
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(
            f"ix_{table}_tenant_id",
            table_name=table,
            schema="_riverbank",
        )
        op.drop_column(table, "tenant_id", schema="_riverbank")
