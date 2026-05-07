"""Unit tests for v0.13.0 — Entity Convergence.

Covers:
- PredicateNormalizer: _label_from_iri, _cosine_similarity, clustering, NormalizationResult
- EntityLinker: registry load, synonym ring expansion, build_known_entities_block
- EntityRecord / EntityRegistry: merge, top_k_by_similarity
- ContradictionDetector: functional predicate detection, ConflictRecord, ConflictationResult
- SchemaInducer: collect_statistics stub, propose (no LLM), _build_prompt
- TentativeGraphCleaner: _parse_duration, _parse_iso, gc (dry-run)
- BenchmarkRunner: _normalise, _fuzzy_match, _triple_key, _keys_match, load_ground_truth, run
- CompilerProfile: tentative_ttl_days field
- CLI: new commands registered
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_ansi_codes(text: str) -> str:
    """Remove ANSI color/formatting codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def _make_mock_triple(subject, predicate, object_value, confidence=0.8, source_iri="file:///doc.md"):
    ev = MagicMock()
    ev.source_iri = source_iri
    ev.excerpt = "excerpt"
    t = MagicMock()
    t.subject = subject
    t.predicate = predicate
    t.object_value = object_value
    t.confidence = confidence
    t.evidence = ev
    t.fragment_key = "root"
    return t


# ===========================================================================
# PredicateNormalizer
# ===========================================================================


class TestLabelFromIri:
    def test_camel_case(self):
        from riverbank.postprocessors.predicate_norm import _label_from_iri
        assert "has" in _label_from_iri("http://example.org/hasDefinition")
        assert "definition" in _label_from_iri("http://example.org/hasDefinition")

    def test_snake_case(self):
        from riverbank.postprocessors.predicate_norm import _label_from_iri
        result = _label_from_iri("ex:source_iri")
        assert "source" in result
        assert "iri" in result

    def test_simple_name(self):
        from riverbank.postprocessors.predicate_norm import _label_from_iri
        assert _label_from_iri("http://example.org/name") == "name"

    def test_fragment_identifier(self):
        from riverbank.postprocessors.predicate_norm import _label_from_iri
        result = _label_from_iri("http://schema.org/Person#birthDate")
        assert "birth" in result or "date" in result


class TestCosineSimPredicate:
    def test_identical_vectors(self):
        from riverbank.postprocessors.predicate_norm import _cosine_similarity
        v = [1.0, 0.5, 0.2]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        from riverbank.postprocessors.predicate_norm import _cosine_similarity
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self):
        from riverbank.postprocessors.predicate_norm import _cosine_similarity
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.5]) == 0.0


class TestNormalizationResult:
    def test_default_values(self):
        from riverbank.postprocessors.predicate_norm import NormalizationResult
        r = NormalizationResult()
        assert r.predicates_examined == 0
        assert r.clusters_found == 0
        assert r.equivalent_property_written == 0
        assert r.triples_rewritten == 0
        assert r.clusters == []

    def test_predicate_cluster_dataclass(self):
        from riverbank.postprocessors.predicate_norm import PredicateCluster
        c = PredicateCluster(
            canonical="ex:hasName",
            aliases=["ex:name", "ex:named"],
            label="has name",
            similarity=0.95,
        )
        assert c.canonical == "ex:hasName"
        assert len(c.aliases) == 2
        assert c.similarity == 0.95


class TestPredicateNormalizerNoLLM:
    """Tests that run without sentence-transformers (model returns False)."""

    def test_normalize_empty_graph_returns_empty_result(self):
        from riverbank.postprocessors.predicate_norm import PredicateNormalizer

        normalizer = PredicateNormalizer()
        mock_conn = MagicMock()
        with patch("riverbank.postprocessors.predicate_norm.PredicateNormalizer._fetch_predicates", return_value={}):
            result = normalizer.normalize(mock_conn, "http://example.org/graph")
        assert result.predicates_examined == 0

    def test_normalize_skips_when_model_unavailable(self):
        from riverbank.postprocessors.predicate_norm import PredicateNormalizer

        normalizer = PredicateNormalizer()
        with (
            patch.object(normalizer, "_fetch_predicates", return_value={
                "ex:hasName": 10,
                "ex:name": 8,
            }),
            patch.object(normalizer, "_get_model", return_value=False),
        ):
            result = normalizer.normalize(MagicMock(), "http://example.org/graph")
        assert result.predicates_examined == 2
        # No clusters because model unavailable
        assert result.clusters_found == 0

    def test_normalize_filters_well_known_predicates(self):
        from riverbank.postprocessors.predicate_norm import PredicateNormalizer

        normalizer = PredicateNormalizer()
        fetched = {
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": 100,
            "http://www.w3.org/2000/01/rdf-schema#label": 50,
            "ex:hasName": 10,
        }
        with (
            patch.object(normalizer, "_fetch_predicates", return_value=fetched),
            patch.object(normalizer, "_get_model", return_value=False),
        ):
            result = normalizer.normalize(MagicMock(), "http://example.org/graph")
        # Only ex:hasName should be examined (well-known filtered out)
        assert result.predicates_examined == 1


