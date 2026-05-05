"""Unit tests for the HeadingFragmenter."""
from __future__ import annotations

from riverbank.fragmenters.heading import DocumentFragment, HeadingFragmenter
from riverbank.parsers.markdown import MarkdownParser


def _parse_and_fragment(text: str) -> list[DocumentFragment]:
    parser = MarkdownParser()
    fragmenter = HeadingFragmenter()
    doc = parser.parse(text)
    return list(fragmenter.fragment(doc))


def test_single_heading_produces_one_fragment() -> None:
    text = "# Introduction\n\nThis is an introduction."
    fragments = _parse_and_fragment(text)
    assert len(fragments) == 1
    assert fragments[0].heading_path == ["Introduction"]


def test_two_h1_headings_produce_two_fragments() -> None:
    text = "# Part One\n\nContent one.\n\n# Part Two\n\nContent two."
    fragments = _parse_and_fragment(text)
    assert len(fragments) == 2
    assert fragments[0].heading_path == ["Part One"]
    assert fragments[1].heading_path == ["Part Two"]


def test_nested_headings_produce_correct_path() -> None:
    text = "# Chapter\n\n## Section\n\nBody text here."
    fragments = _parse_and_fragment(text)
    # Chapter heading and nested section
    keys = [f.fragment_key for f in fragments]
    assert "Chapter" in keys
    assert "Chapter > Section" in keys


def test_no_headings_yields_root_fragment() -> None:
    text = "Just some content without headings."
    fragments = _parse_and_fragment(text)
    assert len(fragments) == 1
    assert fragments[0].fragment_key == "root"


def test_empty_doc_yields_no_fragments() -> None:
    fragments = _parse_and_fragment("")
    assert fragments == []


def test_fragment_key_is_joinedpath() -> None:
    text = "# Top\n\n## Middle\n\nBody."
    fragments = _parse_and_fragment(text)
    keys = [f.fragment_key for f in fragments]
    assert "Top > Middle" in keys


def test_fragment_has_content_hash() -> None:
    text = "# Sec\n\nSome text."
    fragments = _parse_and_fragment(text)
    assert all(isinstance(f.content_hash, bytes) for f in fragments)
    assert all(len(f.content_hash) == 16 for f in fragments)


def test_fragment_text_contains_heading() -> None:
    text = "# Title\n\nDescription paragraph."
    fragments = _parse_and_fragment(text)
    assert len(fragments) == 1
    assert "Title" in fragments[0].text


def test_fragment_name() -> None:
    assert HeadingFragmenter.name == "heading"
