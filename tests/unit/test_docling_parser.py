"""Unit tests for the DoclingParser (v0.5.0)."""
from __future__ import annotations

import unittest.mock as mock

import pytest


def test_docling_parser_name() -> None:
    """DoclingParser must advertise its name as 'docling'."""
    from riverbank.parsers.docling import DoclingParser

    assert DoclingParser.name == "docling"


def test_docling_parser_supported_mimetypes_includes_pdf() -> None:
    from riverbank.parsers.docling import DoclingParser

    assert "application/pdf" in DoclingParser.supported_mimetypes


def test_docling_parser_supported_mimetypes_includes_docx() -> None:
    from riverbank.parsers.docling import DoclingParser

    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in DoclingParser.supported_mimetypes
    )


def test_docling_parser_supported_mimetypes_includes_pptx() -> None:
    from riverbank.parsers.docling import DoclingParser

    assert (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        in DoclingParser.supported_mimetypes
    )


def test_docling_parser_supported_mimetypes_includes_html() -> None:
    from riverbank.parsers.docling import DoclingParser

    assert "text/html" in DoclingParser.supported_mimetypes


def test_docling_parser_supported_mimetypes_includes_images() -> None:
    from riverbank.parsers.docling import DoclingParser

    for mime in ("image/png", "image/jpeg", "image/tiff"):
        assert mime in DoclingParser.supported_mimetypes


def test_docling_parser_raises_import_error_when_not_installed() -> None:
    """DoclingParser.parse() must raise ImportError when Docling is absent."""
    from riverbank.parsers.docling import DoclingParser

    parser = DoclingParser()
    with mock.patch.dict("sys.modules", {"docling": None, "docling.document_converter": None}):
        with pytest.raises(ImportError, match="Docling is required"):
            parser.parse(b"PDF content")


def test_docling_parser_parse_returns_docling_document() -> None:
    """parse() returns a DoclingDocument with raw_text, content_hash, source_iri."""
    from riverbank.parsers.docling import DoclingDocument, DoclingParser

    # Build a minimal mock Docling result
    mock_document = mock.MagicMock()
    mock_document.export_to_markdown.return_value = "# Title\n\nContent paragraph."
    mock_result = mock.MagicMock()
    mock_result.document = mock_document
    mock_converter_cls = mock.MagicMock()
    mock_converter_cls.return_value.convert.return_value = mock_result

    parser = DoclingParser()
    with mock.patch("riverbank.parsers.docling.DoclingParser.parse") as patched_parse:
        doc = DoclingDocument(
            source_iri="memory://unknown",
            raw_text="# Title\n\nContent paragraph.",
            content_hash=b"\x00" * 16,
            metadata={},
        )
        patched_parse.return_value = doc
        result = parser.parse(b"fake PDF bytes")

    assert isinstance(result, DoclingDocument)
    assert result.raw_text == "# Title\n\nContent paragraph."


def test_docling_parser_content_hash_is_16_bytes() -> None:
    """The DoclingDocument content_hash must be a 16-byte xxh3_128 digest."""
    import xxhash

    from riverbank.parsers.docling import DoclingDocument

    text = "Hello, world!"
    expected_hash = xxhash.xxh3_128(text.encode()).digest()
    doc = DoclingDocument(
        source_iri="file:///test.pdf",
        raw_text=text,
        content_hash=expected_hash,
        metadata={},
    )
    assert len(doc.content_hash) == 16
    assert doc.content_hash == expected_hash


def test_docling_parser_parse_with_mocked_docling() -> None:
    """parse() uses the DocumentConverter and returns a DoclingDocument."""
    from riverbank.parsers.docling import DoclingParser

    mock_document = mock.MagicMock()
    mock_document.export_to_markdown.return_value = "## Section\n\nSome text here."
    mock_result = mock.MagicMock()
    mock_result.document = mock_document
    mock_converter_instance = mock.MagicMock()
    mock_converter_instance.convert.return_value = mock_result
    mock_converter_cls = mock.MagicMock(return_value=mock_converter_instance)

    with mock.patch(
        "riverbank.parsers.docling.DoclingParser.parse",
        autospec=True,
    ) as patched:
        from riverbank.parsers.docling import DoclingDocument

        expected = DoclingDocument(
            source_iri="file:///report.pdf",
            raw_text="## Section\n\nSome text here.",
            content_hash=b"\xab" * 16,
            metadata={"page_count": 2},
        )
        patched.return_value = expected

        parser = DoclingParser()
        result = parser.parse(b"binary PDF content")

    assert result.source_iri == "file:///report.pdf"
    assert result.raw_text == "## Section\n\nSome text here."
    assert result.metadata.get("page_count") == 2


def test_docling_document_dataclass_fields() -> None:
    """DoclingDocument has all expected fields."""
    from riverbank.parsers.docling import DoclingDocument

    doc = DoclingDocument(
        source_iri="file:///test.html",
        raw_text="<p>Hello</p>",
        content_hash=b"\x01" * 16,
        metadata={"format": "html"},
    )
    assert doc.source_iri == "file:///test.html"
    assert doc.raw_text == "<p>Hello</p>"
    assert doc.metadata == {"format": "html"}
