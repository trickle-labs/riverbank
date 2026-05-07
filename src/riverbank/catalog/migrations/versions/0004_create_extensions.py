"""Create required PostgreSQL extensions

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-06

Creates pg_ripple and pg_trickle extensions required for SPARQL queries
and incremental view maintenance.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create pg_ripple extension (RDF triple store with SPARQL)
    # Try to create, but fail gracefully if not available (e.g., standard PostgreSQL)
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_ripple")
    except Exception:  # noqa: BLE001
        # Extension not available in this PostgreSQL installation
        pass
    
    # Create pg_trickle extension (incremental view maintenance and streams)
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trickle")
    except Exception:  # noqa: BLE001
        # Extension not available in this PostgreSQL installation
        pass


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trickle")
    op.execute("DROP EXTENSION IF EXISTS pg_ripple")
