"""Initial _riverbank schema

Revision ID: 0001
Revises:
Create Date: 2026-05-05

Creates the _riverbank schema and all catalog tables:
profiles, sources, fragments, runs, artifact_deps, log.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS _riverbank")

    op.create_table(
        "profiles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("schema_json", JSONB, nullable=False),
        sa.Column("prompt_hash", sa.LargeBinary, nullable=False),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("editorial_policy", JSONB, nullable=False),
        sa.Column("model_provider", sa.Text, nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("embedding_model", sa.Text),
        sa.Column("max_fragment_tokens", sa.Integer, nullable=False, server_default="2000"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", "version"),
        schema="_riverbank",
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("iri", sa.Text, unique=True, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("connector", sa.Text, nullable=False),
        sa.Column(
            "profile_id",
            sa.BigInteger,
            sa.ForeignKey("_riverbank.profiles.id"),
            nullable=False,
        ),
        sa.Column("named_graph", sa.Text, nullable=False),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_compiled_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="'pending'"),
        sa.Column("metadata", JSONB, nullable=False, server_default="'{}'"),
        schema="_riverbank",
    )

    op.create_table(
        "fragments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "source_id",
            sa.BigInteger,
            sa.ForeignKey("_riverbank.sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fragment_key", sa.Text, nullable=False),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("char_start", sa.Integer),
        sa.Column("char_end", sa.Integer),
        sa.Column("page_number", sa.Integer),
        sa.Column("heading_path", ARRAY(sa.Text)),
        sa.Column("text_excerpt", sa.Text),
        sa.UniqueConstraint("source_id", "fragment_key"),
        schema="_riverbank",
    )
    op.create_index(
        "ix_fragments_content_hash", "fragments", ["content_hash"], schema="_riverbank"
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fragment_id",
            sa.BigInteger,
            sa.ForeignKey("_riverbank.fragments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.BigInteger,
            sa.ForeignKey("_riverbank.profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("prompt_tokens", sa.Integer),
        sa.Column("completion_tokens", sa.Integer),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("output_hash", sa.LargeBinary),
        sa.Column("diagnostics", JSONB),
        sa.Column("langfuse_trace_id", sa.Text),
        schema="_riverbank",
    )
    op.create_index(
        "ix_runs_fragment_started", "runs", ["fragment_id", "started_at"], schema="_riverbank"
    )
    op.create_index(
        "ix_runs_profile_started", "runs", ["profile_id", "started_at"], schema="_riverbank"
    )

    op.create_table(
        "artifact_deps",
        sa.Column("artifact_iri", sa.Text, primary_key=True),
        sa.Column("dep_kind", sa.Text, primary_key=True),
        sa.Column("dep_ref", sa.Text, primary_key=True),
        schema="_riverbank",
    )
    op.create_index(
        "ix_artifact_deps_kind_ref", "artifact_deps", ["dep_kind", "dep_ref"],
        schema="_riverbank",
    )

    op.create_table(
        "log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("operation", sa.Text, nullable=False),
        sa.Column("actor", sa.Text),
        sa.Column("subject_iri", sa.Text),
        sa.Column("payload", JSONB, nullable=False),
        schema="_riverbank",
    )
    op.create_index("ix_log_occurred_at", "log", ["occurred_at"], schema="_riverbank")
    op.create_index(
        "ix_log_operation_occurred", "log", ["operation", "occurred_at"], schema="_riverbank"
    )


def downgrade() -> None:
    op.drop_table("log", schema="_riverbank")
    op.drop_table("artifact_deps", schema="_riverbank")
    op.drop_table("runs", schema="_riverbank")
    op.drop_table("fragments", schema="_riverbank")
    op.drop_table("sources", schema="_riverbank")
    op.drop_table("profiles", schema="_riverbank")
    # Note: the _riverbank schema is intentionally NOT dropped here.
    # Alembic stores its version table in _riverbank.alembic_version and
    # needs it to exist until after this function returns.
