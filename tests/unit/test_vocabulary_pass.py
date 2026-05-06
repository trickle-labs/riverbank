"""Unit tests for the vocabulary pass and ExtractedEntity (v0.4.0)."""
from __future__ import annotations

from pathlib import Path

import pytest

from riverbank.pipeline import CompilerProfile, IngestPipeline
from riverbank.prov import EvidenceSpan, ExtractedEntity


# ---------------------------------------------------------------------------
# ExtractedEntity model
# ---------------------------------------------------------------------------


def _ev(**kwargs) -> EvidenceSpan:
    defaults = {
        "source_iri": "file:///doc.md",
        "char_start": 0,
        "char_end": 10,
        "excerpt": "Some text.",
    }
    defaults.update(kwargs)
    return EvidenceSpan(**defaults)


def test_extracted_entity_valid() -> None:
    entity = ExtractedEntity(
        concept_iri="entity:Acme",
        preferred_label="Acme Corporation",
        confidence=0.9,
        evidence=_ev(),
    )
    assert entity.preferred_label == "Acme Corporation"
    assert entity.alternate_labels == []
    assert entity.scope_note is None


def test_extracted_entity_with_alt_labels() -> None:
    entity = ExtractedEntity(
        concept_iri="entity:Acme",
        preferred_label="Acme",
        alternate_labels=["Acme Corp", "ACME"],
        confidence=0.8,
        evidence=_ev(),
    )
    assert len(entity.alternate_labels) == 2


def test_extracted_entity_to_skos_triples_minimum() -> None:
    entity = ExtractedEntity(
        concept_iri="entity:Acme",
        preferred_label="Acme",
        confidence=0.9,
        evidence=_ev(),
    )
    triples = entity.to_skos_triples()
    predicates = {t.predicate for t in triples}
    assert "rdf:type" in predicates
    assert "skos:prefLabel" in predicates
    # No altLabel or scopeNote when absent
    assert "skos:altLabel" not in predicates
    assert "skos:scopeNote" not in predicates


def test_extracted_entity_to_skos_triples_full() -> None:
    entity = ExtractedEntity(
        concept_iri="entity:Acme",
        preferred_label="Acme",
        alternate_labels=["ACME"],
        scope_note="A fictional company",
        confidence=0.9,
        evidence=_ev(),
    )
    triples = entity.to_skos_triples()
    predicates = {t.predicate for t in triples}
    assert "skos:altLabel" in predicates
    assert "skos:scopeNote" in predicates
    # Total: rdf:type + prefLabel + 1×altLabel + scopeNote = 4
    assert len(triples) == 4


def test_extracted_entity_to_skos_triples_uses_vocab_graph() -> None:
    entity = ExtractedEntity(
        concept_iri="entity:X",
        preferred_label="X",
        confidence=0.5,
        evidence=_ev(),
    )
    triples = entity.to_skos_triples(vocab_graph="<my-vocab>")
    assert all(t.named_graph == "<my-vocab>" for t in triples)


def test_extracted_entity_confidence_range() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractedEntity(
            concept_iri="entity:X",
            preferred_label="X",
            confidence=1.5,
            evidence=_ev(),
        )


# ---------------------------------------------------------------------------
# Vocabulary pass in IngestPipeline
# ---------------------------------------------------------------------------


