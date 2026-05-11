"""Unit tests for DocumentPreprocessor (no LLM calls — all mocked)."""
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
# Minimal stand-in for CompilerProfile
# ---------------------------------------------------------------------------


@dataclass
class _Profile:
    name: str = "test"
    model_name: str = "llama3.2"
    prompt_text: str = "Extract triples."
    preprocessing: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "backend": "llm",
            "strategies": ["document_summary", "entity_catalog"],
            "max_entities": 50,
            "predefined_predicates": ["rdf:type", "rdfs:label", "schema:isPartOf"],
        }
    )


@dataclass
class _ProfileDisabled:
    name: str = "noop"
    preprocessing: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PreprocessingResult dataclass
# ---------------------------------------------------------------------------


def test_preprocessing_result_defaults() -> None:
    result = PreprocessingResult(summary="A summary.", entity_catalog=[])
    assert result.noise_sections == []
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


def test_preprocessing_result_token_fields() -> None:
    result = PreprocessingResult(
        summary="x",
        entity_catalog=[],
        prompt_tokens=100,
        completion_tokens=50,
    )
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50


# ---------------------------------------------------------------------------
# EntityCatalogEntry dataclass
# ---------------------------------------------------------------------------


def test_entity_catalog_entry_defaults() -> None:
    entry = EntityCatalogEntry(
        canonical_name="sesam-pipe",
        label="Pipe",
        entity_type="Component",
    )
    assert entry.aliases == []


def test_entity_catalog_entry_aliases() -> None:
    entry = EntityCatalogEntry(
        canonical_name="sesam-dataset",
        label="Dataset",
        entity_type="Concept",
        aliases=["data set", "datasets"],
    )
    assert "data set" in entry.aliases


# ---------------------------------------------------------------------------
# preprocess() returns None when disabled
# ---------------------------------------------------------------------------


def test_preprocess_returns_none_when_disabled() -> None:
    preprocessor = DocumentPreprocessor()
    result = preprocessor.preprocess("Some text.", _ProfileDisabled())
    assert result is None


def test_preprocess_returns_none_when_enabled_false() -> None:
    @dataclass
    class _P:
        preprocessing: dict = field(default_factory=lambda: {"enabled": False})

    preprocessor = DocumentPreprocessor()
    result = preprocessor.preprocess("Some text.", _P())
    assert result is None


# ---------------------------------------------------------------------------
# preprocess() with mocked LLM calls
# ---------------------------------------------------------------------------


def _make_mock_summary_completion(text: str, prompt_t: int = 10, completion_t: int = 5):
    """Return a (response_model, raw_completion) tuple like instructor returns."""
    from pydantic import BaseModel  # noqa: PLC0415

    class _Summary(BaseModel):
        summary: str

    response = _Summary(summary=text)
    usage = mock.MagicMock()
    usage.prompt_tokens = prompt_t
    usage.completion_tokens = completion_t
    completion = mock.MagicMock()
    completion.usage = usage
    return response, completion


def _make_mock_catalog_completion(entities: list[dict], prompt_t: int = 20, completion_t: int = 15):
    """Return a (response_model, raw_completion) tuple for entity catalog."""
    from pydantic import BaseModel  # noqa: PLC0415

    class _Entry(BaseModel):
        canonical_name: str
        label: str
        entity_type: str
        aliases: list[str] = []

    class _Catalog(BaseModel):
        entities: list[_Entry]

    response = _Catalog(entities=[_Entry(**e) for e in entities])
    usage = mock.MagicMock()
    usage.prompt_tokens = prompt_t
    usage.completion_tokens = completion_t
    completion = mock.MagicMock()
    completion.usage = usage
    return response, completion


@pytest.fixture
def preprocessor_with_mock_llm():
    """Return a DocumentPreprocessor whose LLM client is mocked."""
    preprocessor = DocumentPreprocessor()

    summary_return = _make_mock_summary_completion("This is a test document about Pipes and Datasets.")
    catalog_return = _make_mock_catalog_completion([
        {"canonical_name": "sesam-pipe", "label": "Pipe", "entity_type": "Component", "aliases": ["pipes"]},
        {"canonical_name": "sesam-dataset", "label": "Dataset", "entity_type": "Concept", "aliases": ["data set", "datasets"]},
    ])

    mock_client = mock.MagicMock()
    mock_client.chat.completions.create_with_completion.side_effect = [
        summary_return,
        catalog_return,
    ]
    preprocessor._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2", "openai"))
    return preprocessor


def test_preprocess_returns_result(preprocessor_with_mock_llm) -> None:
    result = preprocessor_with_mock_llm.preprocess(
        "Pipe processes data. Dataset stores data. data set is the same as datasets.",
        _Profile(),
    )
    assert result is not None
    assert isinstance(result, PreprocessingResult)
    assert "Pipes" in result.summary or "document" in result.summary