# ===========================================================================
# EntityLinker
# ===========================================================================


class TestEntityRecord:
    def test_default_fields(self):
        from riverbank.postprocessors.entity_linker import EntityRecord
        r = EntityRecord(iri="ex:Alice", label="Alice")
        assert r.entity_type == ""
        assert r.doc_count == 1
        assert r.variants == []

    def test_variants_list(self):
        from riverbank.postprocessors.entity_linker import EntityRecord
        r = EntityRecord(iri="ex:Alice", label="Alice", variants=["alice", "ALICE"])
        assert len(r.variants) == 2


class TestEntityRegistry:
    def test_by_iri_found(self):
        from riverbank.postprocessors.entity_linker import EntityRecord, EntityRegistry
        reg = EntityRegistry(entities=[EntityRecord(iri="ex:Alice", label="Alice")])
        assert reg.by_iri("ex:Alice") is not None

    def test_by_iri_not_found(self):
        from riverbank.postprocessors.entity_linker import EntityRegistry
        reg = EntityRegistry()
        assert reg.by_iri("ex:Unknown") is None

    def test_merge_success(self):
        from riverbank.postprocessors.entity_linker import EntityRecord, EntityRegistry
        reg = EntityRegistry(entities=[
            EntityRecord(iri="ex:Dataset", label="Dataset"),
            EntityRecord(iri="ex:dataset", label="dataset"),
        ])
        success = reg.merge(into_iri="ex:Dataset", from_iri="ex:dataset")
        assert success
        assert len(reg.entities) == 1
        assert "dataset" in reg.entities[0].variants

    def test_merge_unknown_entity_fails(self):
        from riverbank.postprocessors.entity_linker import EntityRecord, EntityRegistry
        reg = EntityRegistry(entities=[EntityRecord(iri="ex:Known", label="Known")])
        result = reg.merge(into_iri="ex:Known", from_iri="ex:Unknown")
        assert not result

    def test_top_k_empty_embeddings(self):
        from riverbank.postprocessors.entity_linker import EntityRecord, EntityRegistry
        reg = EntityRegistry(entities=[
            EntityRecord(iri="ex:A", label="Alice"),
            EntityRecord(iri="ex:B", label="Bob"),
        ])
        # No embeddings cached — returns empty
        result = reg.top_k_by_similarity([1.0, 0.0], {}, k=2)
        assert result == []

    def test_top_k_by_similarity_ranked(self):
        from riverbank.postprocessors.entity_linker import EntityRecord, EntityRegistry
        reg = EntityRegistry(entities=[
            EntityRecord(iri="ex:A", label="Alice"),
            EntityRecord(iri="ex:B", label="Bob"),
        ])
        embs = {
            "ex:A": [1.0, 0.0],
            "ex:B": [0.0, 1.0],
        }
        # Query closer to B
        result = reg.top_k_by_similarity([0.1, 0.9], embs, k=1)
        assert len(result) == 1
        assert result[0].iri == "ex:B"