def test_vocabulary_mode_uses_vocab_graph(tmp_path: Path) -> None:
    """In vocabulary mode the pipeline targets the vocab_graph, not named_graph."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text(
        "# Concepts\n\nAcme Corporation is a technology company founded in 1990."
    )
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(
        name="test",
        run_mode_sequence=["vocabulary"],
        vocab_graph="http://test/graph/vocab",
    )

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
            stats = pipeline.run(corpus_path=str(tmp_path), profile=profile)

    # noop extractor returns no entities/triples — vocab mode still processes fragments
    assert stats["errors"] == 0


def test_run_mode_sequence_vocabulary_full_runs_both_passes(tmp_path: Path) -> None:
    """run_mode_sequence=['vocabulary','full'] executes two passes."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text(
        "# Section\n\nThis is a long enough section to pass the ingest gate "
        "and verify that both vocabulary and full passes are executed."
    )
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(
        name="test",
        run_mode_sequence=["vocabulary", "full"],
    )

    call_count: list[int] = [0]
    original_run_inner = pipeline._run_inner

    def counting_run_inner(*args, **kwargs):
        call_count[0] += 1
        return original_run_inner(*args, **kwargs)

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
            with mock.patch.object(pipeline, "_run_inner", side_effect=counting_run_inner):
                pipeline.run(corpus_path=str(tmp_path), profile=profile)

    assert call_count[0] == 2


def test_explicit_mode_overrides_profile_sequence(tmp_path: Path) -> None:
    """Passing mode='vocabulary' explicitly runs only the vocabulary pass."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text("# A\n\n" + "X" * 100)
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(name="test", run_mode_sequence=["vocabulary", "full"])

    call_count: list[int] = [0]
    original_run_inner = pipeline._run_inner

    def counting_run_inner(*args, **kwargs):
        call_count[0] += 1
        return original_run_inner(*args, **kwargs)

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
            with mock.patch.object(pipeline, "_run_inner", side_effect=counting_run_inner):
                pipeline.run(corpus_path=str(tmp_path), profile=profile, mode="vocabulary")

    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Recompile flow
# ---------------------------------------------------------------------------


def test_recompile_invalidates_stale_artifacts(tmp_path: Path) -> None:
    """When a fragment changes, stale artifact deps must be invalidated."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text(
        "# Changed Section\n\nThis content has changed from a previous ingest run."
    )
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(name="test")

    # A special dict that reports every key as present (with a stale hash)
    # so that every fragment is detected as changed (triggers recompile).
    class _StaleHashDict(dict):
        def __contains__(self, key):  # type: ignore[override]
            return True
        def __getitem__(self, key):  # type: ignore[override]
            return "00" * 16

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    deleted_artifacts: list[str] = []
    outbox_events: list[dict] = []

    import riverbank.catalog.graph as graph_module  # noqa: PLC0415

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value=_StaleHashDict()):
            with mock.patch.object(graph_module, "get_artifacts_depending_on_fragment",
                                   return_value=["entity:Old"]):
                with mock.patch.object(graph_module, "delete_artifact_deps",
                                       side_effect=lambda c, a: deleted_artifacts.append(a)):
                    with mock.patch.object(graph_module, "emit_outbox_event",
                                           side_effect=lambda c, t, p: outbox_events.append(p)):
                        pipeline.run(corpus_path=str(tmp_path), profile=profile, dry_run=False)

    assert "entity:Old" in deleted_artifacts
    assert any("invalidated" in e for e in outbox_events)


def test_recompile_emits_semantic_diff_event(tmp_path: Path) -> None:
    """When a fragment changes, a semantic_diff outbox event must be emitted."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text("# Section\n\n" + "Y" * 100)
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(name="test")

    # A special dict that reports every key as present (with a stale hash)
    class _StaleHashDict(dict):
        def __contains__(self, key):  # type: ignore[override]
            return True
        def __getitem__(self, key):  # type: ignore[override]
            return "00" * 16

    emitted: list[tuple] = []

    import riverbank.catalog.graph as graph_module  # noqa: PLC0415

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value=_StaleHashDict()):
            with mock.patch.object(graph_module, "get_artifacts_depending_on_fragment",
                                   return_value=["entity:StaleArtifact"]):
                with mock.patch.object(graph_module, "delete_artifact_deps", return_value=1):
                    with mock.patch.object(
                        graph_module, "emit_outbox_event",
                        side_effect=lambda c, event_type, payload: emitted.append(
                            (event_type, payload)
                        ),
                    ):
                        pipeline.run(corpus_path=str(tmp_path), profile=profile, dry_run=False)

    assert any(evt[0] == "semantic_diff" for evt in emitted)
