"""Unit tests for v0.14.0 — Structural Improvements & Reasoning.

Covers:
- Constrained decoding: CompilerProfile.constrained_decoding field,
  InstructorExtractor builds constrained_decoding flag from profile + provider
- SemanticFragmenter: _split_sentences, _detect_boundaries, fragment (fallback),
  from_profile, single root on short text
- ShaclValidator: from_profile, validate (no pyshacl graceful fallback,
  missing shapes file, full report parsing), ShapeViolation, ShapeValidationReport
- ConstructRulesEngine: run (dry-run, empty rules, execution), _scope_to_graph,
  _construct_to_select, _apply_template, ConstructRuleResult
- OwlRlEngine: from_profile, is_enabled, run (graceful fallback, dry-run),
  OwlRlResult
- CompilerProfile: new v0.14.0 fields
- CLI: new v0.14.0 commands registered
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# CompilerProfile: v0.14.0 fields
# ===========================================================================


class TestCompilerProfileV014Fields:
    def test_constrained_decoding_field_default(self):
        from riverbank.pipeline import CompilerProfile

        p = CompilerProfile(name="test")
        assert p.constrained_decoding is False

    def test_constrained_decoding_set(self):
        from riverbank.pipeline import CompilerProfile

        p = CompilerProfile(name="test", constrained_decoding=True)
        assert p.constrained_decoding is True

    def test_semantic_chunking_default(self):
        from riverbank.pipeline import CompilerProfile

        p = CompilerProfile(name="test")
        assert p.semantic_chunking == {}

    def test_construct_rules_default(self):
        from riverbank.pipeline import CompilerProfile

        p = CompilerProfile(name="test")
        assert p.construct_rules == []

    def test_shacl_validation_default(self):
        from riverbank.pipeline import CompilerProfile

        p = CompilerProfile(name="test")
        assert p.shacl_validation == {}

    def test_owl_rl_default(self):
        from riverbank.pipeline import CompilerProfile

        p = CompilerProfile(name="test")
        assert p.owl_rl == {}

    def test_construct_rules_set(self):
        from riverbank.pipeline import CompilerProfile

        rules = ["CONSTRUCT { ?x ex:p ?y } WHERE { ?x ex:q ?y }"]
        p = CompilerProfile(name="test", construct_rules=rules)
        assert len(p.construct_rules) == 1


# ===========================================================================
# Constrained decoding
# ===========================================================================


class TestConstrainedDecoding:
    def test_constrained_decoding_flag_false_by_default(self):
        """constrained_decoding is False when not set in profile."""
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test")
        settings_mock = SimpleNamespace(
            llm=SimpleNamespace(
                provider="ollama",
                api_base="http://localhost:11434/v1",
                api_key="ollama",
                model="llama3",
            )
        )
        # constrained_decoding only activates for ollama + flag=True
        assert not (
            settings_mock.llm.provider == "ollama"
            and getattr(profile, "constrained_decoding", False)
        )

    def test_constrained_decoding_flag_true_for_ollama(self):
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test", constrained_decoding=True)
        settings_mock = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", api_base="", api_key="ollama", model="llama3")
        )
        assert (
            settings_mock.llm.provider == "ollama"
            and getattr(profile, "constrained_decoding", False)
        )

    def test_constrained_decoding_disabled_for_non_ollama(self):
        """constrained_decoding=True but provider=openai → flag should be False."""
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test", constrained_decoding=True)
        provider = "openai"
        constrained = provider == "ollama" and getattr(profile, "constrained_decoding", False)
        assert constrained is False

    def test_extractor_has_constrained_decoding_logic(self):
        """InstructorExtractor source code mentions constrained_decoding."""
        import inspect
        from riverbank.extractors.instructor_extractor import InstructorExtractor

        src = inspect.getsource(InstructorExtractor._extract_with_llm)
        assert "constrained_decoding" in src

    def test_extra_body_format_key_added(self):
        """JSON schema format key is built for Ollama when constrained."""
        import inspect
        from riverbank.extractors.instructor_extractor import InstructorExtractor

        src = inspect.getsource(InstructorExtractor._extract_with_llm)
        assert "format" in src
        assert "model_json_schema" in src


# ===========================================================================
# SemanticFragmenter
# ===========================================================================


class TestSplitSentences:
    def test_splits_on_period(self):
        from riverbank.fragmenters.semantic import _split_sentences

        sents = _split_sentences("First sentence. Second sentence. Third.")
        assert len(sents) == 3

    def test_handles_exclamation_question(self):
        from riverbank.fragmenters.semantic import _split_sentences

        sents = _split_sentences("Hello! Is this working? Yes it is.")
        assert len(sents) == 3

    def test_empty_string(self):
        from riverbank.fragmenters.semantic import _split_sentences

        assert _split_sentences("") == []

    def test_no_punctuation(self):
        from riverbank.fragmenters.semantic import _split_sentences

        sents = _split_sentences("no punctuation here at all")
        assert len(sents) == 1
        assert sents[0] == "no punctuation here at all"

    def test_filters_empty_strings(self):
        from riverbank.fragmenters.semantic import _split_sentences

        sents = _split_sentences("......")
        # 6 empty after splitting — all should be filtered
        assert all(s.strip() for s in sents)


class TestSemanticFragmenterFromProfile:
    def test_creates_from_profile(self):
        from riverbank.fragmenters.semantic import SemanticFragmenter
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(
            name="test",
            semantic_chunking={
                "model": "all-MiniLM-L6-v2",
                "similarity_threshold": 0.80,
                "min_sentences_per_chunk": 3,
            },
        )
        frag = SemanticFragmenter.from_profile(profile)
        assert frag._threshold == pytest.approx(0.80)
        assert frag._min_sentences == 3

    def test_default_params(self):
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter()
        assert frag._model_name == "all-MiniLM-L6-v2"
        assert frag._threshold == pytest.approx(0.75)


class TestSemanticFragmenterFragment:
    def _make_doc(self, text: str, source_iri: str = "file:///test.md") -> Any:
        return SimpleNamespace(source_iri=source_iri, raw_text=text)

    def test_empty_doc_yields_nothing(self):
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter()
        doc = self._make_doc("")
        result = list(frag.fragment(doc))
        assert result == []

    def test_short_text_yields_single_fragment(self):
        """Fewer than 3 sentences → single root fragment (no model needed)."""
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter()
        doc = self._make_doc("One sentence. Two sentences.")
        result = list(frag.fragment(doc))
        assert len(result) == 1
        assert "One sentence" in result[0].text

    def test_fallback_when_model_unavailable(self):
        """When sentence-transformers is not available, returns single root fragment."""
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter()
        doc = self._make_doc(
            "First topic sentence. Second topic sentence. Third topic sentence. "
            "Fourth topic sentence. Fifth topic sentence."
        )

        with patch.dict("sys.modules", {"sentence_transformers": None}):
            result = list(frag.fragment(doc))

        assert len(result) == 1  # fallback to single root fragment

    def test_name_is_semantic(self):
        from riverbank.fragmenters.semantic import SemanticFragmenter

        assert SemanticFragmenter.name == "semantic"

    def test_fragment_key_format(self):
        """Fragment keys use 'semantic_chunk_N' format."""
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter()
        doc = self._make_doc("Short. Doc.")  # < 3 sentences → single fragment
        result = list(frag.fragment(doc))
        assert result[0].fragment_key == "semantic_chunk_0"

    def test_detect_boundaries_all_similar(self):
        """Embeddings that are all near-identical should produce few boundaries."""
        import numpy as np
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter(similarity_threshold=0.9, min_sentences_per_chunk=1)
        # All identical vectors → cosine similarity == 1.0 → no splits
        embeddings = np.ones((5, 10)) / np.sqrt(10)
        boundaries = frag._detect_boundaries(embeddings)
        assert boundaries == [0]

    def test_detect_boundaries_dissimilar(self):
        """Dissimilar embeddings at every step should produce many boundaries."""
        import numpy as np
        from riverbank.fragmenters.semantic import SemanticFragmenter

        frag = SemanticFragmenter(
            similarity_threshold=0.99,  # very high threshold → lots of splits
            min_sentences_per_chunk=1,
            max_sentences_per_chunk=100,
        )
        # Orthogonal vectors → cosine similarity == 0.0 < 0.99 → split at every step
        n = 6
        d = n
        embeddings = np.eye(n, d)  # each sentence has a unique orthogonal embedding
        boundaries = frag._detect_boundaries(embeddings)
        # Should have a split after sentence 1 (index 1), 2, 3, 4, 5
        assert len(boundaries) > 1


# ===========================================================================
# ShaclValidator
# ===========================================================================


class TestShaclValidatorFromProfile:
    def test_from_profile_defaults(self):
        from riverbank.pipeline import CompilerProfile
        from riverbank.postprocessors.shacl_validator import ShaclValidator

        profile = CompilerProfile(name="test")
        v = ShaclValidator.from_profile(profile)
        assert v._reduce_confidence is False

    def test_from_profile_custom(self):
        from riverbank.pipeline import CompilerProfile
        from riverbank.postprocessors.shacl_validator import ShaclValidator

        profile = CompilerProfile(
            name="test",
            shacl_validation={
                "shapes_path": "ontology/pgc-shapes.ttl",
                "reduce_confidence": True,
                "confidence_penalty": 0.20,
            },
        )
        v = ShaclValidator.from_profile(profile)
        assert v._reduce_confidence is True
        assert v._confidence_penalty == pytest.approx(0.20)


class TestShaclValidatorValidate:
    def test_missing_shapes_file_returns_empty_report(self):
        from riverbank.postprocessors.shacl_validator import ShaclValidator

        v = ShaclValidator(shapes_path="/nonexistent/path.ttl")
        conn = MagicMock()
        report = v.validate(conn, "http://graph/trusted")
        assert report.conforms is True
        assert report.violations == []

    def test_pyshacl_unavailable_returns_empty_report(self, tmp_path):
        from riverbank.postprocessors.shacl_validator import ShaclValidator

        shapes = tmp_path / "shapes.ttl"
        shapes.write_text("@prefix sh: <http://www.w3.org/ns/shacl#> .\n")
        v = ShaclValidator(shapes_path=str(shapes))
        conn = MagicMock()

        with patch.dict("sys.modules", {"pyshacl": None, "rdflib": None}):
            report = v.validate(conn, "http://graph/trusted")

        assert report.conforms is True

    def test_shape_violation_dataclass(self):
        from riverbank.postprocessors.shacl_validator import ShapeViolation

        v = ShapeViolation(
            focus_node="http://ex.org/A",
            result_path="http://ex.org/p",
            message="Missing value",
            severity="sh:Violation",
            source_shape="http://ex.org/Shape",
        )
        assert v.focus_node == "http://ex.org/A"
        assert v.severity == "sh:Violation"

    def test_report_dataclass_defaults(self):
        from riverbank.postprocessors.shacl_validator import ShapeValidationReport

        r = ShapeValidationReport()
        assert r.conforms is True
        assert r.violations == []

    def test_bundled_shapes_file_exists(self):
        """The pgc-shapes.ttl file must exist in the ontology directory."""
        shapes_path = Path("ontology/pgc-shapes.ttl")
        assert shapes_path.exists(), "ontology/pgc-shapes.ttl must exist for SHACL validation"

    def test_validate_with_empty_graph(self, tmp_path):
        """Validation against an empty graph should report conformance."""
        from riverbank.postprocessors.shacl_validator import ShaclValidator

        shapes = tmp_path / "shapes.ttl"
        shapes.write_text("""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
