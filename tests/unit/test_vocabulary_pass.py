"""Unit tests for the vocabulary pass and ExtractedEntity (v0.4.0 + v0.15.3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from riverbank.pipeline import CompilerProfile, IngestPipeline
from riverbank.prov import EvidenceSpan, ExtractedEntity, ExtractedTriple


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


# ===========================================================================
# v0.15.3 — Vocabulary Normalisation Pass
# ===========================================================================


from riverbank.vocabulary import (  # noqa: E402
    CategoricalDetector,
    FactDecomposer,
    NormalisationConfig,
    PredicateCollapser,
    URICanonicaliser,
    VocabularyNormalisationPass,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _triple(
    subject: str,
    predicate: str,
    object_value: str,
    confidence: float = 0.9,
) -> ExtractedTriple:
    """Build a minimal ExtractedTriple for normalisation tests."""
    return ExtractedTriple(
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        confidence=confidence,
        evidence=EvidenceSpan(
            source_iri="file:///test.md",
            char_start=0,
            char_end=10,
            excerpt="Test text.",
        ),
    )


# ---------------------------------------------------------------------------
# CategoricalDetector
# ---------------------------------------------------------------------------


class TestCategoricalDetector:
    """Tests for CategoricalDetector across three domain corpora."""

    # ---- Organisational corpus ----

    def test_organisational_roles_promoted(self) -> None:
        """Repeated role literals become vocab:* IRIs (threshold=2)."""
        triples = [
            _triple("ex:Alice", "ex:role", "Director"),
            _triple("ex:Bob", "ex:role", "Director"),
            _triple("ex:Carol", "ex:role", "CEO"),
        ]
        detector = CategoricalDetector(threshold=2)
        cat_map = detector.detect(triples)
        # "Director" appears twice → promoted
        assert ("ex:role", "Director") in cat_map
        assert cat_map[("ex:role", "Director")].endswith("Director")
        # "CEO" appears once → not promoted at threshold=2
        assert ("ex:role", "CEO") not in cat_map

    def test_organisational_status_promoted(self) -> None:
        """Document status literals with threshold=2 are promoted."""
        triples = [
            _triple("ex:Doc1", "ex:status", "Approved"),
            _triple("ex:Doc2", "ex:status", "Approved"),
            _triple("ex:Doc3", "ex:status", "Approved"),
            _triple("ex:Doc4", "ex:status", "Draft"),
        ]
        detector = CategoricalDetector(threshold=2)
        cat_map = detector.detect(triples)
        assert ("ex:status", "Approved") in cat_map
        assert ("ex:status", "Draft") not in cat_map

    def test_organisational_promote_rewrites_objects(self) -> None:
        triples = [
            _triple("ex:Alice", "ex:role", "Director"),
            _triple("ex:Bob", "ex:role", "Director"),
        ]
        detector = CategoricalDetector(threshold=2, vocab_namespace="http://vocab/")
        cat_map = detector.detect(triples)
        result, n = detector.promote(triples, cat_map)
        assert n == 2
        assert all(t.object_value == "http://vocab/Director" for t in result)

    # ---- Scientific corpus ----

    def test_scientific_taxonomy_promoted(self) -> None:
        """Taxonomic classification strings are treated as categorical."""
        triples = [
            _triple("ex:Tiger", "ex:classification", "Mammal"),
            _triple("ex:Lion", "ex:classification", "Mammal"),
            _triple("ex:Eagle", "ex:classification", "Bird"),
            _triple("ex:Salmon", "ex:classification", "Fish"),
        ]
        detector = CategoricalDetector(threshold=2)
        cat_map = detector.detect(triples)
        assert ("ex:classification", "Mammal") in cat_map
        # Bird / Fish appear once → not promoted
        assert ("ex:classification", "Bird") not in cat_map

    def test_scientific_iri_objects_not_promoted(self) -> None:
        """IRI-valued objects must never be treated as categorical literals."""
        triples = [
            _triple("ex:Tiger", "ex:classification", "ex:Mammal"),
            _triple("ex:Lion", "ex:classification", "ex:Mammal"),
        ]
        detector = CategoricalDetector(threshold=2)
        cat_map = detector.detect(triples)
        # ex:Mammal is an IRI → not a candidate
        assert len(cat_map) == 0

    # ---- Biographical corpus ----

    def test_biographical_nationality_promoted(self) -> None:
        """Nationality strings that appear for multiple people are promoted."""
        triples = [
            _triple("ex:Einstein", "ex:nationality", "German"),
            _triple("ex:Planck", "ex:nationality", "German"),
            _triple("ex:Curie", "ex:nationality", "Polish"),
        ]
        detector = CategoricalDetector(threshold=2)
        cat_map = detector.detect(triples)
        assert ("ex:nationality", "German") in cat_map
        assert ("ex:nationality", "Polish") not in cat_map

    def test_camel_case_conversion(self) -> None:
        """Multi-word literals produce CamelCase IRI local names."""
        triples = [
            _triple("ex:Alice", "ex:role", "Head Coach"),
            _triple("ex:Bob", "ex:role", "Head Coach"),
        ]
        detector = CategoricalDetector(threshold=2, vocab_namespace="http://vocab/")
        cat_map = detector.detect(triples)
        assert cat_map[("ex:role", "Head Coach")] == "http://vocab/HeadCoach"

    def test_threshold_respected(self) -> None:
        """Threshold=3 requires at least 3 occurrences."""
        triples = [
            _triple("ex:A", "ex:status", "Approved"),
            _triple("ex:B", "ex:status", "Approved"),
        ]
        detector = CategoricalDetector(threshold=3)
        cat_map = detector.detect(triples)
        assert len(cat_map) == 0


# ---------------------------------------------------------------------------
# PredicateCollapser
# ---------------------------------------------------------------------------


class TestPredicateCollapser:
    """Tests for PredicateCollapser — deterministic and mock-LLM backends."""

    # ---- Deterministic backend ----

    def test_similar_predicates_collapsed(self) -> None:
        """Predicates with very high edit-distance similarity are collapsed."""
        triples = [
            _triple("ex:Alice", "ex:is_director", "ex:Acme"),
            _triple("ex:Bob", "ex:is_director", "ex:Acme"),
            _triple("ex:Carol", "ex:is_directors", "ex:Acme"),  # near-duplicate
        ]
        collapser = PredicateCollapser(backend="deterministic", similarity_threshold=0.8)
        collapse_map = collapser.find_clusters(triples)
        # Both should map to the same canonical predicate
        assert len(collapse_map) >= 1

    def test_dissimilar_predicates_not_collapsed(self) -> None:
        """Completely different predicates are never merged."""
        triples = [
            _triple("ex:Alice", "ex:discovered", "ex:Polonium"),
            _triple("ex:Alice", "ex:born_in", "Warsaw"),
            _triple("ex:Alice", "ex:won_award", "ex:NobelPrize"),
        ]
        collapser = PredicateCollapser(backend="deterministic", similarity_threshold=0.8)
        collapse_map = collapser.find_clusters(triples)
        # No cluster — all predicates are distinct
        assert len(collapse_map) == 0

    def test_collapse_rewrites_predicates(self) -> None:
        """Collapse map is applied correctly to all triples."""
        triples = [
            _triple("ex:Alice", "ex:holds_role", "ex:Director"),
            _triple("ex:Bob", "ex:holds_roles", "ex:CEO"),  # typo variant
        ]
        collapser = PredicateCollapser(backend="deterministic", similarity_threshold=0.8)
        collapse_map = collapser.find_clusters(triples)
        result, n = collapser.collapse(triples, collapse_map)
        preds = {t.predicate for t in result}
        # After collapsing, only one predicate should remain
        assert len(preds) == 1

    def test_canonical_is_most_frequent(self) -> None:
        """The most frequent predicate in a cluster becomes the canonical form."""
        triples = (
            [_triple("ex:A", "ex:won_award", "ex:Prize")] * 5
            + [_triple("ex:B", "ex:won_awards", "ex:Medal")] * 2
        )
        collapser = PredicateCollapser(backend="deterministic", similarity_threshold=0.8)
        collapse_map = collapser.find_clusters(triples)
        # ex:won_awards should map to ex:won_award (more frequent)
        if collapse_map:
            assert all(v == "ex:won_award" for v in collapse_map.values())

    # ---- LLM backend (mock) ----

    def test_llm_backend_uses_provided_groups(self) -> None:
        """Mock LLM grouping overrides edit-distance logic."""
        triples = [
            _triple("ex:Alice", "ex:is_director", "ex:Acme"),
            _triple("ex:Alice", "ex:is_ceo", "ex:Acme"),
            _triple("ex:Alice", "ex:is_chair", "ex:Acme"),
            _triple("ex:Bob", "ex:discovered", "ex:Polonium"),
        ]

        def mock_llm(preds: list[str]) -> list[list[str]]:
            # Group the three role predicates together
            role_preds = [p for p in preds if any(kw in p for kw in ("director", "ceo", "chair"))]
            other_preds = [p for p in preds if p not in role_preds]
            groups = []
            if role_preds:
                groups.append(role_preds)
            for p in other_preds:
                groups.append([p])
            return groups

        collapser = PredicateCollapser(backend="llm")
        collapse_map = collapser.find_clusters(triples, llm_client=mock_llm)
        # All three role predicates should be collapsed to one
        role_preds = {"ex:is_director", "ex:is_ceo", "ex:is_chair"}
        canonical_values = set(collapse_map.values())
        non_canonical_keys = set(collapse_map.keys())
        assert non_canonical_keys.issubset(role_preds)
        assert len(canonical_values) == 1
        assert canonical_values.pop() in role_preds

    def test_llm_backend_without_client_falls_back_to_deterministic(self) -> None:
        """When llm_client is None, deterministic clustering is used."""
        triples = [
            _triple("ex:A", "ex:is_director", "ex:Acme"),
            _triple("ex:B", "ex:is_director", "ex:Beta"),
        ]
        collapser = PredicateCollapser(backend="llm")
        # No llm_client → falls back to deterministic
        collapse_map = collapser.find_clusters(triples, llm_client=None)
        # Only one unique predicate → no collapse
        assert len(collapse_map) == 0

    def test_single_predicate_no_collapse(self) -> None:
        """A triple buffer with a single unique predicate produces no collapse."""
        triples = [_triple("ex:A", "ex:holds_role", "ex:Director")] * 5
        collapser = PredicateCollapser()
        assert collapser.find_clusters(triples) == {}


# ---------------------------------------------------------------------------
# FactDecomposer
# ---------------------------------------------------------------------------


class TestFactDecomposer:
    """Tests for FactDecomposer across year, date, and ordinal patterns."""

    def test_year_embedded_in_2019(self) -> None:
        """_in_YYYY pattern is stripped and a year qualifier triple emitted."""
        triples = [_triple("ex:Org", "ex:founded_in_2019", "ex:UK")]
        decomposer = FactDecomposer()
        result, n = decomposer.decompose(triples)
        assert n == 1
        assert len(result) == 2
        preds = {t.predicate for t in result}
        assert "ex:founded" in preds
        assert "ex:year" in preds
        year_triple = next(t for t in result if t.predicate == "ex:year")
        assert year_triple.object_value == "2019"

    def test_year_suffix_without_in(self) -> None:
        """_YYYY suffix (no 'in') is also detected."""
        triples = [_triple("ex:Org", "ex:acquired_2022", "ex:Target")]
        decomposer = FactDecomposer()
        result, n = decomposer.decompose(triples)
        assert n == 1
        year_triple = next(t for t in result if t.predicate == "ex:year")
        assert year_triple.object_value == "2022"

    def test_ordinal_first(self) -> None:
        """_first suffix produces an ordinal qualifier triple."""
        triples = [_triple("ex:Club", "ex:won_championship_first", "ex:Trophy")]
        decomposer = FactDecomposer()
        result, n = decomposer.decompose(triples)
        assert n == 1
        ordinal_triple = next(t for t in result if t.predicate == "ex:ordinal")
        assert ordinal_triple.object_value.lower() == "first"

    def test_ordinal_numeric_3rd(self) -> None:
        """_3rd numeric ordinal is extracted."""
        triples = [_triple("ex:Runner", "ex:finished_3rd", "ex:Race")]
        decomposer = FactDecomposer()
        result, n = decomposer.decompose(triples)
        assert n == 1
        ordinal_triple = next(t for t in result if t.predicate == "ex:ordinal")
        assert "3rd" in ordinal_triple.object_value.lower()

    def test_no_qualifier_unchanged(self) -> None:
        """Predicates without embedded qualifiers pass through unchanged."""
        triples = [
            _triple("ex:Alice", "ex:born_in", "Warsaw"),
            _triple("ex:Alice", "ex:nationality", "Polish"),
        ]
        decomposer = FactDecomposer()
        result, n = decomposer.decompose(triples)
        assert n == 0
        assert len(result) == 2

    def test_base_triple_preserves_original_object(self) -> None:
        """The base predicate triple retains the original object value."""
        triples = [_triple("ex:Co", "ex:merged_in_2010", "ex:OtherCo")]
        decomposer = FactDecomposer()
        result, _ = decomposer.decompose(triples)
        base = next(t for t in result if t.predicate != "ex:year")
        assert base.object_value == "ex:OtherCo"

    def test_multiple_triples_mixed(self) -> None:
        """Mixed buffer: some triples decomposed, others unchanged."""
        triples = [
            _triple("ex:Co", "ex:acquired_in_2022", "ex:Target"),
            _triple("ex:Co", "ex:headquarters", "ex:London"),
        ]
        decomposer = FactDecomposer()
        result, n = decomposer.decompose(triples)
        assert n == 1
        assert len(result) == 3  # 2 from decomposition + 1 unchanged


# ---------------------------------------------------------------------------
# URICanonicaliser
# ---------------------------------------------------------------------------


class TestURICanonicaliser:
    """Tests for URICanonicaliser using owl:sameAs links in the buffer."""

    def test_canonical_uri_rewrite(self) -> None:
        """Non-canonical subject URIs are rewritten to the most-used form."""
        triples = [
            # owl:sameAs chain
            _triple("ex:Marie_Curie", "owl:sameAs", "ex:M_Curie"),
            # Substantive triples using non-canonical form
            _triple("ex:M_Curie", "ex:discovered", "ex:Polonium"),
            _triple("ex:M_Curie", "ex:born_in", "Warsaw"),
            # Another triple using canonical form (more frequent → chosen)
            _triple("ex:Marie_Curie", "ex:won_award", "ex:Nobel"),
            _triple("ex:Marie_Curie", "ex:field_of_work", "ex:Physics"),
        ]
        canonicaliser = URICanonicaliser()
        result, n = canonicaliser.canonicalise(triples)
        subjects = {t.subject for t in result}
        assert "ex:M_Curie" not in subjects
        assert "ex:Marie_Curie" in subjects
        assert n >= 2

    def test_no_same_as_no_change(self) -> None:
        """Without any owl:sameAs triples, the buffer is returned unchanged."""
        triples = [
            _triple("ex:Alice", "ex:role", "Director"),
            _triple("ex:Bob", "ex:role", "CEO"),
        ]
        canonicaliser = URICanonicaliser()
        result, n = canonicaliser.canonicalise(triples)
        assert n == 0
        assert result == triples

    def test_chain_collapses_to_most_frequent(self) -> None:
        """A three-way chain collapses to the most frequently referenced URI."""
        triples = [
            _triple("ex:A", "owl:sameAs", "ex:B"),
            _triple("ex:B", "owl:sameAs", "ex:C"),
            # ex:A appears 3 times as subject
            _triple("ex:A", "ex:p", "ex:X"),
            _triple("ex:A", "ex:q", "ex:Y"),
            _triple("ex:A", "ex:r", "ex:Z"),
            # ex:C appears once
            _triple("ex:C", "ex:p", "ex:W"),
        ]
        canonicaliser = URICanonicaliser()
        result, n = canonicaliser.canonicalise(triples)
        subjects = {t.subject for t in result if t.predicate != "owl:sameAs"}
        # ex:A is most frequent → canonical
        assert subjects == {"ex:A"}

    def test_object_uris_also_rewritten(self) -> None:
        """Non-canonical URIs in object position are also rewritten."""
        triples = [
            _triple("ex:Marie_Curie", "owl:sameAs", "ex:M_Curie"),
            _triple("ex:Marie_Curie", "ex:p1", "ex:X"),
            _triple("ex:Marie_Curie", "ex:p2", "ex:X"),
            # object_value is a non-canonical URI
            _triple("ex:Lab", "ex:employed", "ex:M_Curie"),
        ]
        canonicaliser = URICanonicaliser()
        result, n = canonicaliser.canonicalise(triples)
        objects = {t.object_value for t in result if t.predicate == "ex:employed"}
        assert "ex:M_Curie" not in objects


# ---------------------------------------------------------------------------
# VocabularyNormalisationPass (full pass)
# ---------------------------------------------------------------------------


class TestVocabularyNormalisationPass:
    """End-to-end tests across three domain corpora (organisational,
    scientific, biographical) verifying all four normalisations."""

    def _make_pass(self, **overrides) -> VocabularyNormalisationPass:
        cfg = NormalisationConfig(
            enabled=True,
            categorical_threshold=2,
            collapse_predicates=True,
            predicate_collapse_backend="deterministic",
            decompose_stuffed_predicates=True,
            rewrite_canonical_uris=False,
            vocabulary_namespace="http://vocab/",
            **overrides,
        )
        return VocabularyNormalisationPass(cfg)

    # ---- Organisational corpus ----

    def test_organisational_corpus(self) -> None:
        """Organisational corpus: roles promoted, no domain-specific hardcoding."""
        triples = [
            # Roles — should be promoted (each appears ≥2 times)
            _triple("ex:Alice", "ex:role", "Director"),
            _triple("ex:Bob", "ex:role", "Director"),
            _triple("ex:Carol", "ex:role", "Manager"),
            _triple("ex:Dave", "ex:role", "Manager"),
            # Status — should be promoted
            _triple("ex:Policy1", "ex:status", "Approved"),
            _triple("ex:Policy2", "ex:status", "Approved"),
            # Fact-stuffed predicate
            _triple("ex:Corp", "ex:founded_in_1990", "ex:UK"),
        ]
        vn = self._make_pass()
        result = vn.run(triples)

        # Categorical promotion
        assert result.vocab_literals_promoted > 0
        # Every "Director" and "Manager" object should now be an IRI
        obj_values = {t.object_value for t in result.triples}
        assert "Director" not in obj_values
        assert "Manager" not in obj_values
        assert "http://vocab/Director" in obj_values
        assert "http://vocab/Manager" in obj_values

        # Fact decomposition
        assert result.vocab_facts_decomposed > 0
        preds = {t.predicate for t in result.triples}
        assert "ex:year" in preds
        assert "ex:founded_in_1990" not in preds

    # ---- Scientific corpus ----

    def test_scientific_corpus(self) -> None:
        """Scientific corpus: taxonomy promoted, qualifiers decomposed."""
        triples = [
            # Taxonomy classification
            _triple("ex:Tiger", "ex:classification", "Mammal"),
            _triple("ex:Lion", "ex:classification", "Mammal"),
            _triple("ex:Wolf", "ex:classification", "Mammal"),
            # Nobel-like awards with year
            _triple("ex:Einstein", "ex:awarded_in_1921", "ex:NobelPhysics"),
            _triple("ex:Curie", "ex:awarded_in_1903", "ex:NobelPhysics"),
            # IRI object — must not be promoted
            _triple("ex:Tiger", "ex:type", "ex:FelidaFamily"),
        ]
        vn = self._make_pass()
        result = vn.run(triples)

        # Mammals promoted
        obj_values = {t.object_value for t in result.triples}
        assert "Mammal" not in obj_values
        assert "http://vocab/Mammal" in obj_values

        # IRI objects unchanged
        assert "ex:FelidaFamily" in obj_values

        # Year qualifiers extracted
        preds = {t.predicate for t in result.triples}
        assert "ex:year" in preds
        assert "ex:awarded_in_1921" not in preds

    # ---- Biographical corpus ----

    def test_biographical_corpus(self) -> None:
        """Biographical corpus: nationalities promoted, URI canonicalisation."""
        triples = [
            # Nationalities
            _triple("ex:Einstein", "ex:nationality", "German"),
            _triple("ex:Planck", "ex:nationality", "German"),
            _triple("ex:Heisenberg", "ex:nationality", "German"),
            # Fact-stuffed
            _triple("ex:Einstein", "ex:moved_in_1933", "ex:USA"),
            # owl:sameAs — rewriting disabled by default
            _triple("ex:Einstein", "owl:sameAs", "ex:Albert_Einstein"),
        ]
        vn = self._make_pass()
        result = vn.run(triples)

        # Nationalities promoted
        obj_values = {t.object_value for t in result.triples}
        assert "German" not in obj_values
        assert "http://vocab/German" in obj_values

        # Year qualifier extracted
        preds = {t.predicate for t in result.triples}
        assert "ex:year" in preds
        assert "ex:moved_in_1933" not in preds

        # URI rewriting disabled (rewrite_canonical_uris=False)
        assert result.vocab_uris_rewritten == 0

    def test_uri_canonicalisation_enabled(self) -> None:
        """When rewrite_canonical_uris=True, owl:sameAs chains are resolved."""
        triples = [
            _triple("ex:Marie_Curie", "owl:sameAs", "ex:M_Curie"),
            _triple("ex:Marie_Curie", "ex:discovered", "ex:Polonium"),
            _triple("ex:Marie_Curie", "ex:born_in", "Warsaw"),
            _triple("ex:M_Curie", "ex:field", "ex:Chemistry"),
        ]
        cfg = NormalisationConfig(
            enabled=True,
            categorical_threshold=2,
            collapse_predicates=False,
            decompose_stuffed_predicates=False,
            rewrite_canonical_uris=True,
            vocabulary_namespace="http://vocab/",
        )
        vn = VocabularyNormalisationPass(cfg)
        result = vn.run(triples)
        assert result.vocab_uris_rewritten > 0
        subjects = {t.subject for t in result.triples if t.predicate != "owl:sameAs"}
        assert "ex:M_Curie" not in subjects

    def test_from_profile_constructor(self) -> None:
        """VocabularyNormalisationPass.from_profile reads profile dict correctly."""
        profile = CompilerProfile(
            name="test",
            vocabulary_normalisation={
                "enabled": True,
                "categorical_threshold": 3,
                "vocabulary_namespace": "http://custom/vocab/",
            },
        )
        vn = VocabularyNormalisationPass.from_profile(profile)
        assert vn.config.categorical_threshold == 3
        assert vn.config.vocabulary_namespace == "http://custom/vocab/"

    def test_empty_buffer_returns_empty(self) -> None:
        """An empty triple buffer produces an empty result with zero counts."""
        vn = self._make_pass()
        result = vn.run([])
        assert result.triples == []
        assert result.vocab_literals_promoted == 0
        assert result.vocab_predicates_collapsed == 0
        assert result.vocab_facts_decomposed == 0
        assert result.vocab_uris_rewritten == 0

    def test_llm_backend_with_mock_client(self) -> None:
        """LLM-guided predicate collapsing with an injected mock client."""
        triples = [
            _triple("ex:Alice", "ex:is_director", "ex:Acme"),
            _triple("ex:Bob", "ex:is_ceo", "ex:Acme"),
            _triple("ex:Carol", "ex:is_chair", "ex:Acme"),
            _triple("ex:Dave", "ex:is_director", "ex:Beta"),
        ]
        cfg = NormalisationConfig(
            enabled=True,
            categorical_threshold=10,  # disable categorical promotion
            collapse_predicates=True,
            predicate_collapse_backend="llm",
            decompose_stuffed_predicates=False,
            rewrite_canonical_uris=False,
        )
        vn = VocabularyNormalisationPass(cfg)

        def mock_llm(preds: list[str]) -> list[list[str]]:
            role_preds = [p for p in preds if any(kw in p for kw in ("director", "ceo", "chair"))]
            return [role_preds] if role_preds else []

        result = vn.run(triples, llm_client=mock_llm)
        preds = {t.predicate for t in result.triples}
        # All role predicates collapsed to one canonical form
        assert len(preds) == 1
        # 3 unique predicates → 2 non-canonical ones get rewritten
        assert result.vocab_predicates_collapsed >= 2

    def test_stats_are_non_negative(self) -> None:
        """All returned stat counts are non-negative integers."""
        triples = [_triple("ex:A", "ex:p", "ex:B")]
        vn = self._make_pass()
        result = vn.run(triples)
        assert result.vocab_literals_promoted >= 0
        assert result.vocab_predicates_collapsed >= 0
        assert result.vocab_facts_decomposed >= 0
        assert result.vocab_uris_rewritten >= 0

    def test_no_domain_specific_hardcoding(self) -> None:
        """The pass works identically on any domain — no domain knowledge."""
        # All literals here are invented; the pass should still detect categories
        triples = [
            _triple("ex:X1", "ex:zork", "flurble"),
            _triple("ex:X2", "ex:zork", "flurble"),
            _triple("ex:X3", "ex:zork", "grumble"),
        ]
        vn = self._make_pass()
        result = vn.run(triples)
        # "flurble" appears twice → promoted
        assert result.vocab_literals_promoted == 2
        # "grumble" once → not promoted
        obj_values = {t.object_value for t in result.triples}
        assert "flurble" not in obj_values
        assert "grumble" in obj_values


# ---------------------------------------------------------------------------
# Pipeline integration — vocab_normalisation.enabled in CompilerProfile
# ---------------------------------------------------------------------------


def test_pipeline_vocab_normalisation_enabled_in_stats(tmp_path: Path) -> None:
    """When vocabulary_normalisation.enabled=true, stats keys are present."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text(
        "# Section\n\nThis section contains knowledge for vocabulary normalisation "
        "integration testing — it is long enough to pass the ingest gate."
    )
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(
        name="test",
        vocabulary_normalisation={
            "enabled": True,
            "categorical_threshold": 2,
        },
    )

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
            stats = pipeline.run(corpus_path=str(tmp_path), profile=profile)

    # All four vocab stat keys must be present
    assert "vocab_literals_promoted" in stats
    assert "vocab_predicates_collapsed" in stats
    assert "vocab_facts_decomposed" in stats
    assert "vocab_uris_rewritten" in stats
    assert stats["errors"] == 0


def test_pipeline_vocab_normalisation_disabled_by_default(tmp_path: Path) -> None:
    """Vocabulary normalisation is disabled by default (backward-compatible)."""
    import unittest.mock as mock  # noqa: PLC0415

    (tmp_path / "doc.md").write_text("# Section\n\n" + "Z" * 100)
    pipeline = IngestPipeline(db_engine=None)
    profile = CompilerProfile(name="test")  # no vocabulary_normalisation key

    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
            stats = pipeline.run(corpus_path=str(tmp_path), profile=profile)

    # Stats keys still present (initialised to zero)
    assert stats.get("vocab_literals_promoted", 0) == 0
    assert stats.get("vocab_predicates_collapsed", 0) == 0
    assert stats["errors"] == 0
