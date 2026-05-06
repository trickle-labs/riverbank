"""Semantic chunking fragmenter — embedding-based boundary detection (v0.14.0).

**Problem:** Heading-based fragmentation splits documents at structural
boundaries, which may not align with semantic topic transitions.  Two
consecutive paragraphs under the same heading may discuss completely different
concepts, producing "orphan" triples that lack context.

**Approach:** Embed each sentence via sentence-transformers, then split the
document where cosine similarity between adjacent sentences drops below a
configurable threshold.  The resulting fragments are semantically cohesive
units rather than arbitrary structural sections.

**Fallback:** When sentence-transformers is not installed or when the document
has very few sentences (< 3), falls back to treating the entire document as a
single fragment (equivalent to the "root" heading case in HeadingFragmenter).

Profile YAML::

    fragmenter: semantic   # select via profile (see pipeline.py)
    semantic_chunking:
      enabled: true
      model: all-MiniLM-L6-v2   # sentence-transformer model name
      similarity_threshold: 0.75 # split where cosine similarity drops below this
      min_sentences_per_chunk: 2  # never create fragments smaller than N sentences
      max_sentences_per_chunk: 20 # hard cap to prevent enormous fragments

Entry point::

    riverbank.fragmenters = semantic = riverbank.fragmenters.semantic:SemanticFragmenter
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterator

import xxhash

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_THRESHOLD = 0.75
_DEFAULT_MIN_SENTENCES = 2
_DEFAULT_MAX_SENTENCES = 20

# Sentence boundary characters (simple heuristic)
_SENT_END = frozenset(".!?")


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences using a simple punctuation heuristic.

    Returns the individual sentence strings with leading/trailing whitespace
    stripped.  Empty strings are excluded.

    This is intentionally a lightweight heuristic rather than a full NLP
    sentence splitter, so it does not require spaCy or NLTK.
    """
    sentences: list[str] = []
    current: list[str] = []
    for char in text:
        current.append(char)
        if char in _SENT_END:
            s = "".join(current).strip()
            if s:
                sentences.append(s)
            current = []
    # Flush any remaining text
    remainder = "".join(current).strip()
    if remainder:
        sentences.append(remainder)
    return [s for s in sentences if s]


def _cosine_similarity_1d(a: Any, b: Any) -> float:
    """Compute cosine similarity between two 1-D vectors."""
    try:
        import numpy as np  # noqa: PLC0415

        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)
    except Exception:  # noqa: BLE001
        return 0.0


def _make_fragment(
    chunk_idx: int,
    source_iri: str,
    text: str,
    char_start: int,
    char_end: int,
) -> Any:
    """Create a DocumentFragment for a semantic chunk."""
    from riverbank.fragmenters.heading import DocumentFragment  # noqa: PLC0415

    content_hash = xxhash.xxh3_128(text.encode()).digest()
    fragment_key = f"semantic_chunk_{chunk_idx}"
    return DocumentFragment(
        fragment_key=fragment_key,
        source_iri=source_iri,
        content_hash=content_hash,
        heading_path=[fragment_key],
        text=text,
        char_start=char_start,
        char_end=char_end,
        heading_depth=0,
    )