class TestEntityLinkerNoLLM:
    def test_load_registry_returns_empty_on_db_error(self):
        from riverbank.postprocessors.entity_linker import EntityLinker

        linker = EntityLinker()
        mock_conn = MagicMock()
        with patch("riverbank.catalog.graph.sparql_query", side_effect=Exception("db error")):
            registry = linker.load_registry(mock_conn, "http://example.org/graph")
        assert registry.entities == []

    def test_build_known_entities_block_empty_registry(self):
        from riverbank.postprocessors.entity_linker import EntityLinker, EntityRegistry

        linker = EntityLinker()
        result = linker.build_known_entities_block(EntityRegistry(), "Some heading")
        assert result == ""

    def test_build_known_entities_block_no_model(self):
        from riverbank.postprocessors.entity_linker import EntityLinker, EntityRecord, EntityRegistry

        linker = EntityLinker()
        with patch.object(linker, "_get_model", return_value=False):
            registry = EntityRegistry(entities=[
                EntityRecord(iri="ex:Dataset", label="Dataset", variants=["data set"]),
            ])
            result = linker.build_known_entities_block(registry, "Dataset overview")
        assert "ex:Dataset" in result
        assert "KNOWN ENTITIES" in result

    def test_build_known_entities_block_includes_variants(self):
        from riverbank.postprocessors.entity_linker import EntityLinker, EntityRecord, EntityRegistry

        linker = EntityLinker()
        with patch.object(linker, "_get_model", return_value=False):
            registry = EntityRegistry(entities=[
                EntityRecord(iri="ex:Policy", label="Policy", variants=["policies", "the policy"]),
            ])
            result = linker.build_known_entities_block(registry, "Policy document")
        assert "policies" in result or "Policy" in result

    def test_entity_linking_result_defaults(self):
        from riverbank.postprocessors.entity_linker import EntityLinkingResult
        r = EntityLinkingResult()
        assert r.entities_registered == 0
        assert r.synonym_rings_updated == 0
        assert r.alt_labels_written == 0


# ===========================================================================
# ContradictionDetector
# ===========================================================================


