"""Direct (whole-document) fragmenter (v0.16.0).

Emits the entire document as a single ``DocumentFragment``, giving the
extraction LLM full document context in one call.

This is the highest-quality approach for concise documents (reports, articles,
README files) where heading-based splitting would break semantic context.
When the document exceeds *max_doc_chars*, falls back to ``HeadingFragmenter``
to avoid overflowing model context windows.

Profile YAML::

    fragmenter: direct
    direct_extraction:
      max_doc_chars: 12000   # fall back to heading fragmenter above this

Entry point::

    riverbank.fragmenters = direct = riverbank.fragmenters.direct:DirectFragmenter
"""
from __future__ import annotations

from typing import Any, ClassVar, Iterator

import xxhash

from riverbank.fragmenters.heading import DocumentFragment

_DEFAULT_MAX_DOC_CHARS = 12000


class DirectFragmenter:
    """Emit the whole document as a single fragment for direct LLM extraction.

    For short-to-medium documents, gives the extraction LLM full document
    context without any structural splitting.  When the document exceeds
    *max_doc_chars*, delegates to *fallback* (typically ``HeadingFragmenter``)
    to avoid overflowing model context windows.

    Args:
        max_doc_chars: Maximum document length in characters before fallback.
        fallback: Fragmenter to use when the document is too large.
    """

    name: ClassVar[str] = "direct"

    def __init__(
        self,
        max_doc_chars: int = _DEFAULT_MAX_DOC_CHARS,
        fallback: Any = None,
    ) -> None:
        self._max_doc_chars = max_doc_chars
        self._fallback = fallback

    @classmethod
    def from_profile(cls, profile: Any, fallback: Any = None) -> "DirectFragmenter":
        """Construct from a ``CompilerProfile``."""
        cfg: dict = getattr(profile, "direct_extraction", {}) or {}
        return cls(
            max_doc_chars=int(cfg.get("max_doc_chars", _DEFAULT_MAX_DOC_CHARS)),
            fallback=fallback,
        )

    def fragment(self, doc: object, **_kwargs: Any) -> Iterator[DocumentFragment]:
        """Yield one fragment containing the whole document text.

        Falls back to *fallback* when the document exceeds *max_doc_chars*.
        Yields nothing for empty documents.
        """
        source_iri: str = getattr(doc, "source_iri", "")
        raw_text: str = getattr(doc, "raw_text", "")

        if not raw_text.strip():
            return

        if len(raw_text) > self._max_doc_chars and self._fallback is not None:
            yield from self._fallback.fragment(doc)
            return

        content_hash = xxhash.xxh3_128(raw_text.encode()).digest()
        yield DocumentFragment(
            fragment_key="root",
            source_iri=source_iri,
            content_hash=content_hash,
            heading_path=["root"],
            text=raw_text,
            char_start=0,
            char_end=len(raw_text),
            heading_depth=0,
        )
