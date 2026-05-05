from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from riverbank.catalog import Base


class Profile(Base):
    """A versioned compiler profile (prompt + schema + editorial policy)."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompt_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    editorial_policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[Optional[str]] = mapped_column(Text)
    max_fragment_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="2000"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("name", "version"),)

    sources: Mapped[list[Source]] = relationship(back_populates="profile")
    runs: Mapped[list[Run]] = relationship(back_populates="profile")


class Source(Base):
    """A registered source document (logical identifier, not a fragment)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    iri: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("_riverbank.profiles.id"), nullable=False
    )
    named_graph: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_compiled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="'pending'")
    source_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    profile: Mapped[Profile] = relationship(back_populates="sources")
    fragments: Mapped[list[Fragment]] = relationship(back_populates="source")


class Fragment(Base):
    """A stable section of a source (page, heading, time segment, …)."""

    __tablename__ = "fragments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("_riverbank.sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    fragment_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    char_start: Mapped[Optional[int]] = mapped_column(Integer)
    char_end: Mapped[Optional[int]] = mapped_column(Integer)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    heading_path: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    text_excerpt: Mapped[Optional[str]] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="fragments")
    runs: Mapped[list[Run]] = relationship(back_populates="fragment")

    __table_args__ = (
        UniqueConstraint("source_id", "fragment_key"),
        Index("ix_fragments_content_hash", "content_hash"),
    )


class Run(Base):
    """One compile attempt (success or failure) for a fragment under a profile."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fragment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("_riverbank.fragments.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("_riverbank.profiles.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(12, 6))
    output_hash: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    diagnostics: Mapped[Optional[dict]] = mapped_column(JSONB)
    langfuse_trace_id: Mapped[Optional[str]] = mapped_column(Text)

    fragment: Mapped[Fragment] = relationship(back_populates="runs")
    profile: Mapped[Profile] = relationship(back_populates="runs")

    __table_args__ = (
        Index("ix_runs_fragment_started", "fragment_id", "started_at"),
        Index("ix_runs_profile_started", "profile_id", "started_at"),
    )


class ArtifactDep(Base):
    """Dependency graph edge: which compiled artifact depends on which fragments/rules."""

    __tablename__ = "artifact_deps"

    artifact_iri: Mapped[str] = mapped_column(Text, primary_key=True)
    dep_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    dep_ref: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (Index("ix_artifact_deps_kind_ref", "dep_kind", "dep_ref"),)


class LogEntry(Base):
    """Append-only audit log of every compile-side operation."""

    __tablename__ = "log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(Text)
    subject_iri: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_log_occurred_at", "occurred_at"),
        Index("ix_log_operation_occurred", "operation", "occurred_at"),
    )