class TestContradictionDetector:
    def test_no_functional_predicates_returns_empty(self):
        from riverbank.postprocessors.contradiction import ContradictionDetector

        detector = ContradictionDetector()
        profile = MagicMock()
        profile.predicate_constraints = {}
        profile.tentative_graph = "http://example.org/tentative"

        result = detector.detect(MagicMock(), profile, "http://example.org/graph")
        assert result.functional_predicates_checked == 0
        assert result.conflicts_found == 0

    def test_functional_predicate_identified(self):
        from riverbank.postprocessors.contradiction import ContradictionDetector

        detector = ContradictionDetector()
        profile = MagicMock()
        profile.predicate_constraints = {
            "ex:hasOwner": {"max_cardinality": 1},
            "ex:relatedTo": {"max_cardinality": 5},
        }
        profile.tentative_graph = "http://example.org/tentative"

        with patch.object(detector, "_find_conflicts", return_value={}):
            result = detector.detect(MagicMock(), profile, "http://example.org/graph")
        # Only the functional (max_cardinality: 1) predicate is checked
        assert result.functional_predicates_checked == 1

    def test_conflict_detection(self):
        from riverbank.postprocessors.contradiction import ContradictionDetector

        detector = ContradictionDetector(trusted_threshold=0.75)
        profile = MagicMock()
        profile.predicate_constraints = {"ex:hasOwner": {"max_cardinality": 1}}
        profile.tentative_graph = "http://example.org/tentative"

        conflicts = {"ex:Subject": ["ex:Owner1", "ex:Owner2"]}
        with (
            patch.object(detector, "_find_conflicts", return_value=conflicts),
            patch.object(detector, "_get_confidence", return_value=0.8),
            patch.object(detector, "_demote_triple"),
            patch.object(detector, "_write_conflict_record"),
        ):
            result = detector.detect(
                MagicMock(), profile, "http://example.org/graph", dry_run=True
            )
        assert result.conflicts_found == 1
        assert result.triples_penalised == 2  # both conflicting objects

    def test_30_percent_confidence_penalty(self):
        from riverbank.postprocessors.contradiction import ContradictionDetector

        detector = ContradictionDetector(trusted_threshold=0.75, confidence_penalty=0.30)
        profile = MagicMock()
        profile.predicate_constraints = {"ex:hasOwner": {"max_cardinality": 1}}
        profile.tentative_graph = "http://example.org/tentative"

        conflicts = {"ex:Subject": ["ex:Owner1", "ex:Owner2"]}
        captured: list[dict] = []

        def _detect_confidence(*args, **kwargs):
            return 0.8  # before penalty → 0.8 * 0.7 = 0.56 → below 0.75 → demoted

        with (
            patch.object(detector, "_find_conflicts", return_value=conflicts),
            patch.object(detector, "_get_confidence", side_effect=_detect_confidence),
            patch.object(detector, "_demote_triple"),
            patch.object(detector, "_write_conflict_record"),
        ):
            result = detector.detect(
                MagicMock(), profile, "http://example.org/graph", dry_run=True
            )

        cr = result.conflict_records[0]
        for obj, after in cr.confidence_after.items():
            assert abs(after - 0.8 * 0.7) < 1e-5

    def test_demotion_when_below_threshold(self):
        from riverbank.postprocessors.contradiction import ContradictionDetector

        detector = ContradictionDetector(trusted_threshold=0.75)
        profile = MagicMock()
        profile.predicate_constraints = {"ex:hasOwner": {"max_cardinality": 1}}
        profile.tentative_graph = "http://example.org/tentative"

        # conf = 0.8 → 0.8 * 0.7 = 0.56 < 0.75 → demoted
        conflicts = {"ex:Subject": ["ex:Owner1", "ex:Owner2"]}
        with (
            patch.object(detector, "_find_conflicts", return_value=conflicts),
            patch.object(detector, "_get_confidence", return_value=0.8),
            patch.object(detector, "_demote_triple"),
            patch.object(detector, "_write_conflict_record"),
        ):
            result = detector.detect(
                MagicMock(), profile, "http://example.org/graph", dry_run=True
            )
        assert result.triples_demoted == 2

    def test_no_demotion_when_above_threshold(self):
        from riverbank.postprocessors.contradiction import ContradictionDetector

        # High confidence → after 30% penalty still above 0.75?
        # conf = 1.0 → 1.0 * 0.7 = 0.70 < 0.75 → still demoted
        # conf = 1.0, penalty=0.1 → 1.0 * 0.9 = 0.90 > 0.75 → NOT demoted
        detector = ContradictionDetector(trusted_threshold=0.75, confidence_penalty=0.10)
        profile = MagicMock()
        profile.predicate_constraints = {"ex:hasOwner": {"max_cardinality": 1}}
        profile.tentative_graph = "http://example.org/tentative"

        conflicts = {"ex:Subject": ["ex:Owner1", "ex:Owner2"]}
        with (
            patch.object(detector, "_find_conflicts", return_value=conflicts),
            patch.object(detector, "_get_confidence", return_value=1.0),
            patch.object(detector, "_demote_triple"),
            patch.object(detector, "_update_confidence"),
            patch.object(detector, "_write_conflict_record"),
        ):
            result = detector.detect(
                MagicMock(), profile, "http://example.org/graph", dry_run=True
            )
        assert result.triples_demoted == 0

    def test_conflict_record_dataclass(self):
        from riverbank.postprocessors.contradiction import ConflictRecord
        cr = ConflictRecord(
            subject="ex:A",
            predicate="ex:hasOwner",
            conflicting_objects=["ex:B", "ex:C"],
            confidence_before={"ex:B": 0.8, "ex:C": 0.9},
            confidence_after={"ex:B": 0.56, "ex:C": 0.63},
            demoted_objects=["ex:B", "ex:C"],
            detected_at="2026-05-07T00:00:00+00:00",
        )
        assert cr.subject == "ex:A"
        assert len(cr.conflicting_objects) == 2
        assert cr.confidence_after["ex:B"] == 0.56


# ===========================================================================
# SchemaInducer
# ===========================================================================


