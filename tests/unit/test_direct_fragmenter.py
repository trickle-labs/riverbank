"""Unit tests for DirectFragmenter."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from riverbank.fragmenters.direct import DirectFragmenter, _DEFAULT_MAX_DOC_CHARS
from riverbank.fragmenters.heading import DocumentFragment, HeadingFragmenter
from riverbank.parsers.markdown import MarkdownParser


def _make_doc(text: str, iri: str = "file:///doc.md") -> MagicMock:
    doc = MagicMock()
    doc.raw_text = text
    doc.source_iri = iri
    return doc


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_short_doc_emits_single_root_fragment() -> None:
    fragmenter = DirectFragmenter(max_doc_chars=1000)
    frags = list(fragmenter.fragment(_make_doc("Hello world. This is a test.")))
    assert len(frags) == 1
    assert frags[0].fragment_key == "root"
    assert frags[0].text == "Hello world. This is a test."


def test_fragment_uses_whole_text() -> None:
    text = "# Heading\n\nParagraph one.\n\n## Sub\n\nParagraph two."
    fragmenter = DirectFragmenter(max_doc_chars=10000)
    frags = list(fragmenter.fragment(_make_doc(text)))
    assert len(frags) == 1
    assert frags[0].text == text


def test_content_hash_is_deterministic() -> None:
    text = "Stable text."
    fragmenter = DirectFragmenter()
    frag_a = list(fragmenter.fragment(_make_doc(text, "file:///a.md")))[0]
    frag_b = list(fragmenter.fragment(_make_doc(text, "file:///a.md")))[0]
    assert frag_a.content_hash == frag_b.content_hash


def test_different_text_gives_different_hash() -> None:
    fragmenter = DirectFragmenter()
    frag_a = list(fragmenter.fragment(_make_doc("Text A.")))[0]
    frag_b = list(fragmenter.fragment(_make_doc("Text B.")))[0]
    assert frag_a.content_hash != frag_b.content_hash


def test_empty_doc_yields_nothing() -> None:
    fragmenter = DirectFragmenter()
    frags = list(fragmenter.fragment(_make_doc("")))
    assert frags == []


def test_whitespace_only_doc_yields_nothing() -> None:
    fragmenter = DirectFragmenter()
    frags = list(fragmenter.fragment(_make_doc("   \n\t  ")))
    assert frags == []


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


def test_falls_back_when_doc_exceeds_max_doc_chars() -> None:
    long_text = "x" * 500
    fallback_frag = DocumentFragment(
        fragment_key="fallback",
        source_iri="file:///doc.md",
        content_hash=b"\x00" * 16,
        heading_path=["fallback"],
        text=long_text,
        char_start=0,
        char_end=len(long_text),
        heading_depth=0,
    )
    fallback = MagicMock()
    fallback.fragment.return_value = iter([fallback_frag])

    fragmenter = DirectFragmenter(max_doc_chars=100, fallback=fallback)
    frags = list(fragmenter.fragment(_make_doc(long_text)))

    fallback.fragment.assert_called_once()
    assert len(frags) == 1
    assert frags[0].fragment_key == "fallback"


def test_no_fallback_still_emits_large_doc() -> None:
    long_text = "y" * 50000
    fragmenter = DirectFragmenter(max_doc_chars=100, fallback=None)
    frags = list(fragmenter.fragment(_make_doc(long_text)))
    assert len(frags) == 1
    assert frags[0].text == long_text


def test_doc_exactly_at_limit_is_not_delegated() -> None:
    text = "a" * 100
    fallback = MagicMock()
    fragmenter = DirectFragmenter(max_doc_chars=100, fallback=fallback)
    frags = list(fragmenter.fragment(_make_doc(text)))
    fallback.fragment.assert_not_called()
    assert len(frags) == 1


# ---------------------------------------------------------------------------
# from_profile
# ---------------------------------------------------------------------------


def test_from_profile_reads_max_doc_chars() -> None:
    profile = MagicMock()
    profile.direct_extraction = {"max_doc_chars": 5000}
    fragmenter = DirectFragmenter.from_profile(profile)
    assert fragmenter._max_doc_chars == 5000


def test_from_profile_uses_default_when_config_absent() -> None:
    profile = MagicMock()
    profile.direct_extraction = {}
    fragmenter = DirectFragmenter.from_profile(profile)
    assert fragmenter._max_doc_chars == _DEFAULT_MAX_DOC_CHARS


def test_from_profile_passes_fallback() -> None:
    profile = MagicMock()
    profile.direct_extraction = {}
    fallback = HeadingFragmenter()
    fragmenter = DirectFragmenter.from_profile(profile, fallback=fallback)
    assert fragmenter._fallback is fallback


# ---------------------------------------------------------------------------
# Integration: works with real MarkdownParser doc
# ---------------------------------------------------------------------------


def test_real_parsed_doc() -> None:
    text = "# Intro\n\nRiverbank is a knowledge graph compiler.\n\n## Design\n\nIt uses LLMs."
    parser = MarkdownParser()
    doc = parser.parse(text)
    fragmenter = DirectFragmenter(max_doc_chars=10000)
    frags = list(fragmenter.fragment(doc))
    assert len(frags) == 1
    assert "Riverbank" in frags[0].text