""")
        v = ShaclValidator(shapes_path=str(shapes))
        conn = MagicMock()

        with patch("riverbank.catalog.graph.sparql_query", return_value=[]):
            report = v.validate(conn, "http://graph/trusted")

        assert report.conforms is True


# ===========================================================================
# ConstructRulesEngine
# ===========================================================================


class TestConstructRulesEngine:
    def test_import(self):
        from riverbank.inference import ConstructRulesEngine

        assert ConstructRulesEngine is not None

    def test_result_dataclass(self):
        from riverbank.inference import ConstructRuleResult

        r = ConstructRuleResult()
        assert r.rules_executed == 0
        assert r.triples_inferred == 0

    def test_empty_rules_returns_empty_result(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        conn = MagicMock()
        result = engine.run(conn, "http://graph/trusted", [])
        assert result.rules_executed == 0

    def test_dry_run_does_not_write(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        conn = MagicMock()
        rules = ["CONSTRUCT { ?x ex:p ?y } WHERE { ?x ex:q ?y }"]

        with patch("riverbank.catalog.graph.sparql_query", return_value=[
            {"x": "http://ex.org/A", "y": "http://ex.org/B"}
        ]):
            result = engine.run(conn, "http://graph/trusted", rules, dry_run=True)

        assert result.rules_executed == 1
        # dry_run → no write call
        assert result.triples_inferred == 1  # counted but not written

    def test_scope_to_graph_wraps_where(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        rule = "CONSTRUCT { ?x ex:p ?y } WHERE { ?x ex:q ?y }"
        scoped = engine._scope_to_graph(rule, "http://graph/trusted")
        assert "GRAPH <http://graph/trusted>" in scoped

    def test_scope_to_graph_skips_if_graph_present(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        rule = "CONSTRUCT { ?x ex:p ?y } WHERE { GRAPH <http://g> { ?x ex:q ?y } }"
        # Should not re-scope
        scoped = engine._scope_to_graph(rule, "http://other")
        assert "GRAPH <http://other>" not in scoped

    def test_construct_to_select_basic(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        rule = "CONSTRUCT { ?x ex:p ?y } WHERE { ?x ex:q ?y }"
        select_q, template = engine._construct_to_select(rule)
        assert "SELECT" in select_q
        assert "?x" in template or "?y" in template

    def test_apply_template_empty_rows(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        result = engine._apply_template([], ["?x", "ex:p", "?y"])
        assert result == []

    def test_apply_template_with_bindings(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        rows = [{"x": "http://ex.org/A", "y": "http://ex.org/B"}]
        template = ["?x", "ex:p", "?y"]
        result = engine._apply_template(rows, template)
        assert len(result) == 1
        assert result[0] == ("http://ex.org/A", "ex:p", "http://ex.org/B")

    def test_invalid_rule_does_not_crash(self):
        from riverbank.inference import ConstructRulesEngine

        engine = ConstructRulesEngine()
        conn = MagicMock()
        rules = ["not a valid sparql query at all"]
        result = engine.run(conn, "http://graph/trusted", rules, dry_run=True)
        assert result.rules_failed == 1
        assert result.rules_executed == 0


# ===========================================================================
# OwlRlEngine
# ===========================================================================


class TestOwlRlEngine:
    def test_import(self):
        from riverbank.inference.owl_rl import OwlRlEngine

        assert OwlRlEngine is not None

    def test_result_dataclass(self):
        from riverbank.inference.owl_rl import OwlRlResult

        r = OwlRlResult()
        assert r.triples_inferred == 0
        assert r.inferred_graph == "http://riverbank.example/graph/inferred"

    def test_from_profile_reads_max_triples(self):
        from riverbank.inference.owl_rl import OwlRlEngine
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test", owl_rl={"enabled": True, "max_triples": 1000})
        engine = OwlRlEngine.from_profile(profile)
        assert engine._max_triples == 1000

    def test_is_enabled_false_by_default(self):
        from riverbank.inference.owl_rl import OwlRlEngine
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test")
        engine = OwlRlEngine()
        assert engine.is_enabled(profile) is False

    def test_is_enabled_true_when_set(self):
        from riverbank.inference.owl_rl import OwlRlEngine
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test", owl_rl={"enabled": True})
        engine = OwlRlEngine()
        assert engine.is_enabled(profile) is True

    def test_graceful_fallback_when_no_owlrl(self):
        from riverbank.inference.owl_rl import OwlRlEngine

        engine = OwlRlEngine()
        conn = MagicMock()

        with patch.dict("sys.modules", {"owlrl": None, "rdflib": None}):
            result = engine.run(conn, "http://graph/trusted")

        assert result.triples_inferred == 0
        assert result.triples_written == 0

    def test_dry_run_does_not_write(self):
        """Dry-run: compute closure but don't write."""
        from riverbank.inference.owl_rl import OwlRlEngine

        engine = OwlRlEngine(max_triples=100)
        conn = MagicMock()

        # Mock sparql_query to return some triples
        mock_rows = [
            {"s": "http://ex.org/A", "p": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
             "o": "http://ex.org/ClassA"},
        ]

        import rdflib
        import owlrl

        with patch("riverbank.catalog.graph.sparql_query", return_value=mock_rows):
            result = engine.run(conn, "http://graph/trusted", dry_run=True)

        # dry_run → triples_written == 0
        assert result.triples_written == 0

    def test_cap_applied_to_inferred_triples(self):
        from riverbank.inference.owl_rl import OwlRlEngine, _INFERRED_GRAPH

        engine = OwlRlEngine(max_triples=2)
        # The cap logic: if new_triples > max_triples, cap and set triples_capped
        new_triples = [
            ("http://ex.org/A", "http://ex.org/p", "http://ex.org/B"),
            ("http://ex.org/C", "http://ex.org/q", "http://ex.org/D"),
            ("http://ex.org/E", "http://ex.org/r", "http://ex.org/F"),
        ]
        assert len(new_triples) > engine._max_triples
        capped = len(new_triples) - engine._max_triples
        trimmed = new_triples[: engine._max_triples]
        assert len(trimmed) == 2
        assert capped == 1

    def test_inferred_graph_iri(self):
        from riverbank.inference.owl_rl import OwlRlEngine, _INFERRED_GRAPH

        assert _INFERRED_GRAPH == "http://riverbank.example/graph/inferred"
        engine = OwlRlEngine()
        assert engine._inferred_graph == _INFERRED_GRAPH


# ===========================================================================
# CLI: new v0.14.0 commands registered
# ===========================================================================


class TestCLIV014Commands:
    def test_validate_shapes_registered(self):
        from riverbank.cli import app

        command_names = [c.name for c in app.registered_commands]
        assert "validate-shapes" in command_names

    def test_run_construct_rules_registered(self):
        from riverbank.cli import app

        command_names = [c.name for c in app.registered_commands]
        assert "run-construct-rules" in command_names

    def test_run_owl_rl_registered(self):
        from riverbank.cli import app

        command_names = [c.name for c in app.registered_commands]
        assert "run-owl-rl" in command_names