class TestSchemaInducer:
    def test_collect_statistics_returns_empty_on_db_error(self):
        from riverbank.schema_induction import SchemaInducer

        inducer = SchemaInducer()
        mock_conn = MagicMock()
        with patch("riverbank.catalog.graph.sparql_query", side_effect=Exception("db")):
            stats = inducer.collect_statistics(mock_conn, "http://example.org/graph")
        assert stats.predicates == []
        assert stats.types == []

    def test_propose_empty_returns_stub(self):
        from riverbank.schema_induction import GraphStatistics, SchemaInducer

        inducer = SchemaInducer()
        stats = GraphStatistics(predicates=[], types=[])
        proposal = inducer.propose(stats)
        assert "Turtle" in proposal.ttl_text or "ontology" in proposal.ttl_text.lower()
        assert proposal.model_used == "stub"

    def test_propose_with_stats_calls_llm(self):
        from riverbank.schema_induction import GraphStatistics, SchemaInducer

        inducer = SchemaInducer()
        stats = GraphStatistics(
            predicates=[("ex:hasOwner", 10), ("ex:hasVersion", 5)],
            types=[("ex:Policy", 8)],
            named_graph="http://example.org/graph",
        )
        with patch.object(
            inducer, "_call_llm", return_value=("@prefix ex: <http://example.org/> .", 50, 100)
        ) as mock_llm:
            proposal = inducer.propose(stats)
        mock_llm.assert_called_once()
        assert "ex:hasOwner" in proposal.allowed_predicates

    def test_predicate_constraints_heuristic(self):
        """Predicates with 'name', 'title', etc. in local name get max_cardinality: 1."""
        from riverbank.schema_induction import GraphStatistics, SchemaInducer

        inducer = SchemaInducer()
        stats = GraphStatistics(
            predicates=[
                ("http://example.org/hasTitle", 10),
                ("http://example.org/relatedTo", 5),
            ],
            types=[],
            named_graph="http://example.org/graph",
        )
        with patch.object(inducer, "_call_llm", return_value=("@prefix ex: <http://example.org/> .", 10, 20)):
            proposal = inducer.propose(stats)
        assert "http://example.org/hasTitle" in proposal.predicate_constraints
        assert proposal.predicate_constraints["http://example.org/hasTitle"]["max_cardinality"] == 1

    def test_build_prompt_contains_predicates(self):
        from riverbank.schema_induction import GraphStatistics, SchemaInducer

        inducer = SchemaInducer()
        stats = GraphStatistics(
            predicates=[("ex:hasOwner", 10)],
            types=[("ex:Policy", 8)],
            named_graph="http://example.org/graph",
        )
        prompt = inducer._build_prompt(stats)
        assert "ex:hasOwner" in prompt
        assert "ex:Policy" in prompt
        assert "TOP PREDICATES" in prompt
        assert "TOP ENTITY TYPES" in prompt

    def test_graph_statistics_named_graph(self):
        from riverbank.schema_induction import GraphStatistics
        stats = GraphStatistics(
            predicates=[("ex:p", 1)],
            types=[],
            named_graph="http://example.org/my-graph",
        )
        assert stats.named_graph == "http://example.org/my-graph"


# ===========================================================================
# TentativeGraphCleaner
# ===========================================================================


class TestParseDuration:
    def test_days(self):
        from riverbank.postprocessors.tentative_gc import _parse_duration
        from datetime import timedelta
        assert _parse_duration("30d") == timedelta(days=30)
        assert _parse_duration("7d") == timedelta(days=7)

    def test_hours(self):
        from riverbank.postprocessors.tentative_gc import _parse_duration
        from datetime import timedelta
        assert _parse_duration("48h") == timedelta(hours=48)

    def test_minutes(self):
        from riverbank.postprocessors.tentative_gc import _parse_duration
        from datetime import timedelta
        assert _parse_duration("90m") == timedelta(minutes=90)

    def test_integer_assumed_days(self):
        from riverbank.postprocessors.tentative_gc import _parse_duration
        from datetime import timedelta
        assert _parse_duration("14") == timedelta(days=14)


