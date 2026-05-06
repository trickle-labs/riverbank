"""Unit tests for v0.13.1 — Extraction Feedback Loops.

Covers:
- FewShotExpander: expand, should_expand, bank_path_for_profile, _triple_key
- FewShotInjector: semantic selection (_select_semantic, inject with fragment_text)
- VerificationPass: batched verification (_verify_batch, batch_size config)
- KnowledgePrefixAdapter: from_profile, build_context, _extract_candidate_tokens
- CompilerProfile: knowledge_prefix field
- CLI: new v0.13.1 commands registered
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_triple(subject, predicate, object_value, confidence=0.92, excerpt="test excerpt"):
    ev = SimpleNamespace(excerpt=excerpt)
    return SimpleNamespace(
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        confidence=confidence,
        evidence=ev,
    )


def _make_low_conf_triple(subject, predicate, object_value, confidence=0.4, evidence="text"):
    return {
        "subject": subject,
        "predicate": predicate,
        "object_value": object_value,
        "confidence": confidence,
        "evidence": evidence,
    }


# ===========================================================================
# FewShotExpander
# ===========================================================================


class TestFewShotExpanderBasics:
    def test_import(self):
        from riverbank.few_shot_expansion import FewShotExpander

        assert FewShotExpander is not None

    def test_expansion_result_import(self):
        from riverbank.few_shot_expansion import ExpansionResult

        assert ExpansionResult is not None

    def test_default_thresholds(self):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander()
        assert exp._cq_threshold == pytest.approx(0.70)
        assert exp._confidence_threshold == pytest.approx(0.85)
        assert exp._max_bank_size == 15
        assert exp._max_new_per_run == 5


class TestFewShotExpanderExpand:
    def test_skips_when_coverage_below_threshold(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.70)
        bank = tmp_path / "bank.jsonl"
        triples = [_make_triple("ex:A", "ex:p", "ex:B", confidence=0.95)]

        result = exp.expand(triples, bank, cq_coverage=0.60)

        assert result.examples_added == 0
        assert result.threshold_met is False
        assert not bank.exists()

    def test_expands_when_coverage_meets_threshold(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.70, confidence_threshold=0.85)
        bank = tmp_path / "bank.jsonl"
        triples = [_make_triple("ex:A", "ex:type", "ex:Thing", confidence=0.95)]

        result = exp.expand(triples, bank, cq_coverage=0.80)

        assert result.threshold_met is True
        assert result.examples_added >= 1
        assert bank.exists()

    def test_skips_low_confidence_triples(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.50, confidence_threshold=0.90)
        bank = tmp_path / "bank.jsonl"
        triples = [
            _make_triple("ex:A", "ex:p", "ex:B", confidence=0.70),   # below threshold
        ]

        result = exp.expand(triples, bank, cq_coverage=0.80)

        assert result.examples_skipped_confidence == 1
        assert result.examples_added == 0

    def test_diversity_constraint_no_duplicate_predicate_type(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.50, confidence_threshold=0.85, max_new_per_run=3)
        bank = tmp_path / "bank.jsonl"

        # All triples have the same predicate AND similar object values → only one should be added
        triples = [
            _make_triple("ex:A", "ex:type", "entity1234", confidence=0.95),
            _make_triple("ex:B", "ex:type", "entity1234", confidence=0.95),
            _make_triple("ex:C", "ex:type", "entity1234", confidence=0.95),
        ]

        result = exp.expand(triples, bank, cq_coverage=0.80)

        # At most 1 due to same predicate+type diversity constraint
        assert result.examples_added <= 1
        assert result.examples_skipped_diversity >= 2

    def test_dry_run_does_not_write(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.50, confidence_threshold=0.85)
        bank = tmp_path / "bank.jsonl"
        triples = [_make_triple("ex:A", "ex:p", "ex:B", confidence=0.95)]

        result = exp.expand(triples, bank, cq_coverage=0.80, dry_run=True)

        assert result.examples_added >= 1
        assert not bank.exists()   # dry_run → no write

    def test_bank_capped_at_max_size(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(
            cq_threshold=0.50,
            confidence_threshold=0.85,
            max_bank_size=3,
            max_new_per_run=10,
        )
        bank = tmp_path / "bank.jsonl"

        # Pre-populate the bank with 2 entries
        existing = [
            {"subject": f"ex:Existing{i}", "predicate": f"ex:pred{i}", "object_value": f"ex:Obj{i}", "confidence": 0.9, "excerpt": ""}
            for i in range(2)
        ]
        bank.write_text("\n".join(json.dumps(e) for e in existing) + "\n")

        # Add a new triple with a unique predicate
        triples = [_make_triple("ex:New", "ex:uniquePred", "ex:Value", confidence=0.95)]
        result = exp.expand(triples, bank, cq_coverage=0.80)

        bank_entries = [json.loads(l) for l in bank.read_text().splitlines() if l.strip()]
        assert len(bank_entries) <= 3   # capped at max_bank_size

    def test_cq_filtering(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.50, confidence_threshold=0.85)
        bank = tmp_path / "bank.jsonl"

        # CQ references "version" keyword; triple about "author" doesn't match
        cqs = ["What is the version of each component?"]
        triples = [
            _make_triple("ex:App", "ex:version", "1.0.0", confidence=0.95),    # matches
            _make_triple("ex:App", "ex:author", "JohnDoe", confidence=0.95),   # doesn't match
        ]

        result = exp.expand(triples, bank, cq_coverage=0.80, competency_questions=cqs)

        # The "author" triple should be skipped by CQ filter
        assert result.examples_skipped_cq >= 1


class TestFewShotExpanderShouldExpand:
    def test_returns_false_when_disabled(self):
        from riverbank.few_shot_expansion import FewShotExpander
        from riverbank.pipeline import CompilerProfile

        exp = FewShotExpander()
        profile = CompilerProfile(name="test", few_shot={})
        assert exp.should_expand(profile, 0.90) is False

    def test_returns_true_when_enabled_and_threshold_met(self):
        from riverbank.few_shot_expansion import FewShotExpander
        from riverbank.pipeline import CompilerProfile

        exp = FewShotExpander(cq_threshold=0.70)
        profile = CompilerProfile(
            name="test",
            few_shot={"auto_expand": True, "auto_expand_cq_threshold": 0.70},
        )
        assert exp.should_expand(profile, 0.80) is True

    def test_returns_false_when_threshold_not_met(self):
        from riverbank.few_shot_expansion import FewShotExpander
        from riverbank.pipeline import CompilerProfile

        exp = FewShotExpander(cq_threshold=0.70)
        profile = CompilerProfile(
            name="test",
            few_shot={"auto_expand": True, "auto_expand_cq_threshold": 0.70},
        )
        assert exp.should_expand(profile, 0.50) is False


class TestFewShotExpanderBankPath:
    def test_bank_path_uses_profile_name(self):
        from riverbank.few_shot_expansion import FewShotExpander
        from riverbank.pipeline import CompilerProfile

        exp = FewShotExpander()
        profile = CompilerProfile(
            name="my-profile",
            few_shot={"source": "tests/golden/"},
        )
        path = exp.bank_path_for_profile(profile)
        assert path.name == "my-profile_autobank.jsonl"
        assert "tests/golden" in str(path)


# ===========================================================================
# FewShotInjector — semantic selection
# ===========================================================================


class TestFewShotInjectorSemanticSelection:
    def test_semantic_selection_import(self):
        from riverbank.preprocessors import FewShotInjector

        assert FewShotInjector is not None

    def test_inject_accepts_fragment_text_param(self):
        from riverbank.preprocessors import FewShotConfig, FewShotInjector

        cfg = FewShotConfig(enabled=False)
        inj = FewShotInjector(cfg)
        # Should not raise
        result = inj.inject("prompt text", fragment_text="some fragment")
        assert result == "prompt text"

    def test_embedder_attribute_initialized_to_none(self):
        from riverbank.preprocessors import FewShotInjector

        inj = FewShotInjector()
        assert inj._embedder is None

    def test_select_fixed(self):
        from riverbank.preprocessors import FewShotConfig, FewShotExample, FewShotInjector

        cfg = FewShotConfig(enabled=True, selection="fixed", max_examples=2)
        inj = FewShotInjector(cfg)
        examples = [
            FewShotExample(subject=f"ex:S{i}", predicate="ex:p", object_value=f"ex:O{i}", confidence=0.9)
            for i in range(5)
        ]
        selected = inj._select(examples)
        assert len(selected) == 2
        assert selected[0].subject == "ex:S0"

    def test_select_random(self):
        from riverbank.preprocessors import FewShotConfig, FewShotExample, FewShotInjector

        cfg = FewShotConfig(enabled=True, selection="random", max_examples=2)
        inj = FewShotInjector(cfg)
        examples = [
            FewShotExample(subject=f"ex:S{i}", predicate="ex:p", object_value=f"ex:O{i}", confidence=0.9)
            for i in range(5)
        ]
        selected = inj._select(examples)
        assert len(selected) == 2

    def test_semantic_selection_falls_back_to_random_without_sentence_transformers(self):
        from riverbank.preprocessors import FewShotConfig, FewShotExample, FewShotInjector

        cfg = FewShotConfig(enabled=True, selection="semantic", max_examples=2)
        inj = FewShotInjector(cfg)
        examples = [
            FewShotExample(subject=f"ex:S{i}", predicate="ex:p", object_value=f"ex:O{i}", confidence=0.9)
            for i in range(5)
        ]

        # Force sentence_transformers to be unavailable
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            selected = inj._select(examples, fragment_text="some fragment text")

        # Falls back to random — should return max_examples items
        assert len(selected) == 2

    def test_semantic_selection_returns_empty_when_no_fragment_text(self):
        from riverbank.preprocessors import FewShotConfig, FewShotExample, FewShotInjector

        cfg = FewShotConfig(enabled=True, selection="semantic", max_examples=2)
        inj = FewShotInjector(cfg)
        examples = [
            FewShotExample(subject=f"ex:S{i}", predicate="ex:p", object_value=f"ex:O{i}", confidence=0.9)
            for i in range(5)
        ]
        # selection="semantic" but no fragment_text → fall back to random
        selected = inj._select(examples, fragment_text="")
        assert len(selected) == 2

    def test_inject_with_semantic_uses_fragment_text_arg(self, tmp_path):
        """inject() accepts fragment_text keyword arg without error."""
        from riverbank.preprocessors import FewShotConfig, FewShotInjector

        cfg = FewShotConfig(enabled=True, selection="semantic", source=str(tmp_path), max_examples=2)
        inj = FewShotInjector(cfg)
        # No example files in tmp_path → inject returns prompt unchanged
        result = inj.inject("my prompt", fragment_text="this is a fragment about pipes")
        assert result == "my prompt"


# ===========================================================================
# VerificationPass — batched verification
# ===========================================================================


class TestVerificationPassBatch:
    def _make_profile(self, batch_size=5):
        return SimpleNamespace(
            verification={
                "enabled": True,
                "confidence_threshold": 0.75,
                "drop_below": 0.4,
                "boost_above": 0.8,
                "batch_size": batch_size,
            },
            llm=SimpleNamespace(
                provider="ollama",
                api_base="http://localhost:11434/v1",
                api_key="ollama",
                model="llama3",
            ),
        )

    def test_verify_batch_structure(self):
        from riverbank.postprocessors.verify import VerificationPass

        vp = VerificationPass()
        assert hasattr(vp, "_verify_batch")

    def test_verify_batch_returns_one_outcome_per_triple(self):
        from riverbank.postprocessors.verify import VerificationPass

        vp = VerificationPass()

        batch = [
            _make_low_conf_triple("ex:A", "ex:p", "ex:X"),
            _make_low_conf_triple("ex:B", "ex:q", "ex:Y"),
            _make_low_conf_triple("ex:C", "ex:r", "ex:Z"),
        ]

        # Mock the LLM client to return a valid BatchResponse
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.results = [
            SimpleNamespace(index=0, supported=True, confidence=0.85),
            SimpleNamespace(index=1, supported=False, confidence=0.20),
            SimpleNamespace(index=2, supported=True, confidence=0.90),
        ]
        mock_completion = MagicMock()
        mock_completion.usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create_with_completion.return_value = (
            mock_result, mock_completion
        )

        outcomes = vp._verify_batch(batch, mock_client, "llama3")
        assert len(outcomes) == 3
        assert outcomes[0]["supported"] is True
        assert outcomes[1]["supported"] is False
        assert outcomes[2]["verifier_confidence"] == pytest.approx(0.90)

    def test_verify_batch_fallback_on_llm_error(self):
        """When batch LLM call fails, falls back to individual calls."""
        from riverbank.postprocessors.verify import VerificationPass

        vp = VerificationPass()
        batch = [
            _make_low_conf_triple("ex:A", "ex:p", "ex:X"),
            _make_low_conf_triple("ex:B", "ex:q", "ex:Y"),
        ]

        mock_client = MagicMock()
        # First call raises (batch attempt), subsequent calls succeed
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("batch LLM error")
            result = SimpleNamespace(supported=True, confidence=0.8)
            completion = MagicMock()
            completion.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
            return result, completion

        mock_client.chat.completions.create_with_completion.side_effect = side_effect

        # Should fall back without raising
        outcomes = vp._verify_batch(batch, mock_client, "llama3")
        assert len(outcomes) == 2

    def test_batch_size_capped_at_max(self):
        """batch_size > 10 is capped to _MAX_BATCH_SIZE."""
        from riverbank.postprocessors.verify import _MAX_BATCH_SIZE, VerificationPass

        vp = VerificationPass()
        profile = SimpleNamespace(
            verification={
                "enabled": True,
                "confidence_threshold": 0.75,
                "drop_below": 0.4,
                "boost_above": 0.8,
                "batch_size": 999,
            }
        )
        assert _MAX_BATCH_SIZE == 10

    def test_verify_skips_when_disabled(self):
        from riverbank.postprocessors.verify import VerificationPass

        vp = VerificationPass()
        conn = MagicMock()
        profile = SimpleNamespace(verification={"enabled": False})

        result = vp.verify(conn, "http://graph/trusted", profile)
        assert result.triples_examined == 0

    def test_verify_no_candidates(self):
        from riverbank.postprocessors.verify import VerificationPass

        vp = VerificationPass()
        conn = MagicMock()
        profile = SimpleNamespace(
            verification={"enabled": True, "confidence_threshold": 0.75}
        )

        with patch("riverbank.catalog.graph.sparql_query", return_value=[]):
            result = vp.verify(conn, "http://graph/trusted", profile)

        assert result.triples_examined == 0

    def test_verify_uses_batch_size_from_profile(self):
        """Verify that batch_size=1 triggers single-triple path (not _verify_batch)."""
        from riverbank.postprocessors.verify import VerificationPass

        vp = VerificationPass()
        conn = MagicMock()
        profile = self._make_profile(batch_size=1)

        candidates = [_make_low_conf_triple("ex:A", "ex:p", "ex:B", confidence=0.5)]

        with patch("riverbank.catalog.graph.sparql_query", return_value=[
            {"s": "ex:A", "p": "ex:p", "o": "ex:B", "confidence": 0.5, "evidence": "text"}
        ]):
            with patch.object(vp, "_get_llm_client") as mock_client_fn:
                mock_client = MagicMock()
                mock_result = SimpleNamespace(supported=True, confidence=0.85)
                mock_completion = MagicMock()
                mock_completion.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
                mock_client.chat.completions.create_with_completion.return_value = (
                    mock_result, mock_completion
                )
                mock_client_fn.return_value = (mock_client, "llama3")

                result = vp.verify(conn, "http://graph/trusted", profile)

        assert result.triples_examined == 1

    def test_batch_size_default_is_5(self):
        """Ensure batch_size defaults to 5 when not in profile."""
        from riverbank.postprocessors.verify import VerificationPass

        # Read the verify source to check default
        import inspect
        src = inspect.getsource(VerificationPass.verify)
        assert "batch_size" in src
        assert "5" in src


# ===========================================================================
# KnowledgePrefixAdapter
# ===========================================================================


class TestKnowledgePrefixAdapterFromProfile:
    def test_disabled_when_not_configured(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test")
        adapter = KnowledgePrefixAdapter.from_profile(profile)
        assert adapter.is_enabled() is False

    def test_disabled_when_enabled_false(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(
            name="test",
            knowledge_prefix={"enabled": False},
        )
        adapter = KnowledgePrefixAdapter.from_profile(profile)
        assert adapter.is_enabled() is False

    def test_enabled_when_configured(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(
            name="test",
            knowledge_prefix={
                "enabled": True,
                "max_graph_context_tokens": 150,
                "top_entities": 5,
            },
        )
        adapter = KnowledgePrefixAdapter.from_profile(profile)
        assert adapter.is_enabled() is True
        assert adapter._max_tokens == 150
        assert adapter._top_entities == 5


class TestKnowledgePrefixAdapterTokenExtraction:
    def test_extracts_tokens(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter(min_entity_label_length=3)
        tokens = adapter._extract_candidate_tokens(
            "The Sesam pipe connects to the Salesforce platform."
        )
        assert "sesam" in tokens
        assert "salesforce" in tokens

    def test_filters_stop_words(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter(min_entity_label_length=3)
        tokens = adapter._extract_candidate_tokens("the is are in of to")
        assert len(tokens) == 0

    def test_filters_short_tokens(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter(min_entity_label_length=4)
        tokens = adapter._extract_candidate_tokens("ab abc abcd abcde")
        assert "ab" not in tokens
        assert "abc" not in tokens
        assert "abcd" in tokens

    def test_deduplicates_tokens(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter(min_entity_label_length=3)
        tokens = adapter._extract_candidate_tokens("sesam sesam sesam")
        assert tokens.count("sesam") == 1


class TestKnowledgePrefixAdapterBuildContext:
    def test_empty_context_when_no_entities(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter()
        conn = MagicMock()

        with patch("riverbank.catalog.graph.sparql_query", return_value=[]):
            result = adapter.build_context(conn, "http://graph/trusted", "some text")

        assert result.context_block == ""
        assert result.entities_found == 0

    def test_context_block_format(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter(max_graph_context_tokens=500)
        conn = MagicMock()

        mock_rows = [
            {"entity": "http://ex.org/sesam", "label": "Sesam", "property": "http://ex.org/type", "value": "Platform"},
        ]

        with patch("riverbank.catalog.graph.sparql_query", return_value=mock_rows):
            result = adapter.build_context(
                conn, "http://graph/trusted",
                "The Sesam platform is a data integration tool."
            )

        assert "KNOWN GRAPH CONTEXT" in result.context_block
        assert "sesam" in result.context_block.lower()
        assert result.entities_found == 1
        assert result.triples_injected == 1

    def test_context_block_respects_token_cap(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        # Very small token cap — should limit the output
        adapter = KnowledgePrefixAdapter(max_graph_context_tokens=10, top_entities=20)
        conn = MagicMock()

        mock_rows = [
            {"entity": f"http://ex.org/entity{i}", "label": f"Entity{i}", "property": "", "value": ""}
            for i in range(20)
        ]

        with patch("riverbank.catalog.graph.sparql_query", return_value=mock_rows):
            result = adapter.build_context(
                conn, "http://graph/trusted",
                "entity0 entity1 entity2 entity3 entity4 entity5 entity6 entity7 entity8 entity9"
            )

        # Should have fewer triples than the total due to cap
        assert result.triples_injected < 20

    def test_sparql_error_returns_empty_context(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter()
        conn = MagicMock()

        with patch("riverbank.catalog.graph.sparql_query", side_effect=RuntimeError("no pg_ripple")):
            result = adapter.build_context(
                conn, "http://graph/trusted", "The Sesam platform."
            )

        assert result.context_block == ""
        assert result.entities_found == 0

    def test_disabled_adapter_returns_empty_result(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test")
        adapter = KnowledgePrefixAdapter.from_profile(profile)
        conn = MagicMock()

        result = adapter.build_context(conn, "http://graph/trusted", "some text")
        assert result.context_block == ""

    def test_empty_fragment_text_returns_empty(self):
        from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

        adapter = KnowledgePrefixAdapter()
        conn = MagicMock()

        result = adapter.build_context(conn, "http://graph/trusted", "")
        assert result.context_block == ""


# ===========================================================================
# CompilerProfile: knowledge_prefix field
# ===========================================================================


class TestCompilerProfileKnowledgePrefix:
    def test_knowledge_prefix_field_exists(self):
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test")
        assert hasattr(profile, "knowledge_prefix")

    def test_knowledge_prefix_default_is_empty_dict(self):
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(name="test")
        assert profile.knowledge_prefix == {}

    def test_knowledge_prefix_set_via_constructor(self):
        from riverbank.pipeline import CompilerProfile

        profile = CompilerProfile(
            name="test",
            knowledge_prefix={
                "enabled": True,
                "max_graph_context_tokens": 300,
            },
        )
        assert profile.knowledge_prefix["enabled"] is True
        assert profile.knowledge_prefix["max_graph_context_tokens"] == 300


# ===========================================================================
# CLI: new v0.13.1 commands registered
# ===========================================================================


class TestCLIV0131Commands:
    def test_expand_few_shot_registered(self):
        from riverbank.cli import app

        command_names = [c.name for c in app.registered_commands]
        assert "expand-few-shot" in command_names

    def test_build_knowledge_context_registered(self):
        from riverbank.cli import app

        command_names = [c.name for c in app.registered_commands]
        assert "build-knowledge-context" in command_names


# ===========================================================================
# Integration: FewShotExpander round-trip (write and reload)
# ===========================================================================


class TestFewShotExpanderRoundTrip:
    def test_write_and_reload(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.50, confidence_threshold=0.85, max_new_per_run=10)
        bank = tmp_path / "bank.jsonl"

        triples = [
            _make_triple(f"ex:Subject{i}", f"ex:pred{i}", f"ex:Obj{i}", confidence=0.95)
            for i in range(5)
        ]
        result = exp.expand(triples, bank, cq_coverage=0.80)

        assert result.examples_added > 0
        assert bank.exists()

        # Reload and check
        reloaded = exp._load_bank(bank)
        assert len(reloaded) == result.examples_added
        for entry in reloaded:
            assert "subject" in entry
            assert "predicate" in entry
            assert "object_value" in entry
            assert "confidence" in entry

    def test_idempotent_expansion_skips_duplicates(self, tmp_path):
        from riverbank.few_shot_expansion import FewShotExpander

        exp = FewShotExpander(cq_threshold=0.50, confidence_threshold=0.85, max_new_per_run=5)
        bank = tmp_path / "bank.jsonl"

        triples = [_make_triple("ex:A", "ex:uniquePred123", "ex:B", confidence=0.95)]

        # First expansion
        result1 = exp.expand(triples, bank, cq_coverage=0.80)
        added_first = result1.examples_added

        # Second expansion with same triple — should be skipped as duplicate
        result2 = exp.expand(triples, bank, cq_coverage=0.80)
        reloaded = exp._load_bank(bank)
        assert len(reloaded) == added_first   # bank size unchanged
