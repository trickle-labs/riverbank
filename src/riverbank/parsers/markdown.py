from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import xxhash
from markdown_it import MarkdownIt


@dataclass
class ParsedDocument:
    """Result of parsing a Markdown source document."""

    source_iri: str
    raw_text: str
    tokens: list  # markdown-it Token list
    content_hash: bytes  # xxh3_128 digest


class MarkdownParser:
    """Markdown document parser using markdown-it-py.

    Accepts a ``SourceRecord`` (or any object with ``.iri`` and ``.content``
    attributes) and returns a ``ParsedDocument`` with the full markdown-it
    token stream.  The content hash is computed with xxh3_128 for use in the
    fragment-skip check.

    For Docling-based parsing of PDF/DOCX/HTML, see the ``docling`` plugin
    (arrives in v0.4.0).
    """

    name: ClassVar[str] = "markdown"
    supported_mimetypes: ClassVar[set[str]] = {"text/markdown", "text/x-markdown"}

    def __init__(self) -> None:
        self._md = MarkdownIt()

    def parse(self, source: object) -> ParsedDocument:
        """Parse a source record into a ``ParsedDocument``.

        ``source`` may be:
        - any object with ``.iri`` (str) and ``.content`` (bytes) attributes
          (e.g. ``SourceRecord`` from the filesystem connector)
        - a ``bytes`` object (source IRI will be ``"<unknown>"``)
        - a ``str`` object (encoded as UTF-8)
        """
        iri: str = getattr(source, "iri", "<unknown>")
        if hasattr(source, "content"):
            content: bytes = source.content  # type: ignore[union-attr]
        elif isinstance(source, bytes):
            content = source
        elif isinstance(source, str):
            content = source.encode("utf-8")
        else:
            content = b""

        raw_text = content.decode("utf-8", errors="replace")
        tokens = self._md.parse(raw_text)
        content_hash = xxhash.xxh3_128(content).digest()
        return ParsedDocument(
            source_iri=iri,
            raw_text=raw_text,
            tokens=tokens,
            content_hash=content_hash,
        )
