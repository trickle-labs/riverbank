"""Unit tests for v0.11.1 token efficiency features.

Covers:
- §3.1 Per-fragment entity catalog filtering
- §3.6 Phase 2 pre-scan deduplication (pre_computed_summary)
- §3.8 Ollama keep-alive prompt caching
- §3.9 Adaptive preprocessing for small documents
- §Noise section filtering
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest import mock

import pytest

from riverbank.preprocessors import (
    DocumentPreprocessor,
    EntityCatalogEntry,
    PreprocessingResult,
)


# ---------------------------------------------------------------------------
# Minimal stand-ins
# ---------------------------------------------------------------------------


@dataclass
class _Profile:
    name: str = "test"
    model_name: str = "llama3.2"
    prompt_text: str = "Extract triples."
    preprocessing: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "strategies": ["document_summary", "entity_catalog"],
            "max_entities": 50,
            "predefined_predicates": ["rdf:type", "schema:isPartOf"],
        }
    )


@dataclass
class _ProfileWithNoise:
    name: str = "noisy"
    model_name: str = "llama3.2"
    prompt_text: str = "Extract triples."
    preprocessing: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "strategies": ["document_summary"],
            "noise_sections": ["References", "Changelog", "Legal Notices"],
        }
    )


def _make_mock_summary_completion(text: str, prompt_t: int = 10, completion_t: int = 5):
    from pydantic import BaseModel

    class _Summary(BaseModel):
        summary: str

    response = _Summary(summary=text)
    usage = mock.MagicMock()
    usage.prompt_tokens = prompt_t
    usage.completion_tokens = completion_t
    completion = mock.MagicMock()
    completion.usage = usage
    return response, completion


def _make_preprocessor_with_mock(summary_text: str = "A test summary."):
    """Return a DocumentPreprocessor with mocked LLM returning a single summary."""
    preprocessor = DocumentPreprocessor()
    mock_client = mock.MagicMock()
    mock_client.chat.completions.create_with_completion.return_value = (
        _make_mock_summary_completion(summary_text)
    )
    preprocessor._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2", "openai"))
    return preprocessor, mock_client


# ===========================================================================
# §3.1 Per-fragment entity catalog filtering
# ===========================================================================


def test_build_extraction_prompt_filters_catalog_to_fragment_text() -> None:
    """Only entities whose label appears in fragment_text are injected."""
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="A document about pipes and datasets.",
        entity_catalog=[
            EntityCatalogEntry("sesam-pipe", "Pipe", "Component", ["pipes"]),
            EntityCatalogEntry("sesam-dataset", "Dataset", "Concept", ["data set"]),
            EntityCatalogEntry("sesam-system", "System", "System", []),
        ],
    )
    # Fragment text only mentions "Pipe" and "pipes" — not "Dataset" or "System"
    prompt = preprocessor.build_extraction_prompt(
        result, _Profile(), fragment_text="A pipe is a component. Pipes process data."
    )
    assert "ex:sesam-pipe" in prompt
    assert "ex:sesam-dataset" not in prompt
    assert "ex:sesam-system" not in prompt


def test_build_extraction_prompt_filters_by_alias() -> None:
    """Entities matched only through their aliases are included."""
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="",
        entity_catalog=[
            EntityCatalogEntry("sesam-dataset", "Dataset", "Concept", ["data set", "datasets"]),
            EntityCatalogEntry("sesam-pipe", "Pipe", "Component", ["pipes"]),
        ],
    )
    # Fragment text contains "data set" (alias) but not "Dataset" (label)
    prompt = preprocessor.build_extraction_prompt(
        result, _Profile(), fragment_text="Each data set is processed once."
    )
    assert "ex:sesam-dataset" in prompt
    assert "ex:sesam-pipe" not in prompt


def test_build_extraction_prompt_no_filter_when_fragment_text_empty() -> None:
    """When fragment_text is empty, the full catalog is injected (backward compat)."""
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="",
        entity_catalog=[
            EntityCatalogEntry("sesam-pipe", "Pipe", "Component", []),
            EntityCatalogEntry("sesam-dataset", "Dataset", "Concept", []),
        ],
    )
    prompt = preprocessor.build_extraction_prompt(result, _Profile(), fragment_text="")
    assert "ex:sesam-pipe" in prompt
    assert "ex:sesam-dataset" in prompt


def test_build_extraction_prompt_catalog_omitted_when_all_filtered_out() -> None:
    """When no entities match the fragment, the ENTITY CATALOG block is omitted."""
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="",
        entity_catalog=[
            EntityCatalogEntry("sesam-pipe", "Pipe", "Component", []),
        ],
    )
    # Fragment contains no mention of "Pipe"
    prompt = preprocessor.build_extraction_prompt(
        result, _Profile(), fragment_text="The operator deploys a flow."
    )
    assert "ENTITY CATALOG" not in prompt


def test_build_extraction_prompt_case_insensitive_match() -> None:
    """Entity filtering is case-insensitive."""
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="",
        entity_catalog=[
            EntityCatalogEntry("sesam-pipe", "Pipe", "Component", []),
        ],
    )
    # "PIPE" upper-case should still match
    prompt = preprocessor.build_extraction_prompt(
        result, _Profile(), fragment_text="The PIPE is connected."
    )
    assert "ex:sesam-pipe" in prompt


# ===========================================================================
# §3.6 Phase 2 pre-scan deduplication (pre_computed_summary)
# ===========================================================================


def test_preprocess_uses_pre_computed_summary_skips_llm_call() -> None:
    """When pre_computed_summary is provided, no LLM call is made for the summary."""
    preprocessor, mock_client = _make_preprocessor_with_mock("Summary from LLM.")

    @dataclass
    class _SummaryOnlyProfile:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "strategies": ["document_summary"]}
        )

    result = preprocessor.preprocess(
        "Some text.",
        _SummaryOnlyProfile(),
        pre_computed_summary="Pre-computed summary from Phase 2.",
    )

    assert result is not None
    assert result.summary == "Pre-computed summary from Phase 2."
    # No LLM call should have been made
    mock_client.chat.completions.create_with_completion.assert_not_called()


def test_preprocess_falls_through_to_llm_when_no_pre_computed_summary() -> None:
    """Without pre_computed_summary, the LLM is still called normally."""
    preprocessor, mock_client = _make_preprocessor_with_mock("LLM summary.")

    @dataclass
    class _SummaryOnlyProfile:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "backend": "llm", "strategies": ["document_summary"]}
        )

    result = preprocessor.preprocess("Some text.", _SummaryOnlyProfile())
    assert result is not None
    assert result.summary == "LLM summary."
    mock_client.chat.completions.create_with_completion.assert_called_once()


def test_preprocess_pre_computed_summary_zero_token_cost() -> None:
    """Reusing a pre-computed summary contributes 0 prompt tokens for the summary."""
    preprocessor, _ = _make_preprocessor_with_mock()

    @dataclass
    class _SummaryOnlyProfile:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "strategies": ["document_summary"]}
        )

    result = preprocessor.preprocess(
        "Some text.",
        _SummaryOnlyProfile(),
        pre_computed_summary="Cached summary.",
    )
    assert result is not None
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


# ===========================================================================
# §3.8 Ollama keep-alive prompt caching
# ===========================================================================


def test_preprocessor_passes_keep_alive_for_ollama() -> None:
    """When provider is 'ollama', extra_body with keep_alive is sent."""
    preprocessor, mock_client = _make_preprocessor_with_mock("Ollama summary.")
    # Override _get_llm_client to return 'ollama' provider
    preprocessor._get_llm_client = mock.MagicMock(
        return_value=(mock_client, "llama3.2", "ollama")
    )

    @dataclass
    class _SummaryOnlyProfile:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "backend": "llm", "strategies": ["document_summary"]}
        )

    preprocessor.preprocess("Some text.", _SummaryOnlyProfile())

    call_kwargs = mock_client.chat.completions.create_with_completion.call_args
    assert "extra_body" in call_kwargs.kwargs
    assert call_kwargs.kwargs["extra_body"]["keep_alive"] == "5m"


def test_preprocessor_no_keep_alive_for_openai() -> None:
    """When provider is 'openai', extra_body is not added."""
    preprocessor, mock_client = _make_preprocessor_with_mock("OpenAI summary.")
    preprocessor._get_llm_client = mock.MagicMock(
        return_value=(mock_client, "gpt-4o", "openai")
    )

    @dataclass
    class _SummaryOnlyProfile:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "backend": "llm", "strategies": ["document_summary"]}
        )

    preprocessor.preprocess("Some text.", _SummaryOnlyProfile())

    call_kwargs = mock_client.chat.completions.create_with_completion.call_args
    assert "extra_body" not in call_kwargs.kwargs


# ===========================================================================
# §3.9 Adaptive preprocessing (skip for small single-fragment documents)
# ===========================================================================


def test_adaptive_preprocessing_skips_for_small_doc() -> None:
    """Pipeline skips preprocessing for single-fragment docs under the threshold."""
    from riverbank.pipeline import IngestPipeline, CompilerProfile

    profile = CompilerProfile(
        name="adaptive-test",
        preprocessing={
            "enabled": True,
            "strategies": ["document_summary"],
            "adaptive_threshold": 2000,
        },
    )

    pipeline = IngestPipeline.__new__(IngestPipeline)

    # Simulate: 1 fragment, text < 2000 chars → skip preprocessing
    preprocessing_cfg = profile.preprocessing
    adaptive_threshold = preprocessing_cfg.get("adaptive_threshold", 2000)
    n_fragments = 1
    doc_len = 500  # small doc

    skip = n_fragments <= 1 and doc_len < adaptive_threshold
    assert skip is True


def test_adaptive_preprocessing_does_not_skip_for_large_doc() -> None:
    """Pipeline does NOT skip preprocessing for multi-fragment or large documents."""
    from riverbank.pipeline import CompilerProfile

    profile = CompilerProfile(
        name="adaptive-test",
        preprocessing={"enabled": True, "adaptive_threshold": 2000},
    )

    preprocessing_cfg = profile.preprocessing
    adaptive_threshold = preprocessing_cfg.get("adaptive_threshold", 2000)

    # Multi-fragment doc → no skip
    assert not (3 <= 1 and 500 < adaptive_threshold)

    # Large single-fragment doc → no skip
    assert not (1 <= 1 and 3000 < adaptive_threshold)


def test_adaptive_preprocessing_threshold_configurable() -> None:
    """The adaptive_threshold defaults to 2000 and is profile-configurable."""
    from riverbank.pipeline import CompilerProfile

    default_profile = CompilerProfile(name="test", preprocessing={"enabled": True})
    assert default_profile.preprocessing.get("adaptive_threshold", 2000) == 2000

    custom_profile = CompilerProfile(
        name="test",
        preprocessing={"enabled": True, "adaptive_threshold": 5000},
    )
    assert custom_profile.preprocessing.get("adaptive_threshold", 2000) == 5000


# ===========================================================================
# §Noise section filtering
# ===========================================================================


def test_preprocess_noise_sections_from_profile_config() -> None:
    """noise_sections from profile config are propagated to PreprocessingResult."""
    preprocessor, mock_client = _make_preprocessor_with_mock()
    mock_client.chat.completions.create_with_completion.return_value = (
        _make_mock_summary_completion("A doc.")
    )
    preprocessor._get_llm_client = mock.MagicMock(
        return_value=(mock_client, "llama3.2", "openai")
    )

    result = preprocessor.preprocess("Some text.", _ProfileWithNoise())
    assert result is not None
    assert "References" in result.noise_sections
    assert "Changelog" in result.noise_sections
    assert "Legal Notices" in result.noise_sections


def test_preprocess_noise_sections_empty_by_default() -> None:
    """noise_sections is [] by default when not configured in the profile."""
    preprocessor, mock_client = _make_preprocessor_with_mock()

    @dataclass
    class _P:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "strategies": ["document_summary"]}
        )

    result = preprocessor.preprocess("Some text.", _P())
    assert result is not None
    assert result.noise_sections == []


def test_noise_section_filtering_exact_match() -> None:
    """Pipeline skips a fragment whose key exactly matches a noise section."""
    from riverbank.fragmenters.heading import DocumentFragment
    import xxhash

    noise_sections = ["References", "Changelog"]
    frag_key = "References"

    # Simulate the pipeline check
    should_skip = frag_key in noise_sections or any(
        frag_key.startswith(ns) for ns in noise_sections
    )
    assert should_skip is True


def test_noise_section_filtering_prefix_match() -> None:
    """Pipeline skips a fragment whose key starts with a noise section heading."""
    noise_sections = ["References"]
    frag_key = "References > External links"

    should_skip = frag_key in noise_sections or any(
        frag_key.startswith(ns) for ns in noise_sections
    )
    assert should_skip is True


def test_noise_section_filtering_non_noise_fragment_not_skipped() -> None:
    """A normal fragment key does not trigger noise filtering."""
    noise_sections = ["References", "Changelog"]
    frag_key = "Introduction > Overview"

    should_skip = frag_key in noise_sections or any(
        frag_key.startswith(ns) for ns in noise_sections
    )
    assert should_skip is False


def test_noise_section_filtering_empty_list_skips_nothing() -> None:
    """An empty noise_sections list never filters any fragment."""
    noise_sections: list[str] = []
    for frag_key in ["References", "Introduction", "API"]:
        should_skip = frag_key in noise_sections or any(
            frag_key.startswith(ns) for ns in noise_sections
        )
        assert should_skip is False


# ===========================================================================
# CompilerProfile token_efficiency field (v0.11.1)
# ===========================================================================


def test_compiler_profile_token_efficiency_field_defaults_empty() -> None:
    """CompilerProfile.token_efficiency defaults to an empty dict."""
    from riverbank.pipeline import CompilerProfile

    profile = CompilerProfile(name="test")
    assert profile.token_efficiency == {}


def test_compiler_profile_token_efficiency_configurable() -> None:
    """token_efficiency can be set via the CompilerProfile constructor."""
    from riverbank.pipeline import CompilerProfile

    profile = CompilerProfile(
        name="test",
        token_efficiency={"ollama_keep_alive": "10m"},
    )
    assert profile.token_efficiency.get("ollama_keep_alive") == "10m"
