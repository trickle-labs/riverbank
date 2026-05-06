"""Docling-backed multi-format document parser (v0.5.0).

Handles PDF, DOCX, PPTX, HTML, and image files (OCR) via Docling ≥ 2.92.
Falls back gracefully when Docling is not installed.
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import xxhash

logger = logging.getLogger(__name__)

# Mapping of MIME type → temp-file suffix for in-memory content
_MIME_TO_SUFFIX: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/html": ".html",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}


@dataclass
class DoclingDocument:
    """A document parsed by Docling with extracted text and metadata."""

    source_iri: str
    raw_text: str
    content_hash: bytes
    metadata: dict = field(default_factory=dict)


class DoclingParser:
    """Multi-format document parser backed by Docling ≥ 2.92.

    Handles PDF, DOCX, PPTX, HTML, and image files (OCR). ``Docling`` is the
    default parser for non-Markdown sources; the ``MarkdownParser`` is still
    used for ``text/markdown`` and ``text/x-markdown`` MIME types.

    Raises ``ImportError`` when Docling is not installed — install the
    ``ingest`` extras: ``pip install 'riverbank[ingest]'``.
    """

    name = "docling"
    supported_mimetypes: frozenset[str] = frozenset(
        {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/html",
            "image/png",
            "image/jpeg",
            "image/tiff",
            "image/gif",
            "image/bmp",
            "image/webp",
        }
    )

    def parse(self, source: Any) -> DoclingDocument:
        """Parse a document using Docling and return a ``DoclingDocument``.

        Args:
            source: A ``SourceRecord`` (with ``.iri``, ``.content``,
                    ``.mime_type`` attributes), raw ``bytes``, or a file-path
                    string / ``Path``.

        Returns:
            ``DoclingDocument`` with ``raw_text``, ``content_hash``, and
            ``metadata`` populated.

        Raises:
            ImportError: If Docling is not installed.
        """
        try:
            from docling.document_converter import DocumentConverter  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "Docling is required for non-Markdown parsing. "
                "Install it with: pip install 'riverbank[ingest]'"
            ) from exc

        # Resolve IRI, content, and MIME type from the source argument.
        if hasattr(source, "iri"):
            iri: str = source.iri
            content: bytes | None = getattr(source, "content", None)
            mime_type: str = getattr(source, "mime_type", "")
        elif isinstance(source, bytes):
            iri = "memory://unknown"
            content = source
            mime_type = ""
        else:
            # Assume file path
            iri = Path(source).as_uri()
            content = None
            mime_type = ""

        if content is not None:
            # Write content to a temp file so Docling can parse it.
            suffix = _MIME_TO_SUFFIX.get(mime_type, "")
            if not suffix and iri:
                suffix = Path(iri.split("?")[0]).suffix or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                raw_text, metadata = _convert_file(tmp_path, DocumentConverter)
            finally:
                os.unlink(tmp_path)
        else:
            # iri is a file:// URI or plain path.
            if iri.startswith("file://"):
                file_path = Path(iri[7:])
            else:
                file_path = Path(iri)
            raw_text, metadata = _convert_file(str(file_path), DocumentConverter)

        content_hash = xxhash.xxh3_128(raw_text.encode()).digest()
        return DoclingDocument(
            source_iri=iri,
            raw_text=raw_text,
            content_hash=content_hash,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _convert_file(path: str, DocumentConverter: type) -> tuple[str, dict]:
    """Convert a file with Docling and return ``(markdown_text, metadata)``."""
    converter = DocumentConverter()
    result = converter.convert(path)
    text: str = result.document.export_to_markdown()
    metadata: dict = {
        "page_count": getattr(result.document, "page_count", None),
        "format": str(getattr(getattr(result, "input", None), "format", "")),
    }
    return text, metadata
