"""Unit tests for the artifact dependency graph (v0.4.0).

Exercises ``record_artifact_dep``, ``get_artifact_deps``,
``get_artifacts_depending_on_fragment``, and ``delete_artifact_deps`` via
mocked DB connections (no real PostgreSQL required).
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from riverbank.catalog.graph import (
    delete_artifact_deps,
    get_artifact_deps,
    get_artifacts_depending_on_fragment,
    record_artifact_dep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conn(fetchall=None, fetchone=None, rowcount=0):
    """Return a minimal mock connection."""
    conn = mock.MagicMock()
    result = mock.MagicMock()
    result.fetchall.return_value = fetchall or []
    result.fetchone.return_value = fetchone
    result.rowcount = rowcount
    conn.execute.return_value = result
    return conn


# ---------------------------------------------------------------------------
# record_artifact_dep
# ---------------------------------------------------------------------------


def test_record_artifact_dep_executes_upsert() -> None:
    conn = _conn()
    record_artifact_dep(conn, "entity:Acme", "fragment", "file:///doc.md#intro")
    assert conn.execute.called


def test_record_artifact_dep_silently_ignores_db_error() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("table missing")
    # Should not raise
    record_artifact_dep(conn, "entity:Acme", "fragment", "file:///doc.md#intro")


# ---------------------------------------------------------------------------
# get_artifact_deps
# ---------------------------------------------------------------------------


def test_get_artifact_deps_returns_rows() -> None:
    rows = [("fragment", "file:///doc.md#intro"), ("profile_version", "default@v1")]
    conn = _conn(fetchall=rows)
    deps = get_artifact_deps(conn, "entity:Acme")
    assert len(deps) == 2
    assert deps[0]["dep_kind"] == "fragment"
    assert deps[0]["dep_ref"] == "file:///doc.md#intro"


def test_get_artifact_deps_returns_empty_on_no_rows() -> None:
    conn = _conn(fetchall=[])
    deps = get_artifact_deps(conn, "entity:Unknown")
    assert deps == []


def test_get_artifact_deps_returns_empty_on_db_error() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("relation does not exist")
    deps = get_artifact_deps(conn, "entity:Acme")
    assert deps == []


# ---------------------------------------------------------------------------
# get_artifacts_depending_on_fragment
# ---------------------------------------------------------------------------


def test_get_artifacts_depending_on_fragment_returns_iris() -> None:
    rows = [("entity:Acme",), ("entity:Corp",)]
    conn = _conn(fetchall=rows)
    artifacts = get_artifacts_depending_on_fragment(conn, "file:///doc.md#intro")
    assert "entity:Acme" in artifacts
    assert "entity:Corp" in artifacts


def test_get_artifacts_depending_on_fragment_empty_on_error() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("missing")
    assert get_artifacts_depending_on_fragment(conn, "file:///doc.md#x") == []


# ---------------------------------------------------------------------------
# delete_artifact_deps
# ---------------------------------------------------------------------------


def test_delete_artifact_deps_returns_rowcount() -> None:
    conn = _conn(rowcount=3)
    deleted = delete_artifact_deps(conn, "entity:Acme")
    assert deleted == 3


def test_delete_artifact_deps_returns_zero_on_error() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("missing")
    assert delete_artifact_deps(conn, "entity:X") == 0


# ---------------------------------------------------------------------------
# Pipeline helper: _record_triples_deps
# ---------------------------------------------------------------------------


def test_record_triples_deps_records_three_edges_per_subject() -> None:
    """Each unique subject gets fragment, profile_version, and rule_set edges."""
    from riverbank.pipeline import CompilerProfile, _record_triples_deps  # noqa: PLC0415

    from riverbank.prov import EvidenceSpan, ExtractedTriple  # noqa: PLC0415

    ev = EvidenceSpan(source_iri="file:///doc.md", char_start=0, char_end=5, excerpt="Hello")
    triples = [
        ExtractedTriple(subject="entity:Acme", predicate="rdf:type", object_value="org:Org",
                        confidence=0.9, evidence=ev),
        ExtractedTriple(subject="entity:Acme", predicate="rdfs:label", object_value="Acme",
                        confidence=0.9, evidence=ev),
        ExtractedTriple(subject="entity:Corp", predicate="rdf:type", object_value="org:Org",
                        confidence=0.8, evidence=ev),
    ]

    recorded: list[tuple] = []

    def _fake_record(conn, artifact_iri, dep_kind, dep_ref):
        recorded.append((artifact_iri, dep_kind, dep_ref))

    profile = CompilerProfile(name="test", version=2)
    _record_triples_deps(mock.MagicMock(), triples, "file:///doc.md#s1", profile, _fake_record)

    # 2 unique subjects × 3 edge kinds = 6 edges
    assert len(recorded) == 6
    subjects = {r[0] for r in recorded}
    assert subjects == {"entity:Acme", "entity:Corp"}
    kinds = {r[1] for r in recorded}
    assert kinds == {"fragment", "profile_version", "rule_set"}


def test_record_triples_deps_empty_list_is_noop() -> None:
    from riverbank.pipeline import CompilerProfile, _record_triples_deps  # noqa: PLC0415

    recorded: list = []

    def _fake_record(*args):
        recorded.append(args)

    _record_triples_deps(mock.MagicMock(), [], "file:///x#s", CompilerProfile(name="p"),
                         _fake_record)
    assert recorded == []
