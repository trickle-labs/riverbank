"""Corpus pre-scanner for adaptive semantic-chunking tuning (v0.15.0).

**Problem:** A single set of semantic chunking parameters (threshold, min/max
sentences, min/max fragment length) cannot be optimal for all corpus sizes.
A 5-file pilot corpus needs large, high-context chunks; a 500-file reference
corpus needs smaller, more focused chunks.

**Approach:** Scan the corpus *before* fragmentation — one stat-only pass that
reads every source file (no LLM calls, no DB writes).  Compute a
``CorpusScanResult`` with median word count, file-count, size distribution, and
vocabulary richness (unique/total word ratio).  Then apply a ``TuningBand``
(``small`` / ``medium`` / ``large``) to select defaults that are statistically
appropriate.

**Usage (automatic):** Set ``auto_tune: true`` inside ``semantic_chunking`` in
the profile YAML::

    semantic_chunking:
      auto_tune: true
      model: all-MiniLM-L6-v2
      # similarity_threshold, min/max sentences, min/max fragment_length
      # will be overridden by the pre-scan result

**Usage (manual override):** Any key you *do* specify in ``semantic_chunking``
will win over the auto-tuned value::

    semantic_chunking:
      auto_tune: true
      similarity_threshold: 0.80   # locks this; rest are auto-tuned

The scan result is also stored on the ``IngestPipeline`` for introspection
and surfaced in the progress callback as ``corpus_scan_done``.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning bands
# ---------------------------------------------------------------------------

TuningBand = Literal["small", "medium", "large"]

# Thresholds (inclusive upper bound of *median words per file*)
_SMALL_CORPUS_MAX_MEDIAN_WORDS = 400   # ≤ 400 median words/file
_MEDIUM_CORPUS_MAX_MEDIAN_WORDS = 1500  # 401 – 1 500

# Thresholds on file count
_SMALL_CORPUS_MAX_FILES = 30
_MEDIUM_CORPUS_MAX_FILES = 200

# Per-band parameter defaults
_BAND_DEFAULTS: dict[TuningBand, dict] = {
    "small": {
        # Small corpus: need maximum context per fragment — fewer, larger chunks
        "similarity_threshold": 0.80,
        "min_sentences_per_chunk": 3,  # lowered from 6 — table/list-heavy docs produce fewer prose sentences
        "max_sentences_per_chunk": 20,
        "min_fragment_length": 300,
        "max_fragment_length": 2000,
    },
    "medium": {
        # Medium corpus: balanced
        "similarity_threshold": 0.75,
        "min_sentences_per_chunk": 4,
        "max_sentences_per_chunk": 15,
        "min_fragment_length": 200,
        "max_fragment_length": 1500,
    },
    "large": {
        # Large corpus: focused, smaller chunks reduce per-call token cost
        "similarity_threshold": 0.70,
        "min_sentences_per_chunk": 2,
        "max_sentences_per_chunk": 10,
        "min_fragment_length": 100,
        "max_fragment_length": 1000,
    },
}

_WORD_RE = re.compile(r"\w+")


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CorpusScanResult:
    """Immutable statistics from a corpus pre-scan.

    Attributes:
        num_files: Total number of source files scanned.
        total_bytes: Sum of raw file sizes in bytes.
        mean_words: Arithmetic mean of per-file word counts.
        median_words: Median per-file word count.
        p90_words: 90th-percentile per-file word count.
        vocabulary_richness: Ratio of unique lowercase words to total words
            across the whole corpus (0.0 – 1.0).  Higher values indicate more
            varied vocabulary, which benefits from tighter chunking.
        band: Automatically selected tuning band (``small``/``medium``/``large``).
        tuned_params: Dict of parameter names → values derived from the scan.
            Only keys *not* manually specified in the profile are included.
    """

    num_files: int = 0
    total_bytes: int = 0
    mean_words: float = 0.0
    median_words: float = 0.0
    p90_words: float = 0.0
    vocabulary_richness: float = 0.0
    band: TuningBand = "medium"
    tuned_params: dict = field(default_factory=dict)

    @property
    def total_kb(self) -> float:
        return self.total_bytes / 1024

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class CorpusScanner:
    """Scan a corpus and derive adaptive chunking parameters.

    Usage::

        scanner = CorpusScanner()
        result = scanner.scan(paths)
        tuned = scanner.tune(result, profile_cfg=profile.semantic_chunking)
    """

    def scan(self, paths: Iterable[Path]) -> CorpusScanResult:
        """Read every file in *paths* and return a ``CorpusScanResult``.

        This is a read-only, single-threaded pass — no DB, no LLM, no side
        effects.  Files that cannot be read are silently skipped.
        """
        path_list = list(paths)
        if not path_list:
            logger.debug("CorpusScanner: no files to scan")
            return CorpusScanResult()

        word_counts: list[int] = []
        total_bytes = 0
        all_words: list[str] = []

        for p in path_list:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                logger.debug("CorpusScanner: skipping %s — %s", p, exc)
                continue

            total_bytes += p.stat().st_size
            words = _WORD_RE.findall(text.lower())
            word_counts.append(len(words))
            all_words.extend(words)

        if not word_counts:
            return CorpusScanResult()

        word_counts_sorted = sorted(word_counts)
        n = len(word_counts_sorted)
        mean_words = sum(word_counts_sorted) / n
        median_words = _percentile(word_counts_sorted, 50)
        p90_words = _percentile(word_counts_sorted, 90)
        richness = len(set(all_words)) / max(len(all_words), 1)

        result = CorpusScanResult(
            num_files=n,
            total_bytes=total_bytes,
            mean_words=mean_words,
            median_words=median_words,
            p90_words=p90_words,
            vocabulary_richness=richness,
            band=_select_band(n, median_words),
        )
        logger.info(
            "CorpusScanner: %d files, %.0f median words, %.0f p90 words, "
            "richness=%.2f → band=%s",
            result.num_files,
            result.median_words,
            result.p90_words,
            result.vocabulary_richness,
            result.band,
        )
        return result

    def tune(
        self,
        scan_result: CorpusScanResult,
        profile_cfg: Optional[dict] = None,
    ) -> dict:
        """Merge band defaults with any manual overrides from *profile_cfg*.

        Keys explicitly set in the profile always win.  The result can be
        passed directly to ``SemanticFragmenter`` as its configuration.

        Args:
            scan_result: Result from :meth:`scan`.
            profile_cfg: ``semantic_chunking`` dict from the compiler profile.
                Keys other than ``auto_tune`` and ``model`` are treated as
                manual overrides.

        Returns:
            A dict ready to use as the effective ``semantic_chunking`` config.
        """
        if profile_cfg is None:
            profile_cfg = {}

        band_defaults = dict(_BAND_DEFAULTS[scan_result.band])

        # Apply vocabulary-richness fine-tuning on top of band defaults.
        # Rich vocabulary → more diverse content → tighter boundaries help
        # (lower threshold).  Poor vocabulary → repetitive → relax threshold.
        richness = scan_result.vocabulary_richness
        if richness > 0.60:
            # Very rich — nudge threshold down by 0.03 (more splits)
            band_defaults["similarity_threshold"] = max(
                0.60,
                band_defaults["similarity_threshold"] - 0.03,
            )
        elif richness < 0.20:
            # Very repetitive — nudge threshold up by 0.03 (fewer splits)
            band_defaults["similarity_threshold"] = min(
                0.95,
                band_defaults["similarity_threshold"] + 0.03,
            )

        # Manual keys in profile_cfg override auto-tuned values.
        # Exclude control keys that are not chunking parameters.
        _CONTROL_KEYS = {"auto_tune", "model", "enabled"}
        overrides = {k: v for k, v in profile_cfg.items() if k not in _CONTROL_KEYS}
        effective = {**band_defaults, **overrides}

        # Store which keys were actually tuned (for logging / introspection)
        tuned_keys = {k: v for k, v in band_defaults.items() if k not in overrides}
        scan_result.tuned_params = tuned_keys

        logger.info(
            "CorpusScanner tune: band=%s, auto-tuned keys=%s, manual overrides=%s",
            scan_result.band,
            sorted(tuned_keys),
            sorted(overrides),
        )
        return effective


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[int | float], pct: float) -> float:
    """Return the *pct*-th percentile of a pre-sorted list (linear interpolation)."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = (pct / 100) * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(sorted_values[lo])
    frac = idx - lo
    return float(sorted_values[lo]) * (1 - frac) + float(sorted_values[hi]) * frac


def _select_band(num_files: int, median_words: float) -> TuningBand:
    """Select a :class:`TuningBand` based on corpus statistics."""
    if num_files <= _SMALL_CORPUS_MAX_FILES and median_words <= _SMALL_CORPUS_MAX_MEDIAN_WORDS:
        return "small"
    if num_files <= _MEDIUM_CORPUS_MAX_FILES and median_words <= _MEDIUM_CORPUS_MAX_MEDIAN_WORDS:
        return "medium"
    return "large"