class SemanticFragmenter:
    """Split a document at semantic topic boundaries.

    Uses sentence-transformer embeddings to detect topic transitions: wherever
    cosine similarity between adjacent sentences drops below
    *similarity_threshold*, a new fragment begins.

    Falls back to a single "root" fragment when sentence-transformers is
    unavailable or when the document has < 3 sentences.

    Args:
        model_name: Sentence-transformer model to load (default all-MiniLM-L6-v2).
        similarity_threshold: Cosine similarity below which a boundary is placed
            (default 0.75).
        min_sentences_per_chunk: Minimum number of sentences before a split is
            allowed (default 2).
        max_sentences_per_chunk: Hard cap on sentences per fragment (default 20).
    """

    name: ClassVar[str] = "semantic"

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        similarity_threshold: float = _DEFAULT_THRESHOLD,
        min_sentences_per_chunk: int = _DEFAULT_MIN_SENTENCES,
        max_sentences_per_chunk: int = _DEFAULT_MAX_SENTENCES,
    ) -> None:
        self._model_name = model_name
        self._threshold = similarity_threshold
        self._min_sentences = max(1, min_sentences_per_chunk)
        self._max_sentences = max(self._min_sentences + 1, max_sentences_per_chunk)
        self._model: Any | None = None   # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any) -> "SemanticFragmenter":
        """Create a ``SemanticFragmenter`` from a ``CompilerProfile``."""
        cfg: dict = getattr(profile, "semantic_chunking", {})
        return cls(
            model_name=cfg.get("model", _DEFAULT_MODEL),
            similarity_threshold=float(cfg.get("similarity_threshold", _DEFAULT_THRESHOLD)),
            min_sentences_per_chunk=int(cfg.get("min_sentences_per_chunk", _DEFAULT_MIN_SENTENCES)),
            max_sentences_per_chunk=int(cfg.get("max_sentences_per_chunk", _DEFAULT_MAX_SENTENCES)),
        )

    def fragment(self, doc: object, **_kwargs: Any) -> Iterator[Any]:
        """Yield semantically cohesive ``DocumentFragment`` instances.

        Splits the document at topic boundaries detected via sentence embedding
        cosine similarity.  Falls back to a single root fragment when
        sentence-transformers is unavailable or the text is too short.
        """
        source_iri: str = getattr(doc, "source_iri", "")
        raw_text: str = getattr(doc, "raw_text", "")

        if not raw_text.strip():
            return

        sentences = _split_sentences(raw_text)
        if len(sentences) < 3:
            # Too few sentences to detect boundaries — emit single root fragment
            yield _make_fragment(0, source_iri, raw_text, 0, len(raw_text))
            return

        # Try to load the sentence-transformer model
        embeddings = self._embed(sentences)
        if embeddings is None:
            # Fallback: single root fragment
            logger.debug(
                "SemanticFragmenter: sentence-transformers unavailable — "
                "falling back to single root fragment"
            )
            yield _make_fragment(0, source_iri, raw_text, 0, len(raw_text))
            return

        # Detect split points
        boundaries = self._detect_boundaries(embeddings)

        # Build fragments from boundary indices
        yield from self._build_fragments(sentences, boundaries, source_iri, raw_text)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _embed(self, sentences: list[str]) -> Any | None:
        """Embed *sentences* and return a 2-D array (shape: N×D).

        Returns ``None`` when sentence-transformers is not available.
        """
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            if self._model is None:
                self._model = SentenceTransformer(self._model_name)
            return self._model.encode(sentences, normalize_embeddings=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("SemanticFragmenter: embedding failed — %s", exc)
            return None

    def _detect_boundaries(self, embeddings: Any) -> list[int]:
        """Return a list of 0-based sentence indices where new chunks begin.

        The first element is always 0 (start of document).
        """
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            return [0]

        n = len(embeddings)
        boundaries = [0]
        current_chunk_len = 0

        for i in range(1, n):
            current_chunk_len += 1
            # Hard cap
            if current_chunk_len >= self._max_sentences:
                boundaries.append(i)
                current_chunk_len = 0
                continue
            # Minimum chunk size guard
            if current_chunk_len < self._min_sentences:
                continue
            # Cosine similarity between adjacent sentences
            sim = float(np.dot(embeddings[i - 1], embeddings[i]))
            if sim < self._threshold:
                boundaries.append(i)
                current_chunk_len = 0

        return boundaries

    def _build_fragments(
        self,
        sentences: list[str],
        boundaries: list[int],
        source_iri: str,
        raw_text: str,
    ) -> Iterator[Any]:
        """Yield DocumentFragment objects for each chunk defined by *boundaries*."""
        boundaries_set = set(boundaries)
        chunk_idx = 0
        current_sentences: list[str] = []
        char_cursor = 0

        for i, sent in enumerate(sentences):
            if i in boundaries_set and current_sentences:
                # Emit the previous chunk
                chunk_text = " ".join(current_sentences)
                char_start = raw_text.find(current_sentences[0], char_cursor)
                if char_start == -1:
                    char_start = char_cursor
                char_end = char_start + len(chunk_text)
                char_cursor = char_end
                yield _make_fragment(chunk_idx, source_iri, chunk_text, char_start, char_end)
                chunk_idx += 1
                current_sentences = []

            current_sentences.append(sent)

        # Emit final chunk
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            char_start = raw_text.find(current_sentences[0], char_cursor)
            if char_start == -1:
                char_start = char_cursor
            char_end = min(char_start + len(chunk_text), len(raw_text))
            yield _make_fragment(chunk_idx, source_iri, chunk_text, char_start, char_end)
