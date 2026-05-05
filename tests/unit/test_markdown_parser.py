"""Unit tests for the MarkdownParser."""
from __future__ import annotations

from riverbank.parsers.markdown import MarkdownParser, ParsedDocument


def test_parse_returns_parsed_document() -> None:
    parser = MarkdownParser()
    text = "# Hello\n\nWorld"
    result = parser.parse(text)
    assert isinstance(result, ParsedDocument)
    assert result.raw_text == text
    assert result.source_iri == "<unknown>"


def test_parse_bytes_input() -> None:
    parser = MarkdownParser()
    content = b"# Title\n\nSome text."
    result = parser.parse(content)
    assert isinstance(result, ParsedDocument)
    assert result.raw_text == "# Title\n\nSome text."


def test_parse_source_record() -> None:
    """Accepts an object with .iri and .content attributes."""
    class FakeSource:
        iri = "file:///docs/test.md"
        content = b"# Doc\n\nBody text."

    parser = MarkdownParser()
    result = parser.parse(FakeSource())
    assert result.source_iri == "file:///docs/test.md"


def test_parse_produces_content_hash() -> None:
    parser = MarkdownParser()
    result = parser.parse(b"hello")
    assert isinstance(result.content_hash, bytes)
    assert len(result.content_hash) == 16  # xxh3_128 → 16 bytes


def test_parse_same_content_same_hash() -> None:
    parser = MarkdownParser()
    r1 = parser.parse(b"same content")
    r2 = parser.parse(b"same content")
    assert r1.content_hash == r2.content_hash


def test_parse_different_content_different_hash() -> None:
    parser = MarkdownParser()
    r1 = parser.parse(b"content A")
    r2 = parser.parse(b"content B")
    assert r1.content_hash != r2.content_hash
