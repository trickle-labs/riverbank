from __future__ import annotations

from typing import ClassVar, Iterator


class MarkdownParser:
    """Markdown document parser.

    Full implementation arrives in v0.2.0 using markdown-it-py.
    For Docling-based parsing of PDF/DOCX/HTML, see the ``docling`` plugin
    (arrives in v0.4.0).
    """

    name: ClassVar[str] = "markdown"
    supported_mimetypes: ClassVar[set[str]] = {"text/markdown", "text/x-markdown"}

    def parse(self, source: object) -> object:
        raise NotImplementedError("MarkdownParser not yet implemented — arriving in v0.2.0")