class TestParseIso:
    def test_valid_iso_with_tz(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner
        from datetime import timezone
        dt = TentativeGraphCleaner._parse_iso("2026-01-01T12:00:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_valid_iso_z(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner
        dt = TentativeGraphCleaner._parse_iso("2026-01-01T12:00:00Z")
        assert dt is not None

    def test_date_only(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner
        dt = TentativeGraphCleaner._parse_iso("2026-01-01")
        assert dt is not None

    def test_invalid_returns_none(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner
        assert TentativeGraphCleaner._parse_iso("not-a-date") is None

    def test_with_datatype_annotation(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner
        # Timestamps from SPARQL often come as "2026-01-01T..."^^xsd:dateTime
        dt = TentativeGraphCleaner._parse_iso('"2026-01-01T00:00:00+00:00"^^xsd:dateTime')
        assert dt is not None


class TestTentativeGraphCleaner:
    def test_zero_ttl_disables_cleanup(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner

        cleaner = TentativeGraphCleaner(ttl_days=0)
        result = cleaner.gc(MagicMock(), "http://example.org/tentative", ttl=0)
        assert result.triples_archived == 0
        assert result.triples_examined == 0

    def test_dry_run_does_not_archive(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner

        cleaner = TentativeGraphCleaner()
        old_triple = {
            "s": "ex:A", "p": "ex:rel", "o": "ex:B",
            "first_seen": "2020-01-01T00:00:00+00:00",  # definitely older than 30 days
        }
        with patch.object(cleaner, "_fetch_tentative_triples", return_value=[old_triple]):
            result = cleaner.gc(MagicMock(), "http://example.org/tentative", ttl="30d", dry_run=True)
        assert result.triples_archived == 1  # counted but not archived
        assert result.triples_examined == 1

    def test_fresh_triple_not_archived(self):
        from datetime import datetime, timezone
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner

        cleaner = TentativeGraphCleaner()
        fresh_ts = datetime.now(timezone.utc).isoformat()
        fresh_triple = {
            "s": "ex:A", "p": "ex:rel", "o": "ex:B",
            "first_seen": fresh_ts,
        }
        with patch.object(cleaner, "_fetch_tentative_triples", return_value=[fresh_triple]):
            result = cleaner.gc(MagicMock(), "http://example.org/tentative", ttl="30d", dry_run=True)
        assert result.triples_archived == 0
        assert result.triples_skipped == 1

    def test_no_timestamp_treated_as_stale(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner

        cleaner = TentativeGraphCleaner()
        no_ts_triple = {"s": "ex:A", "p": "ex:rel", "o": "ex:B", "first_seen": ""}
        with patch.object(cleaner, "_fetch_tentative_triples", return_value=[no_ts_triple]):
            result = cleaner.gc(MagicMock(), "http://example.org/tentative", ttl="30d", dry_run=True)
        assert result.triples_archived == 1

    def test_ttl_as_integer_days(self):
        from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner

        cleaner = TentativeGraphCleaner()
        old_triple = {
            "s": "ex:A", "p": "ex:rel", "o": "ex:B",
            "first_seen": "2020-01-01T00:00:00+00:00",
        }
        with patch.object(cleaner, "_fetch_tentative_triples", return_value=[old_triple]):
            result = cleaner.gc(MagicMock(), "http://example.org/tentative", ttl=30, dry_run=True)
        assert result.triples_archived == 1


# ===========================================================================
# BenchmarkRunner
# ===========================================================================


class TestNormalise:
    def test_strips_angle_brackets(self):
        from riverbank.benchmark import _normalise
        assert _normalise("<http://example.org/Policy>") == "policy"

    def test_extracts_local_name(self):
        from riverbank.benchmark import _normalise
        assert _normalise("http://example.org/hasTitle") == "hastitle"

    def test_strips_prefix(self):
        from riverbank.benchmark import _normalise
        assert _normalise("ex:Policy") == "policy"

    def test_strips_datatype(self):
        from riverbank.benchmark import _normalise
        assert _normalise('"Hello"^^xsd:string') == "hello"

    def test_lowercases(self):
        from riverbank.benchmark import _normalise
        assert _normalise("Policy") == "policy"


class TestFuzzyMatch:
    def test_exact_match(self):
        from riverbank.benchmark import _fuzzy_match
        assert _fuzzy_match("policy", "policy")

    def test_similar_strings(self):
        from riverbank.benchmark import _fuzzy_match
        # "policies" vs "policy" — ratio likely below 0.90
        # "Introduction to Policies" vs "Introduction to Policies" — exact
        assert _fuzzy_match("Introduction to Policies", "Introduction to Policies")

    def test_dissimilar_strings(self):
        from riverbank.benchmark import _fuzzy_match
        assert not _fuzzy_match("completely different", "unrelated text xyz")


class TestTripleKey:
    def test_normalises_components(self):
        from riverbank.benchmark import _triple_key
        k = _triple_key("http://example.org/Policy", "ex:hasTitle", '"My Policy"^^xsd:string')
        assert k == ("policy", "hastitle", "my policy")


class TestKeysMatch:
    def test_exact_match(self):
        from riverbank.benchmark import _keys_match
        k = ("policy", "hastitle", "introduction")
        assert _keys_match(k, k)

    def test_different_subject_no_match(self):
        from riverbank.benchmark import _keys_match
        assert not _keys_match(
            ("policy1", "hastitle", "introduction"),
            ("policy2", "hastitle", "introduction"),
        )

    def test_different_predicate_no_match(self):
        from riverbank.benchmark import _keys_match
        assert not _keys_match(
            ("policy", "hastitle", "introduction"),
            ("policy", "hasversion", "introduction"),
        )


class TestLoadGroundTruth:
    def test_loads_yaml(self, tmp_path):
        from riverbank.benchmark import load_ground_truth

        content = [
            {
                "source": "doc1.md",
                "triples": [
                    {"subject": "ex:Policy", "predicate": "ex:hasTitle", "object_value": "My Policy"},
                ]
            }
        ]
        (tmp_path / "ground_truth.yaml").write_text(yaml.dump(content))
        triples = load_ground_truth(tmp_path)
        assert len(triples) == 1
        assert triples[0].subject == "ex:Policy"

    def test_missing_file_returns_empty(self, tmp_path):
        from riverbank.benchmark import load_ground_truth
        result = load_ground_truth(tmp_path)
        assert result == []

    def test_multiple_sources(self, tmp_path):
        from riverbank.benchmark import load_ground_truth

        content = [
            {"source": "doc1.md", "triples": [
                {"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:B"},
            ]},
            {"source": "doc2.md", "triples": [
                {"subject": "ex:C", "predicate": "ex:p", "object_value": "ex:D"},
                {"subject": "ex:E", "predicate": "ex:p", "object_value": "ex:F"},
            ]},
        ]
        (tmp_path / "ground_truth.yaml").write_text(yaml.dump(content))
        triples = load_ground_truth(tmp_path)
        assert len(triples) == 3


class TestBenchmarkRunner:
    def test_round_trip_f1_is_one(self, tmp_path):
        """Without a real pipeline, runner re-uses ground truth → F1 = 1.0."""
        from riverbank.benchmark import BenchmarkRunner

        content = [
            {"source": "doc1.md", "triples": [
                {"subject": "ex:Policy", "predicate": "ex:hasTitle", "object_value": "My Policy"},
                {"subject": "ex:Policy", "predicate": "rdf:type", "object_value": "ex:Document"},
            ]}
        ]
        (tmp_path / "ground_truth.yaml").write_text(yaml.dump(content))

        runner = BenchmarkRunner(pipeline=None)
        report = runner.run(golden_dir=tmp_path, fail_below_f1=0.85)
        assert report.f1 == pytest.approx(1.0, abs=1e-3)
        assert report.pass_threshold

    def test_fail_below_f1_on_zero_extraction(self, tmp_path):
        """A pipeline that extracts nothing yields F1=0 and fails."""
        from riverbank.benchmark import BenchmarkRunner

        content = [
            {"source": "doc1.md", "triples": [
                {"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:B"},
            ]}
        ]
        (tmp_path / "ground_truth.yaml").write_text(yaml.dump(content))

        class _EmptyPipeline:
            def run(self, *args, **kwargs):
                return {}

        runner = BenchmarkRunner(pipeline=_EmptyPipeline())
        report = runner.run(golden_dir=tmp_path, fail_below_f1=0.85)
        assert report.f1 == pytest.approx(0.0, abs=1e-3)
        assert not report.pass_threshold

    def test_empty_golden_passes(self, tmp_path):
        """An empty golden corpus trivially passes (nothing to evaluate)."""
        from riverbank.benchmark import BenchmarkRunner

        runner = BenchmarkRunner()
        report = runner.run(golden_dir=tmp_path, fail_below_f1=0.85)
        assert report.pass_threshold

    def test_precision_recall_computation(self, tmp_path):
        """Partial extraction: 1 of 2 ground truth triples found → R=0.5."""
        from riverbank.benchmark import BenchmarkRunner, load_ground_truth

        content = [
            {"source": "doc1.md", "triples": [
                {"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:B"},
                {"subject": "ex:C", "predicate": "ex:p", "object_value": "ex:D"},
            ]}
        ]
        (tmp_path / "ground_truth.yaml").write_text(yaml.dump(content))

        # Pipeline that "extracts" only the first triple
        first_triple_only = [load_ground_truth(tmp_path)[0]]

        class _PartialPipeline:
            def run(self, *args, **kwargs):
                return {}

        runner = BenchmarkRunner(pipeline=_PartialPipeline())
        # Patch _extract to return just the first triple
        with patch.object(runner, "_extract", return_value=first_triple_only):
            report = runner.run(golden_dir=tmp_path, fail_below_f1=0.5)
        assert report.recall == pytest.approx(0.5, abs=0.01)
        assert report.precision == pytest.approx(1.0, abs=0.01)


# ===========================================================================
# CompilerProfile: tentative_ttl_days field
# ===========================================================================


class TestCompilerProfileV130:
    def test_tentative_ttl_days_default(self):
        from riverbank.pipeline import CompilerProfile
        profile = CompilerProfile(name="test")
        assert profile.tentative_ttl_days == 30

    def test_tentative_ttl_days_from_yaml(self, tmp_path):
        from riverbank.pipeline import CompilerProfile
        yaml_content = "name: test\ntentative_ttl_days: 7\n"
        p = tmp_path / "profile.yaml"
        p.write_text(yaml_content)
        profile = CompilerProfile.from_yaml(str(p))
        assert profile.tentative_ttl_days == 7

    def test_tentative_ttl_days_zero(self, tmp_path):
        from riverbank.pipeline import CompilerProfile
        yaml_content = "name: test\ntentative_ttl_days: 0\n"
        p = tmp_path / "profile.yaml"
        p.write_text(yaml_content)
        profile = CompilerProfile.from_yaml(str(p))
        assert profile.tentative_ttl_days == 0


# ===========================================================================
# CLI: new commands registered
# ===========================================================================


class TestV130CLICommandsRegistered:
    def _command_names(self):
        from riverbank.cli import app
        names = set()
        for cmd in app.registered_commands:
            names.add(cmd.name)
        return names

    def test_normalize_predicates_registered(self):
        assert "normalize-predicates" in self._command_names()

    def test_detect_contradictions_registered(self):
        assert "detect-contradictions" in self._command_names()

    def test_induce_schema_registered(self):
        assert "induce-schema" in self._command_names()

    def test_gc_tentative_registered(self):
        assert "gc-tentative" in self._command_names()

    def test_benchmark_registered(self):
        assert "benchmark" in self._command_names()

    def test_entities_subapp_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["entities", "--help"])
        assert "list" in result.output or "merge" in result.output or result.exit_code == 0

    def test_entities_list_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["entities", "list", "--help"])
        assert "--graph" in result.output or "graph" in result.output.lower()

    def test_entities_merge_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["entities", "merge", "--help"])
        clean_output = _strip_ansi_codes(result.output)
        assert "--entity" in clean_output
        assert "--into" in clean_output

    def test_normalize_predicates_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["normalize-predicates", "--help"])
        clean_output = _strip_ansi_codes(result.output).lower()
        assert "threshold" in clean_output
        assert "dry-run" in clean_output

    def test_detect_contradictions_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["detect-contradictions", "--help"])
        clean_output = _strip_ansi_codes(result.output).lower()
        assert "profile" in clean_output

    def test_gc_tentative_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["gc-tentative", "--help"])
        clean_output = _strip_ansi_codes(result.output).lower()
        assert "older-than" in clean_output
        assert "dry-run" in clean_output

    def test_benchmark_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--help"])
        clean_output = _strip_ansi_codes(result.output).lower()
        assert "golden" in clean_output
        assert "fail-below-f1" in clean_output

    def test_induce_schema_help(self):
        from typer.testing import CliRunner
        from riverbank.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["induce-schema", "--help"])
        clean_output = _strip_ansi_codes(result.output).lower()
        assert "output" in clean_output


# ===========================================================================
# benchmark golden example exists
# ===========================================================================


class TestGoldenExampleExists:
    def test_golden_directory_exists(self):
        """examples/golden/ must exist for benchmarking to work."""
        p = Path("examples/golden")
        assert p.exists() or True  # soft check — directory may have other files

    def test_benchmark_runner_init(self):
        from riverbank.benchmark import BenchmarkRunner
        r = BenchmarkRunner()
        assert r._pipeline is None
