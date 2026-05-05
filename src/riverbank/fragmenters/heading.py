from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterator

import xxhash


@dataclass
class DocumentFragment:
    """A stable section of a document delimited by heading boundaries.

    ``fragment_key`` is a ``" > "``-joined heading path and is stable across
    re-ingest as long as the heading hierarchy does not change.
    ``content_hash`` is xxh3_128 of the section text — used for fragment-skip.
    """

    fragment_key: str
    source_iri: str
    content_hash: bytes
    heading_path: list[str] = field(default_factory=list)
    text: str = ""
    char_start: int = 0
    char_end: int = 0
    heading_depth: int = 0


class HeadingFragmenter:
    """Splits a ParsedDocument at heading boundaries.

    One ``DocumentFragment`` is produced per heading section.  If the document
    has no headings at all, the entire document is emitted as a single fragment
    with ``fragment_key = "root"``.
    """

    name: ClassVar[str] = "heading"

    def fragment(self, doc: object) -> Iterator[DocumentFragment]:
        """Yield one ``DocumentFragment`` per heading section."""
        tokens: list = getattr(doc, "tokens", [])
        source_iri: str = getattr(doc, "source_iri", "")
        raw_text: str = getattr(doc, "raw_text", "")

        line_offsets = _build_line_offsets(raw_text)
        sections = _collect_sections(tokens, raw_text, line_offsets)

        if not sections:
            if raw_text.strip():
                yield _make_fragment("root", source_iri, [], raw_text, 0, len(raw_text), 0)
            return

        for heading_path, depth, char_start, char_end in sections:
            section_text = raw_text[char_start:char_end]
            if not section_text.strip():
                continue
            fragment_key = " > ".join(heading_path) if heading_path else "root"
            yield _make_fragment(
                fragment_key,
                source_iri,
                heading_path,
                section_text,
                char_start,
                char_end,
                depth,
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_line_offsets(text: str) -> list[int]:
    """Return character offsets for each line start (0-indexed lines).

    ``offsets[i]`` is the character offset of the first character on line ``i``.
    """
    offsets = [0]
    pos = 0
    for ch in text:
        pos += 1
        if ch == "\n":
            offsets.append(pos)
    return offsets


def _line_to_offset(line_offsets: list[int], line_number: int) -> int:
    """Convert a 0-indexed line number to a character offset."""
    if line_number < len(line_offsets):
        return line_offsets[line_number]
    return line_offsets[-1] if line_offsets else 0


def _collect_sections(
    tokens: list,
    raw_text: str,
    line_offsets: list[int],
) -> list[tuple[list[str], int, int, int]]:
    """Return ``(heading_path, depth, char_start, char_end)`` for each section."""
    total_chars = len(raw_text)
    sections: list[tuple[list[str], int, int, int]] = []
    current_path: list[str] = []
    current_depth: int = 0
    current_char_start: int = 0
    in_section: bool = False

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            depth = int(tok.tag[1])  # "h1" → 1, "h2" → 2, …

            # The next token is always "inline" with the heading text
            heading_text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                heading_text = tokens[i + 1].content.strip()

            heading_char_start = (
                _line_to_offset(line_offsets, tok.map[0]) if tok.map else 0
            )

            # Close the previous section
            if in_section:
                sections.append(
                    (
                        list(current_path),
                        current_depth,
                        current_char_start,
                        heading_char_start,
                    )
                )

            # Trim path to current depth and append new heading
            current_path = current_path[: depth - 1] + [heading_text]
            current_depth = depth
            current_char_start = heading_char_start
            in_section = True

        i += 1

    if in_section:
        sections.append(
            (list(current_path), current_depth, current_char_start, total_chars)
        )

    return sections


def _make_fragment(
    fragment_key: str,
    source_iri: str,
    heading_path: list[str],
    text: str,
    char_start: int,
    char_end: int,
    depth: int,
) -> DocumentFragment:
    content_hash = xxhash.xxh3_128(text.encode("utf-8")).digest()
    return DocumentFragment(
        fragment_key=fragment_key,
        source_iri=source_iri,
        content_hash=content_hash,
        heading_path=list(heading_path),
        text=text,
        char_start=char_start,
        char_end=char_end,
        heading_depth=depth,
    )
