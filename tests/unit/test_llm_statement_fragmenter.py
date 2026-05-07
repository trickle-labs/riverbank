"""Unit tests for LLMStatementFragmenter."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from riverbank.fragmenters.llm_statement import LLMStatementFragmenter, _make_fragment


# ---------------------------------------------------------------------------
# _make_fragment helper
# ---------------------------------------------------------------------------


def test_make_fragment_sets_key_and_text() -> None:
    frag = _make_fragment(3, "file:///doc.md", "Paris is the capital of France.")
    assert frag.fragment_key == "stmt_3"
    assert frag.text == "Paris is the capital of France."
    assert frag.source_iri == "file:///doc.md"


def test_make_fragment_content_hash_is_deterministic() -> None:
    frag_a = _make_fragment(0, "iri", "Same text.")
    frag_b = _make_fragment(0, "iri", "Same text.")
    assert frag_a.content_hash == frag_b.content_hash


def test_make_fragment_different_texts_differ() -> None:
    frag_a = _make_fragment(0, "iri", "Text A.")
    frag_b = _make_fragment(0, "iri", "Text B.")
    assert frag_a.content_hash != frag_b.content_hash


# ---------------------------------------------------------------------------
# LLMStatementFragmenter.fragment — LLM mocked
# ---------------------------------------------------------------------------


def _make_doc(text: str, iri: str = "file:///doc.md") -> MagicMock:
    doc = MagicMock()
    doc.raw_text = text
    doc.source_iri = iri
    return doc


def test_fragment_yields_one_per_statement() -> None:
    fragmenter = LLMStatementFragmenter()
    statements = [
        "Water boils at 100°C at sea level.",
        "The Eiffel Tower is located in Paris.",
        "Marie Curie won two Nobel prizes.",
    ]
    with patch.object(fragmenter, "_call_llm", return_value=statements):
        frags = list(fragmenter.fragment(_make_doc("Some document text.")))

    assert len(frags) == 3
    assert frags[0].fragment_key == "stmt_0"
    assert frags[1].fragment_key == "stmt_1"
    assert frags[2].fragment_key == "stmt_2"
    assert frags[0].text == statements[0]


def test_fragment_falls_back_to_root_when_llm_returns_none() -> None:
    fragmenter = LLMStatementFragmenter()
    with patch.object(fragmenter, "_call_llm", return_value=None):
        frags = list(fragmenter.fragment(_make_doc("Document text.")))

    # When LLM fails, falls back to HeadingFragmenter which returns "root" key
    assert len(frags) == 1
    assert frags[0].fragment_key == "root"
    assert frags[0].text == "Document text."


def test_fragment_falls_back_to_root_when_llm_returns_empty_list() -> None:
    fragmenter = LLMStatementFragmenter()
    with patch.object(fragmenter, "_call_llm", return_value=[]):
        frags = list(fragmenter.fragment(_make_doc("Document text.")))

    assert len(frags) == 1


def test_fragment_yields_nothing_for_empty_document() -> None:
    fragmenter = LLMStatementFragmenter()
    with patch.object(fragmenter, "_call_llm", return_value=None):
        frags = list(fragmenter.fragment(_make_doc("   ")))

    assert frags == []


def test_fragment_respects_max_statements() -> None:
    fragmenter = LLMStatementFragmenter(max_statements=2)
    statements = [f"Fact number {i}." for i in range(10)]
    with patch.object(fragmenter, "_call_llm", return_value=statements):
        frags = list(fragmenter.fragment(_make_doc("text")))

    assert len(frags) == 2


def test_fragment_skips_blank_statements() -> None:
    fragmenter = LLMStatementFragmenter()
    statements = ["Valid fact.", "   ", "", "Another fact."]
    with patch.object(fragmenter, "_call_llm", return_value=statements):
        frags = list(fragmenter.fragment(_make_doc("text")))

    texts = [f.text for f in frags]
    assert "Valid fact." in texts
    assert "Another fact." in texts
    assert len(frags) == 2


# ---------------------------------------------------------------------------
# from_profile
# ---------------------------------------------------------------------------


def test_from_profile_reads_config() -> None:
    profile = MagicMock()
    profile.llm_statement_fragmentation = {
        "max_statements": 50,
        "max_doc_chars": 5000,
        "prompt": "Custom prompt.",
    }
    fragmenter = LLMStatementFragmenter.from_profile(profile)
    assert fragmenter._max_statements == 50
    assert fragmenter._max_doc_chars == 5000
    assert fragmenter._system_prompt == "Custom prompt."


def test_from_profile_uses_defaults_when_config_absent() -> None:
    profile = MagicMock()
    profile.llm_statement_fragmentation = {}
    fragmenter = LLMStatementFragmenter.from_profile(profile)
    assert fragmenter._max_statements == 200
    assert fragmenter._max_doc_chars == 20000


# ---------------------------------------------------------------------------
# _call_llm falls back gracefully when imports fail
# ---------------------------------------------------------------------------


def test_call_llm_returns_none_on_import_error() -> None:
    fragmenter = LLMStatementFragmenter()
    with patch.dict("sys.modules", {"instructor": None}):
        result = fragmenter._call_llm("Some text.")
    assert result is None
