"""Unit tests for the document distillation module (v0.15.2).

All strategies are covered.  LLM-dependent strategies use a mock LLM client.
The ``boilerplate_removal`` tests use no LLM at all.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import xxhash

from riverbank.distillers import (
    BoilerplateFilter,
    BudgetOptimizer,
    DistillationResult,
    DocumentDistiller,
    SectionClassifier,
    _parse_sections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_ARTICLE = """\
# Marie Curie

Marie Curie was a Polish and naturalised-French physicist and chemist.

## Early Life

She was born on 7 November 1867 in Warsaw, Poland.

## Scientific Achievements

She discovered polonium and radium. [1]
She was awarded the Nobel Prize in Physics in 1903 and Chemistry in 1911.

## References

- Smith, John (2005). *Marie Curie and the Science of Radioactivity*. Oxford.
- Jones, A. et al., 2010. Further studies.

## See Also

- Radioactivity
- Nobel Prize

## External Links

- [Nobel Prize page](https://www.nobelprize.org/marie-curie)
"""

_LARGE_ARTICLE = "# Large Article\n\n" + ("This is a factual sentence with key information. " * 200)


def _content_hash(text: str) -> bytes:
    return xxhash.xxh3_128(text.encode()).digest()


def _fake_profile(**distillation_kwargs: Any) -> Any:
    """Build a minimal profile-like object with a distillation config."""
    return SimpleNamespace(
        distillation=distillation_kwargs,
        llm=None,
    )


def _make_mock_llm_response(content: str, prompt_tokens: int = 10, completion_tokens: int = 20) -> Any:
    """Build a mock OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


# ---------------------------------------------------------------------------
# DistillationResult dataclass
# ---------------------------------------------------------------------------


def test_distillation_result_fields() -> None:
    r = DistillationResult(
        distilled_text="hello",
        cache_hit=False,
        strategy_used="moderate",
        original_bytes=100,
        distilled_bytes=50,
        llm_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
    )
    assert r.distilled_text == "hello"
    assert r.cache_hit is False
    assert r.strategy_used == "moderate"
    assert r.original_bytes == 100
    assert r.distilled_bytes == 50
    assert r.llm_calls == 1


# ---------------------------------------------------------------------------
# BoilerplateFilter (no LLM)
# ---------------------------------------------------------------------------


class TestBoilerplateFilter:
    def test_strips_references_section(self) -> None:
        f = BoilerplateFilter()
        result = f.filter(_SAMPLE_ARTICLE)
        assert "References" not in result
        assert "Smith, John" not in result

    def test_strips_see_also_section(self) -> None:
        f = BoilerplateFilter()
        result = f.filter(_SAMPLE_ARTICLE)
        assert "See Also" not in result
        assert "Radioactivity" not in result

    def test_strips_external_links_section(self) -> None:
        f = BoilerplateFilter()
        result = f.filter(_SAMPLE_ARTICLE)
        assert "External Links" not in result
        assert "nobelprize.org" not in result

    def test_preserves_factual_content(self) -> None:
        f = BoilerplateFilter()
        result = f.filter(_SAMPLE_ARTICLE)
        assert "Marie Curie" in result
        assert "Nobel Prize" in result
        assert "polonium" in result

    def test_strips_inline_citations(self) -> None:
        f = BoilerplateFilter()
        text = "She discovered polonium [1] and radium [[2]]."
        result = f.filter(text)
        assert "[1]" not in result
        assert "[[2]]" not in result
        assert "polonium" in result

    def test_strips_author_year_citations(self) -> None:
        f = BoilerplateFilter()
        text = "Radioactivity was studied extensively (Curie, 1903)."
        result = f.filter(text)
        assert "(Curie, 1903)" not in result
        assert "Radioactivity" in result

    def test_strips_et_al_citations(self) -> None:
        f = BoilerplateFilter()
        text = "Results confirmed by (Jones et al., 2010)."
        result = f.filter(text)
        assert "(Jones et al., 2010)" not in result

    def test_strips_image_captions(self) -> None:
        f = BoilerplateFilter()
        text = "## Biography\n\n![Portrait](curie.jpg)\nFigure 1: Marie Curie in 1903.\n\nShe was born..."
        result = f.filter(text)
        assert "![Portrait]" not in result
        assert "Figure 1" not in result
        assert "She was born" in result

    def test_strips_horizontal_rules(self) -> None:
        f = BoilerplateFilter()
        text = "## Section A\n\nContent.\n\n---\n\n## Section B\n\nMore content."
        result = f.filter(text)
        assert "---" not in result
        assert "Content." in result
        assert "More content." in result

    def test_converts_hyperlinks_to_text(self) -> None:
        f = BoilerplateFilter()
        text = "See the [Nobel Prize page](https://www.nobelprize.org/marie-curie)."
        result = f.filter(text)
        assert "nobelprize.org" not in result
        assert "Nobel Prize page" in result

    def test_no_llm_calls(self) -> None:
        """BoilerplateFilter is deterministic — no LLM required."""
        f = BoilerplateFilter()
        # If openai is not importable it still works
        with patch.dict("sys.modules", {"openai": None}):
            result = f.filter(_SAMPLE_ARTICLE)
        assert "Marie Curie" in result

    def test_custom_noise_headings(self) -> None:
        f = BoilerplateFilter(noise_headings=frozenset({"scientific achievements"}))
        result = f.filter(_SAMPLE_ARTICLE)
        assert "Marie Curie" in result
        assert "polonium" not in result  # stripped by custom noise heading

    def test_multiple_blank_lines_collapsed(self) -> None:
        f = BoilerplateFilter()
        text = "Line one.\n\n\n\nLine two."
        result = f.filter(text)
        assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# _parse_sections helper
# ---------------------------------------------------------------------------


class TestParseSections:
    def test_parses_headings(self) -> None:
        sections = _parse_sections(_SAMPLE_ARTICLE)
        headings = [s["heading"] for s in sections]
        assert "Marie Curie" in headings
        assert "Early Life" in headings
        assert "Scientific Achievements" in headings

    def test_preamble_has_empty_heading(self) -> None:
        text = "Some preamble text.\n\n# Section One\n\nContent."
        sections = _parse_sections(text)
        assert sections[0]["heading"] == ""
        assert "preamble" in sections[0]["content"]

    def test_empty_text(self) -> None:
        assert _parse_sections("") == []

    def test_no_headings(self) -> None:
        text = "Just plain text with no headings."
        sections = _parse_sections(text)
        assert len(sections) == 1
        assert sections[0]["heading"] == ""


# ---------------------------------------------------------------------------
# BudgetOptimizer
# ---------------------------------------------------------------------------


class TestBudgetOptimizer:
    def test_skip_for_small_document(self) -> None:
        opt = BudgetOptimizer(min_triple_target=50)
        # 50 / 0.5 = 100 kB ideal; document is 10 kB → skip
        result = opt.select_strategy(10 * 1024)
        assert result == "skip"

    def test_conservative_for_moderate_reduction(self) -> None:
        opt = BudgetOptimizer(min_triple_target=50)
        # ideal = 100 kB; document is 150 kB → ratio = 100/150 ≈ 0.67 → conservative
        result = opt.select_strategy(150 * 1024)
        assert result == "conservative"

    def test_moderate_for_large_document(self) -> None:
        opt = BudgetOptimizer(min_triple_target=50)
        # ideal = 100 kB; document is 350 kB → ratio = 100/350 ≈ 0.29 → moderate
        result = opt.select_strategy(350 * 1024)
        assert result == "moderate"

    def test_aggressive_for_very_large_document(self) -> None:
        opt = BudgetOptimizer(min_triple_target=50)
        # ideal = 100 kB; document is 1000 kB → ratio = 0.10 → aggressive
        result = opt.select_strategy(1000 * 1024)
        assert result == "aggressive"

    def test_custom_triple_target(self) -> None:
        opt = BudgetOptimizer(min_triple_target=10)
        # ideal = 10/0.5 = 20 kB; document is 500 kB → aggressive
        result = opt.select_strategy(500 * 1024)
        assert result == "aggressive"


# ---------------------------------------------------------------------------
# SectionClassifier (mock LLM)
# ---------------------------------------------------------------------------


class TestSectionClassifier:
    def _mock_client(self, response_content: str) -> Any:
        client = MagicMock()
        client.chat.completions.create.return_value = _make_mock_llm_response(
            response_content
        )
        return client

    def test_classify_sections(self) -> None:
        classification = {"Introduction": "factual", "References": "reference"}
        client = self._mock_client(json.dumps(classification))
        sc = SectionClassifier(client, "test-model", "ollama")
        result = sc.classify_sections(["Introduction", "References"])
        assert result["Introduction"] == "factual"
        assert result["References"] == "reference"

    def test_classify_empty_headings(self) -> None:
        client = MagicMock()
        sc = SectionClassifier(client, "test-model", "ollama")
        result = sc.classify_sections([])
        assert result == {}
        client.chat.completions.create.assert_not_called()

    def test_classify_handles_llm_failure(self) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("connection error")
        sc = SectionClassifier(client, "test-model", "ollama")
        result = sc.classify_sections(["Introduction"])
        assert result == {}

    def test_summarize_section(self) -> None:
        summary_text = "Marie Curie discovered polonium and radium."
        client = self._mock_client(summary_text)
        sc = SectionClassifier(client, "test-model", "ollama")
        summary, pt, ct = sc.summarize_section("Life", "Long biographical content...")
        assert summary == summary_text
        assert pt == 10
        assert ct == 20

    def test_summarize_section_llm_failure_returns_original(self) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("timeout")
        sc = SectionClassifier(client, "test-model", "ollama")
        original = "Original content here."
        result, pt, ct = sc.summarize_section("Section", original)
        assert result == original

    def test_ollama_keep_alive_extra_body(self) -> None:
        client = MagicMock()
        client.chat.completions.create.return_value = _make_mock_llm_response("{}")
        sc = SectionClassifier(client, "test-model", "ollama")
        sc.classify_sections(["Intro"])
        call_kwargs = client.chat.completions.create.call_args[1]
        assert call_kwargs.get("extra_body") == {"keep_alive": "5m"}

    def test_non_ollama_no_extra_body(self) -> None:
        client = MagicMock()
        client.chat.completions.create.return_value = _make_mock_llm_response("{}")
        sc = SectionClassifier(client, "test-model", "openai")
        sc.classify_sections(["Intro"])
        call_kwargs = client.chat.completions.create.call_args[1]
        assert "extra_body" not in call_kwargs


# ---------------------------------------------------------------------------
# DocumentDistiller.from_profile
# ---------------------------------------------------------------------------


class TestDocumentDistillerFromProfile:
    def test_default_strategy(self) -> None:
        profile = _fake_profile(enabled=True)
        d = DocumentDistiller.from_profile(profile)
        assert d._strategy == "moderate"

    def test_custom_strategy(self) -> None:
        profile = _fake_profile(enabled=True, strategy="aggressive")
        d = DocumentDistiller.from_profile(profile)
        assert d._strategy == "aggressive"

    def test_target_size_from_profile(self) -> None:
        profile = _fake_profile(enabled=True, strategy="aggressive", target_size_bytes=5120)
        d = DocumentDistiller.from_profile(profile)
        assert d._target_size_bytes == 5120

    def test_default_target_size_for_aggressive(self) -> None:
        profile = _fake_profile(enabled=True, strategy="aggressive")
        d = DocumentDistiller.from_profile(profile)
        assert d._target_size_bytes == 10_240

    def test_default_target_size_for_moderate(self) -> None:
        profile = _fake_profile(enabled=True, strategy="moderate")
        d = DocumentDistiller.from_profile(profile)
        assert d._target_size_bytes == 30_720

    def test_model_overrides(self) -> None:
        profile = _fake_profile(
            enabled=True, model_provider="openai", model_name="gpt-4o-mini"
        )
        d = DocumentDistiller.from_profile(profile)
        assert d._model_provider_override == "openai"
        assert d._model_name_override == "gpt-4o-mini"

    def test_budget_optimizer_created_for_budget_optimized(self) -> None:
        profile = _fake_profile(
            enabled=True,
            strategy="budget_optimized",
            extraction_budget_usd=2.0,
            min_triple_target=100,
        )
        d = DocumentDistiller.from_profile(profile)
        assert d._budget_optimizer is not None
        assert d._budget_optimizer._min_triple_target == 100

    def test_section_types_from_profile(self) -> None:
        profile = _fake_profile(
            enabled=True,
            strategy="section_aware",
            section_types={"factual": "keep", "reference": "remove"},
        )
        d = DocumentDistiller.from_profile(profile)
        assert d._section_types["factual"] == "keep"
        assert d._section_types["reference"] == "remove"

    def test_custom_cache_dir(self, tmp_path: Path) -> None:
        profile = _fake_profile(
            enabled=True, cache_dir=str(tmp_path / "custom_cache")
        )
        d = DocumentDistiller.from_profile(profile)
        assert d._cache_dir == tmp_path / "custom_cache"


# ---------------------------------------------------------------------------
# DocumentDistiller.distill — boilerplate_removal (no LLM)
# ---------------------------------------------------------------------------


class TestDistillBoilerplateRemoval:
    def test_strips_noise_sections(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert "References" not in result.distilled_text
        assert "Marie Curie" in result.distilled_text

    def test_no_llm_calls(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.llm_calls == 0

    def test_strategy_used_set(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.strategy_used == "boilerplate_removal"

    def test_original_and_distilled_bytes_set(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.original_bytes == len(_SAMPLE_ARTICLE.encode())
        assert result.distilled_bytes > 0
        assert result.distilled_bytes <= result.original_bytes

    def test_result_is_cached(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        h = _content_hash(_SAMPLE_ARTICLE)
        result1 = d.distill(_SAMPLE_ARTICLE, h, profile)
        assert result1.cache_hit is False
        result2 = d.distill(_SAMPLE_ARTICLE, h, profile)
        assert result2.cache_hit is True
        assert result2.distilled_text == result1.distilled_text

    def test_cache_key_includes_strategy(self, tmp_path: Path) -> None:
        d1 = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        d2 = DocumentDistiller(strategy="moderate", cache_dir=tmp_path)
        h = _content_hash("test")
        key1 = d1._cache_key(h, "boilerplate_removal")
        key2 = d2._cache_key(h, "moderate")
        assert key1 != key2


# ---------------------------------------------------------------------------
# DocumentDistiller.distill — LLM strategies (mock LLM)
# ---------------------------------------------------------------------------


def _make_distiller_with_mock_llm(
    tmp_path: Path,
    strategy: str,
    llm_response: str,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> tuple[DocumentDistiller, Any]:
    """Build a DocumentDistiller with a patched LLM client."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_mock_llm_response(
        llm_response, prompt_tokens, completion_tokens
    )
    d = DocumentDistiller(strategy=strategy, cache_dir=tmp_path)
    # Patch _get_llm_client to return the mock client
    d._get_llm_client = lambda profile: (mock_client, "test-model", "ollama")  # type: ignore[method-assign]
    return d, mock_client


class TestDistillAggressiveStrategy:
    def test_uses_llm_output(self, tmp_path: Path) -> None:
        distilled = "## Marie Curie\n\nNobel Prize Physics 1903, Chemistry 1911."
        d, _ = _make_distiller_with_mock_llm(tmp_path, "aggressive", distilled)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.distilled_text == distilled

    def test_llm_calls_counted(self, tmp_path: Path) -> None:
        d, _ = _make_distiller_with_mock_llm(tmp_path, "aggressive", "Core facts.")
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.llm_calls == 1

    def test_token_counts_captured(self, tmp_path: Path) -> None:
        d, _ = _make_distiller_with_mock_llm(
            tmp_path, "aggressive", "Core facts.", prompt_tokens=200, completion_tokens=30
        )
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.prompt_tokens == 200
        assert result.completion_tokens == 30

    def test_strategy_used(self, tmp_path: Path) -> None:
        d, _ = _make_distiller_with_mock_llm(tmp_path, "aggressive", "Facts.")
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.strategy_used == "aggressive"

    def test_result_cached(self, tmp_path: Path) -> None:
        d, mock_client = _make_distiller_with_mock_llm(tmp_path, "aggressive", "Distilled.")
        profile = _fake_profile()
        h = _content_hash(_SAMPLE_ARTICLE)
        r1 = d.distill(_SAMPLE_ARTICLE, h, profile)
        r2 = d.distill(_SAMPLE_ARTICLE, h, profile)
        assert r1.cache_hit is False
        assert r2.cache_hit is True
        # LLM called only once
        assert mock_client.chat.completions.create.call_count == 1

    def test_fallback_on_empty_llm_response(self, tmp_path: Path) -> None:
        """Empty LLM response → fallback to boilerplate_removal output."""
        d, _ = _make_distiller_with_mock_llm(tmp_path, "aggressive", "")
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        # Should get non-empty text (boilerplate_removal fallback)
        assert len(result.distilled_text) > 0

    def test_fallback_on_llm_error(self, tmp_path: Path) -> None:
        """LLM exception → fallback to boilerplate_removal, no stall."""
        d = DocumentDistiller(strategy="aggressive", cache_dir=tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("network error")
        d._get_llm_client = lambda profile: (mock_client, "test-model", "ollama")  # type: ignore[method-assign]
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.distilled_text  # non-empty
        assert result.cache_hit is False


class TestDistillModerateStrategy:
    def test_uses_llm_output(self, tmp_path: Path) -> None:
        distilled = "## Marie Curie\n\nDiscovered polonium and radium."
        d, _ = _make_distiller_with_mock_llm(tmp_path, "moderate", distilled)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.distilled_text == distilled
        assert result.strategy_used == "moderate"


class TestDistillConservativeStrategy:
    def test_uses_llm_output(self, tmp_path: Path) -> None:
        distilled = "# Marie Curie\n\nMarie Curie was a physicist.\n\n## Scientific Achievements\n\nDiscovered polonium."
        d, _ = _make_distiller_with_mock_llm(tmp_path, "conservative", distilled)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.distilled_text == distilled
        assert result.strategy_used == "conservative"


# ---------------------------------------------------------------------------
# DocumentDistiller.distill — section_aware strategy
# ---------------------------------------------------------------------------


class TestDistillSectionAware:
    def _make_section_aware_distiller(
        self,
        tmp_path: Path,
        classification: dict[str, str],
        summary: str = "Two sentence summary.",
    ) -> DocumentDistiller:
        d = DocumentDistiller(
            strategy="section_aware",
            cache_dir=tmp_path,
            section_types={
                "factual": "keep",
                "biographical": "summarize",
                "event": "keep",
                "reference": "remove",
                "navigation": "remove",
                "caption": "remove",
                "appendix": "remove",
            },
        )

        def mock_get_client(profile: Any) -> tuple[Any, str, str]:
            client = MagicMock()
            # First call: classify (returns JSON)
            # Subsequent calls: summarize
            responses = [
                _make_mock_llm_response(json.dumps(classification)),
            ] + [_make_mock_llm_response(summary)] * 10
            client.chat.completions.create.side_effect = responses
            return client, "test-model", "ollama"

        d._get_llm_client = mock_get_client  # type: ignore[method-assign]
        return d

    def test_removes_reference_sections(self, tmp_path: Path) -> None:
        classification = {
            "Marie Curie": "factual",
            "Early Life": "biographical",
            "Scientific Achievements": "factual",
            "References": "reference",
            "See Also": "navigation",
            "External Links": "navigation",
        }
        d = self._make_section_aware_distiller(tmp_path, classification)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert "References" not in result.distilled_text
        assert "See Also" not in result.distilled_text

    def test_keeps_factual_sections_verbatim(self, tmp_path: Path) -> None:
        classification = {
            "Marie Curie": "factual",
            "Early Life": "biographical",
            "Scientific Achievements": "factual",
            "References": "reference",
            "See Also": "navigation",
            "External Links": "navigation",
        }
        d = self._make_section_aware_distiller(tmp_path, classification)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert "polonium" in result.distilled_text

    def test_summarizes_biographical_sections(self, tmp_path: Path) -> None:
        classification = {
            "Marie Curie": "factual",
            "Early Life": "biographical",
            "Scientific Achievements": "factual",
            "References": "reference",
            "See Also": "navigation",
            "External Links": "navigation",
        }
        summary = "Marie Curie was born in Warsaw in 1867."
        d = self._make_section_aware_distiller(tmp_path, classification, summary=summary)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert summary in result.distilled_text

    def test_strategy_used(self, tmp_path: Path) -> None:
        d = self._make_section_aware_distiller(tmp_path, {})
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        assert result.strategy_used == "section_aware"

    def test_llm_calls_counted(self, tmp_path: Path) -> None:
        classification = {
            "Marie Curie": "factual",
            "Early Life": "biographical",  # 1 summarize call
            "Scientific Achievements": "factual",
            "References": "reference",
            "See Also": "navigation",
            "External Links": "navigation",
        }
        d = self._make_section_aware_distiller(tmp_path, classification)
        profile = _fake_profile()
        result = d.distill(_SAMPLE_ARTICLE, _content_hash(_SAMPLE_ARTICLE), profile)
        # At least 1 classify call + 1 summarize call = at least 2 LLM calls
        assert result.llm_calls >= 2


# ---------------------------------------------------------------------------
# DocumentDistiller.distill — budget_optimized strategy
# ---------------------------------------------------------------------------


class TestDistillBudgetOptimized:
    def test_skips_for_small_document(self, tmp_path: Path) -> None:
        """Small documents skip distillation and return original text."""
        d = DocumentDistiller(
            strategy="budget_optimized",
            cache_dir=tmp_path,
            budget_optimizer=BudgetOptimizer(min_triple_target=50),
        )
        small_text = "# Short\n\nThis is a short document under 100 kB."
        profile = _fake_profile()
        result = d.distill(small_text, _content_hash(small_text), profile)
        assert result.distilled_text == small_text
        assert "skip" in result.strategy_used
        assert result.llm_calls == 0

    def test_selects_aggressive_for_very_large_document(self, tmp_path: Path) -> None:
        """Very large documents get the aggressive strategy."""
        distilled_text = "Core facts only."
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_llm_response(distilled_text)

        d = DocumentDistiller(
            strategy="budget_optimized",
            cache_dir=tmp_path,
            budget_optimizer=BudgetOptimizer(min_triple_target=50),
        )
        d._get_llm_client = lambda profile: (mock_client, "test-model", "ollama")  # type: ignore[method-assign]

        large_text = "# Article\n\n" + "Word " * (1024 * 200)  # ~200k words ≈ 1 MB
        profile = _fake_profile()
        result = d.distill(large_text, _content_hash(large_text), profile)
        assert result.strategy_used == "aggressive"

    def test_bytes_removed_is_positive_for_large_doc(self, tmp_path: Path) -> None:
        distilled_text = "Core facts only."
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_llm_response(distilled_text)

        d = DocumentDistiller(
            strategy="budget_optimized",
            cache_dir=tmp_path,
            budget_optimizer=BudgetOptimizer(min_triple_target=50),
        )
        d._get_llm_client = lambda profile: (mock_client, "test-model", "ollama")  # type: ignore[method-assign]

        large_text = "# Article\n\n" + "Word " * (1024 * 200)
        profile = _fake_profile()
        result = d.distill(large_text, _content_hash(large_text), profile)
        assert result.distilled_bytes < result.original_bytes


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class TestDistillationCache:
    def test_cache_hit_returns_same_text(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        h = _content_hash(_SAMPLE_ARTICLE)
        r1 = d.distill(_SAMPLE_ARTICLE, h, profile)
        r2 = d.distill(_SAMPLE_ARTICLE, h, profile)
        assert r2.cache_hit is True
        assert r2.distilled_text == r1.distilled_text

    def test_different_content_hash_different_cache_entry(self, tmp_path: Path) -> None:
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        profile = _fake_profile()
        text1 = "# Doc 1\n\nContent A."
        text2 = "# Doc 2\n\nContent B."
        r1 = d.distill(text1, _content_hash(text1), profile)
        r2 = d.distill(text2, _content_hash(text2), profile)
        assert r1.cache_hit is False
        assert r2.cache_hit is False

    def test_different_strategies_different_cache_entries(self, tmp_path: Path) -> None:
        h = _content_hash(_SAMPLE_ARTICLE)
        d1 = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        d2 = DocumentDistiller(strategy="moderate", cache_dir=tmp_path)
        key1 = d1._cache_key(h, "boilerplate_removal")
        key2 = d2._cache_key(h, "moderate")
        assert key1 != key2

    def test_cache_dir_created_automatically(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "new_cache_dir" / "nested"
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=cache_dir)
        profile = _fake_profile()
        d.distill("# Test\n\nContent.", _content_hash("test"), profile)
        assert cache_dir.exists()

    def test_corrupt_cache_file_falls_through(self, tmp_path: Path) -> None:
        """A corrupt (unreadable) cache file should not crash — just re-run."""
        d = DocumentDistiller(strategy="boilerplate_removal", cache_dir=tmp_path)
        h = _content_hash(_SAMPLE_ARTICLE)
        cache_key = d._cache_key(h, "boilerplate_removal")
        cache_path = d._cache_path(cache_key)
        tmp_path.mkdir(parents=True, exist_ok=True)
        # Write a cache file then make it unreadable
        cache_path.write_text("cached content")
        cache_path.chmod(0o000)
        try:
            profile = _fake_profile()
            # Should not raise; falls back to re-running the strategy
            result = d.distill(_SAMPLE_ARTICLE, h, profile)
            assert result.distilled_text
        finally:
            cache_path.chmod(0o644)


# ---------------------------------------------------------------------------
# Pipeline integration — distillation stats
# ---------------------------------------------------------------------------


class TestDistillationPipelineStats:
    """Verify that the pipeline accumulates distillation stats correctly."""

    def test_distillation_stats_in_pipeline_run(self, tmp_path: Path) -> None:
        """Distillation enabled → pipeline stats include distillation keys."""
        from riverbank.pipeline import CompilerProfile, IngestPipeline

        article = "# Big Article\n\n" + "Fact sentence here. " * 50
        (tmp_path / "article.md").write_text(article)

        distill_cache = tmp_path / "distill_cache"

        profile = CompilerProfile(
            name="test-distil",
            distillation={
                "enabled": True,
                "strategy": "boilerplate_removal",
                "cache_dir": str(distill_cache),
            },
        )

        pipeline = IngestPipeline(db_engine=None)

        import unittest.mock as mock

        fake_conn = mock.MagicMock()
        fake_conn.__enter__ = lambda self: fake_conn
        fake_conn.__exit__ = mock.MagicMock(return_value=False)
        fake_conn.execute.return_value.fetchall.return_value = []
        fake_conn.execute.return_value.fetchone.return_value = None

        with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
            with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
                stats = pipeline.run(
                    corpus_path=str(tmp_path / "article.md"),
                    profile=profile,
                    dry_run=False,
                )

        assert "distillation_calls" in stats
        assert "distillation_cache_hits" in stats
        assert "distillation_bytes_removed" in stats
        assert "distillation_strategy_used" in stats
        assert stats["distillation_strategy_used"] == "boilerplate_removal"

    def test_distillation_disabled_stats_are_zero(self, tmp_path: Path) -> None:
        """Distillation disabled → distillation stats remain 0."""
        from riverbank.pipeline import CompilerProfile, IngestPipeline

        (tmp_path / "article.md").write_text("# Test\n\nContent here.")

        profile = CompilerProfile(
            name="test-no-distil",
            distillation={"enabled": False},
        )

        pipeline = IngestPipeline(db_engine=None)

        import unittest.mock as mock

        fake_conn = mock.MagicMock()
        fake_conn.__enter__ = lambda self: fake_conn
        fake_conn.__exit__ = mock.MagicMock(return_value=False)
        fake_conn.execute.return_value.fetchall.return_value = []
        fake_conn.execute.return_value.fetchone.return_value = None

        with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
            with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
                stats = pipeline.run(
                    corpus_path=str(tmp_path / "article.md"),
                    profile=profile,
                    dry_run=False,
                )

        assert stats["distillation_calls"] == 0
        assert stats["distillation_cache_hits"] == 0
        assert stats["distillation_bytes_removed"] == 0

    def test_distillation_cache_hit_on_second_run(self, tmp_path: Path) -> None:
        """Second ingest of same file → cache_hits=1."""
        from riverbank.pipeline import CompilerProfile, IngestPipeline

        article = "# Big Article\n\n" + "Fact sentence here. " * 50
        (tmp_path / "article.md").write_text(article)

        distill_cache = tmp_path / "distill_cache"

        profile = CompilerProfile(
            name="test-distil-cache",
            distillation={
                "enabled": True,
                "strategy": "boilerplate_removal",
                "cache_dir": str(distill_cache),
            },
        )

        pipeline = IngestPipeline(db_engine=None)

        import unittest.mock as mock

        def run_once() -> dict:
            fake_conn = mock.MagicMock()
            fake_conn.__enter__ = lambda self: fake_conn
            fake_conn.__exit__ = mock.MagicMock(return_value=False)
            fake_conn.execute.return_value.fetchall.return_value = []
            fake_conn.execute.return_value.fetchone.return_value = None
            with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
                with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
                    return pipeline.run(
                        corpus_path=str(tmp_path / "article.md"),
                        profile=profile,
                        dry_run=False,
                    )

        run_once()  # First run: populates cache
        stats2 = run_once()  # Second run: should hit cache
        assert stats2["distillation_cache_hits"] == 1