def test_preprocess_entity_catalog_count(preprocessor_with_mock_llm) -> None:
    result = preprocessor_with_mock_llm.preprocess(
        "Pipe processes data. Dataset stores data. data set is the same as datasets.",
        _Profile(),
    )
    assert result is not None
    assert len(result.entity_catalog) == 2


def test_preprocess_canonical_name_slugified(preprocessor_with_mock_llm) -> None:
    result = preprocessor_with_mock_llm.preprocess(
        "Pipe processes data. Dataset stores data. data set is the same as datasets.",
        _Profile(),
    )
    assert result is not None
    names = {e.canonical_name for e in result.entity_catalog}
    assert "sesam-pipe" in names
    assert "sesam-dataset" in names


def test_preprocess_alias_validated_against_text(preprocessor_with_mock_llm) -> None:
    """Aliases not present in the raw text must be stripped."""
    result = preprocessor_with_mock_llm.preprocess(
        # Only 'datasets' appears; 'data set' does NOT
        "Pipe processes datasets only.",
        _Profile(),
    )
    assert result is not None
    dataset_entry = next(e for e in result.entity_catalog if e.canonical_name == "sesam-dataset")
    assert "datasets" in dataset_entry.aliases
    assert "data set" not in dataset_entry.aliases


def test_preprocess_token_counts_accumulated(preprocessor_with_mock_llm) -> None:
    result = preprocessor_with_mock_llm.preprocess(
        "Pipe processes data. Dataset stores data. datasets.",
        _Profile(),
    )
    assert result is not None
    # summary: 10 prompt + 5 completion; catalog: 20 prompt + 15 completion
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 20


# ---------------------------------------------------------------------------
# preprocess() falls back gracefully on LLM failure
# ---------------------------------------------------------------------------


def test_preprocess_falls_back_on_summary_failure() -> None:
    preprocessor = DocumentPreprocessor()
    mock_client = mock.MagicMock()
    mock_client.chat.completions.create_with_completion.side_effect = RuntimeError("timeout")
    preprocessor._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2", "openai"))

    result = preprocessor.preprocess("Some text.", _Profile())
    # Should still return a result (not raise), with empty fields
    assert result is not None
    assert result.summary == ""
    assert result.entity_catalog == []
    assert result.prompt_tokens == 0


# ---------------------------------------------------------------------------
# build_extraction_prompt()
# ---------------------------------------------------------------------------


def test_build_extraction_prompt_none_returns_base() -> None:
    preprocessor = DocumentPreprocessor()
    profile = _Profile()
    prompt = preprocessor.build_extraction_prompt(None, profile)
    assert prompt == profile.prompt_text


def test_build_extraction_prompt_includes_summary() -> None:
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="This document describes Pipes and Datasets.",
        entity_catalog=[],
    )
    prompt = preprocessor.build_extraction_prompt(result, _Profile())
    assert "DOCUMENT CONTEXT" in prompt
    assert "Pipes and Datasets" in prompt


def test_build_extraction_prompt_includes_entity_catalog() -> None:
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(
        summary="Summary.",
        entity_catalog=[
            EntityCatalogEntry("sesam-pipe", "Pipe", "Component", ["pipes"]),
        ],
    )
    prompt = preprocessor.build_extraction_prompt(result, _Profile())
    assert "ENTITY CATALOG" in prompt
    assert "ex:sesam-pipe" in prompt
    assert "Component" in prompt


def test_build_extraction_prompt_includes_allowed_predicates() -> None:
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(summary="S.", entity_catalog=[])
    prompt = preprocessor.build_extraction_prompt(result, _Profile())
    assert "ALLOWED PREDICATES" in prompt
    assert "rdf:type" in prompt
    assert "schema:isPartOf" in prompt
    assert "ex:relatedTo" in prompt  # fallback always added


def test_build_extraction_prompt_no_duplicate_intro() -> None:
    """The generic 'You are a knowledge graph compiler' intro must not appear twice."""
    preprocessor = DocumentPreprocessor()
    result = PreprocessingResult(summary="S.", entity_catalog=[])
    prompt = preprocessor.build_extraction_prompt(result, _Profile())
    assert prompt.lower().count("you are a knowledge graph compiler") <= 1


# ---------------------------------------------------------------------------
# DocumentPreprocessor: only_summary strategy
# ---------------------------------------------------------------------------


def test_preprocess_summary_only_strategy() -> None:
    preprocessor = DocumentPreprocessor()
    summary_return = _make_mock_summary_completion("Summary only.")
    mock_client = mock.MagicMock()
    mock_client.chat.completions.create_with_completion.return_value = summary_return
    preprocessor._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2", "openai"))

    @dataclass
    class _SummaryOnlyProfile:
        preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "backend": "llm", "strategies": ["document_summary"]}
        )

    result = preprocessor.preprocess("Some text.", _SummaryOnlyProfile())
    assert result is not None
    assert result.summary == "Summary only."
    assert result.entity_catalog == []
    # Only one LLM call should have been made
    assert mock_client.chat.completions.create_with_completion.call_count == 1
