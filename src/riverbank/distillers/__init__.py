"""LLM document distillation for riverbank (v0.15.2).

Distillation is an optional pre-fragmentation step that selects and compresses
the extractable content of a document before fragmentation.  Unlike raw
compression, distillation is a **content selection problem**: the step
identifies provably non-extractable sections (references, navigation, captions,
boilerplate) and removes them deterministically, then applies
strategy-specific LLM transformation to the remainder.

The distilled text replaces the original document text for all downstream
pipeline stages (fragmentation, preprocessing, extraction).  Because the
original ``content_hash`` is preserved on the ``SourceRecord``, fragment-level
deduplication continues to work correctly.

Pipeline position::

    parse → [distill] → coref → fragment → gate → extract → write

Profile YAML (full schema)::

    distillation:
      enabled: true
      strategy: moderate          # boilerplate_removal | aggressive | moderate |
                                  # conservative | section_aware | budget_optimized
      cache_dir: ~/.riverbank/distill_cache  # optional; created automatically
      model_provider: ollama      # optional: dedicated model for distillation
      model_name: gemma3:4b       # optional: small fast model is fine

      # For aggressive / moderate / conservative:
      target_size_bytes: 10240    # hint to the LLM

      # For section_aware:
      section_types:
        factual:      keep
        biographical: summarize
        event:        keep
        reference:    remove
        navigation:   remove
        caption:      remove

      # For budget_optimized:
      extraction_budget_usd: 1.00
      min_triple_target: 50
      sample_fragments: 3

Cache files are named::

    <xxh3_128_content_hash_hex>_<strategy>_<target_size_bytes>.md

so the same document distilled with different strategies or sizes produces
independent cached outputs.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_STRATEGY = "moderate"
_DEFAULT_CACHE_DIR = Path.home() / ".riverbank" / "distill_cache"

# Default target sizes per strategy (bytes).  0 means "no size hint".
_TARGET_SIZE_DEFAULTS: dict[str, int] = {
    "aggressive": 10_240,    # 10 kB
    "moderate": 30_720,      # 30 kB
    "conservative": 0,
    "boilerplate_removal": 0,
    "section_aware": 0,
    "budget_optimized": 0,
}

# Noise section headings to strip deterministically.
_NOISE_HEADINGS: frozenset[str] = frozenset({
    "references", "bibliography", "external links", "see also",
    "further reading", "notes", "footnotes", "appendix", "index",
    "sources", "citations", "links",
})

# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_PROMPT_AGGRESSIVE = """\
You are a document distillation assistant. Compress the following document to \
its core facts ONLY — essential, self-contained knowledge about the main subjects.

Guidelines:
- Output only the most important facts: identities, founding facts, key dates, \
  major achievements, significant events, quantitative records, important \
  relationships
- Remove ALL elaboration, context, biographical narrative, opinion, discussion, \
  navigation, references, footnotes, captions, hyperlinks, citation markers
- Target length: approximately {target_kb:.1f} kB ({target_size_bytes:,} bytes)
- Do NOT pad to reach the target — shorter is fine if all core facts fit
- Use clean Markdown with headings and bullet points

Return ONLY the distilled Markdown, no preamble, no explanation.\
"""

_PROMPT_MODERATE = """\
You are a document distillation assistant. Clean and compress the following \
document by removing non-extractable sections while preserving all factual \
content sections verbatim.

Guidelines:
- REMOVE: navigation, references, footnote markers, bibliography, external \
  links, image captions, "See also" / "Further reading" sections, inline \
  citation numbers like [1], boilerplate prose, table-of-contents entries
- KEEP verbatim: all sections with factual content — biographical facts, event \
  descriptions, statistics, relationships, dates, technical specifications
- For long elaborative passages: preserve factual sentences, remove pure \
  commentary
- Target length: approximately {target_kb:.1f} kB ({target_size_bytes:,} bytes)
- Use clean Markdown

Return ONLY the distilled Markdown, no preamble, no explanation.\
"""

_PROMPT_CONSERVATIVE = """\
You are a document distillation assistant. Remove ONLY the clearly \
non-informative sections from the following document.

Guidelines:
- REMOVE: navigation menus, reference lists, footnote sections, bibliography, \
  external links sections, image captions (lines starting with "![" or \
  "Figure"), inline citation numbers like [1] [[2]], horizontal separators, \
  table-of-contents entries
- KEEP UNCHANGED: all prose paragraphs, all factual sections, all headings \
  with content — even if the content seems low density
- Do NOT summarise, paraphrase, or reorder any content

Return ONLY the cleaned Markdown, no preamble, no explanation.\
"""

_PROMPT_SECTION_CLASSIFY = """\
Given the following list of section headings from a document, classify each \
heading as one of: factual, biographical, event, reference, navigation, \
caption, appendix.

Headings (one per line):
{headings}

Return a JSON object mapping each heading to its classification, like:
{{"Introduction": "factual", "References": "reference", "Life": "biographical"}}
Return ONLY the JSON object, no preamble.\
"""

_PROMPT_SECTION_SUMMARIZE = """\
Summarise the following section in 2-3 sentences, capturing only the most \
important factual content. Omit elaboration, narrative context, and \
biographical detail.

Section: {heading}
Content:
{content}

Return ONLY the 2-3 sentence summary.\
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DistillationResult:
    """Output of one distillation operation."""

    distilled_text: str
    """The distilled document text (Markdown)."""

    cache_hit: bool
    """True when the result was served from the on-disk cache."""

    strategy_used: str = ""
    """The strategy that produced this result."""

    original_bytes: int = 0
    """Byte length of the input text."""

    distilled_bytes: int = 0
    """Byte length of the distilled text."""

    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


# ---------------------------------------------------------------------------
# BoilerplateFilter — deterministic pre-pass (zero LLM cost)
# ---------------------------------------------------------------------------


class BoilerplateFilter:
    """Deterministic Markdown boilerplate stripper.

    Removes:

    - Heading sections matching a noise-heading list
      (references, footnotes, external links, etc.)
    - Inline citation markers (``[1]``, ``[[2]]``, ``(Smith, 2020)``)
    - Image / figure captions (lines starting with ``![`` or ``Figure``)
    - Hyperlink URLs — keeps display text only
    - Horizontal rule separators (``---``)

    Can be composed with any LLM-based strategy as a first-pass pre-filter.
    """

    def __init__(self, noise_headings: frozenset[str] | None = None) -> None:
        self._noise_headings = noise_headings or _NOISE_HEADINGS

    def filter(self, text: str) -> str:
        """Return the filtered Markdown text."""
        lines = text.split("\n")
        output_lines: list[str] = []
        skip_section = False

        for line in lines:
            heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
            if heading_match:
                heading_text = heading_match.group(2).strip().lower()
                heading_clean = re.sub(r"[^\w\s]", "", heading_text).strip()
                if heading_clean in self._noise_headings:
                    skip_section = True
                    continue
                else:
                    skip_section = False

            if skip_section:
                continue

            # Skip image/figure captions
            if re.match(r"^!\[", line) or re.match(r"^Figure\b", line, re.IGNORECASE):
                continue

            # Skip horizontal rules
            if re.match(r"^-{3,}\s*$", line) or re.match(r"^\*{3,}\s*$", line):
                continue

            # Strip inline citation markers: [1], [12], [[1]], [[12]]
            line = re.sub(r"\[\[?\d+\]?\]", "", line)
            # Strip author-year citations: (Smith, 2020) or (Smith et al., 2020)
            line = re.sub(
                r"\([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?,\s*\d{4}\)", "", line
            )
            # Convert hyperlinks [text](url) → text
            line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)

            output_lines.append(line)

        result = "\n".join(output_lines)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()


# ---------------------------------------------------------------------------
# SectionClassifier — outline-level LLM classifier for section_aware
# ---------------------------------------------------------------------------


class SectionClassifier:
    """Two-pass section processor for the ``section_aware`` strategy.

    Pass 1: send section headings to the LLM → classification map.
    Pass 2: for each section apply the action from ``section_types`` config:
    ``keep``, ``summarize``, or ``remove``.
    """

    def __init__(self, client: Any, model_name: str, provider: str) -> None:
        self._client = client
        self._model_name = model_name
        self._provider = provider

    def _extra_kwargs(self) -> dict:
        if self._provider == "ollama":
            return {"extra_body": {"keep_alive": "5m"}}
        return {}

    def classify_sections(self, headings: list[str]) -> dict[str, str]:
        """Return a mapping of heading → section type via one LLM call."""
        if not headings:
            return {}
        prompt = _PROMPT_SECTION_CLASSIFY.format(headings="\n".join(headings))
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                **self._extra_kwargs(),
            )
            content = (response.choices[0].message.content or "").strip()
            json_match = re.search(r"\{[\s\S]+\}", content)
            if json_match:
                return json.loads(json_match.group())
        except Exception as exc:  # noqa: BLE001
            logger.debug("SectionClassifier.classify: LLM call failed: %s", exc)
        return {}

    def summarize_section(
        self, heading: str, content: str
    ) -> tuple[str, int, int]:
        """Return ``(summary, prompt_tokens, completion_tokens)``."""
        prompt = _PROMPT_SECTION_SUMMARIZE.format(
            heading=heading, content=content[:4000]
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                **self._extra_kwargs(),
            )
            summary = (response.choices[0].message.content or "").strip()
            usage = getattr(response, "usage", None)
            pt = getattr(usage, "prompt_tokens", 0) if usage else 0
            ct = getattr(usage, "completion_tokens", 0) if usage else 0
            return summary or content, pt, ct
        except Exception as exc:  # noqa: BLE001
            logger.debug("SectionClassifier.summarize: LLM call failed: %s", exc)
            return content, 0, 0


# ---------------------------------------------------------------------------
# BudgetOptimizer — adaptive strategy selector for budget_optimized
# ---------------------------------------------------------------------------


class BudgetOptimizer:
    """Adaptive strategy selector for ``budget_optimized`` distillation.

    Algorithm:

    1. Estimate triples-per-kB using a fixed heuristic (0.5 triples/kB)
    2. Compute ideal distilled size: ``min_triple_target / triples_per_kB``
    3. If ideal size ≥ original size, return ``'skip'``
    4. Select strategy: ``conservative`` → ``moderate`` → ``aggressive``
       based on the ratio of ideal size to original size
    """

    def __init__(
        self,
        extraction_budget_usd: float = 1.0,
        min_triple_target: int = 50,
        sample_fragments: int = 3,
    ) -> None:
        self._extraction_budget_usd = extraction_budget_usd
        self._min_triple_target = min_triple_target
        self._sample_fragments = sample_fragments

    def select_strategy(self, original_bytes: int) -> str:
        """Select a strategy or ``'skip'`` if distillation is unnecessary."""
        _TRIPLES_PER_KB = 0.5
        original_kb = max(original_bytes / 1024, 1)
        ideal_kb = self._min_triple_target / _TRIPLES_PER_KB

        if ideal_kb >= original_kb:
            return "skip"

        ratio = ideal_kb / original_kb
        if ratio >= 0.60:
            return "conservative"
        elif ratio >= 0.25:
            return "moderate"
        return "aggressive"


# ---------------------------------------------------------------------------
# DocumentDistiller — main entry point
# ---------------------------------------------------------------------------


class DocumentDistiller:
    """Distill a document using one of six configurable strategies.

    Results are cached on disk at *cache_dir* (default
    ``~/.riverbank/distill_cache/``), keyed by the document's content hash,
    strategy name, and target size.  An unchanged document incurs zero LLM
    calls on subsequent ingestion runs.

    The distiller does **not** require ``instructor`` — it uses the raw
    ``openai`` client to produce free-form Markdown output, which avoids
    structured-output token overhead on large responses.

    Falls back to the original text on any LLM failure so the pipeline never
    stalls.

    Args:
        settings: riverbank settings object.
        strategy: One of ``boilerplate_removal``, ``aggressive``, ``moderate``,
            ``conservative``, ``section_aware``, ``budget_optimized``.
        target_size_bytes: Size hint passed to LLM prompts (bytes).
        cache_dir: On-disk cache directory.  Created automatically.
        model_provider: Optional LLM provider override.
        model_name: Optional LLM model override.
        section_types: Action map for ``section_aware`` strategy.
        budget_optimizer: Pre-built :class:`BudgetOptimizer` instance.
    """

    def __init__(
        self,
        settings: Any = None,
        strategy: str = _DEFAULT_STRATEGY,
        target_size_bytes: int | None = None,
        cache_dir: Path | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        section_types: dict[str, str] | None = None,
        budget_optimizer: BudgetOptimizer | None = None,
    ) -> None:
        self._settings = settings
        self._strategy = strategy
        self._target_size_bytes: int = (
            target_size_bytes
            if target_size_bytes is not None
            else _TARGET_SIZE_DEFAULTS.get(strategy, 0)
        )
        self._cache_dir: Path = cache_dir or _DEFAULT_CACHE_DIR
        self._model_provider_override = model_provider
        self._model_name_override = model_name
        self._section_types: dict[str, str] = section_types or {
            "factual": "keep",
            "biographical": "summarize",
            "event": "keep",
            "reference": "remove",
            "navigation": "remove",
            "caption": "remove",
            "appendix": "remove",
        }
        self._budget_optimizer = budget_optimizer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any, settings: Any = None) -> "DocumentDistiller":
        """Construct a :class:`DocumentDistiller` from a ``CompilerProfile``."""
        cfg: dict = getattr(profile, "distillation", {}) or {}
        raw_cache_dir = cfg.get("cache_dir")
        cache_dir: Path | None = None
        if raw_cache_dir:
            cache_dir = Path(raw_cache_dir).expanduser()

        strategy = cfg.get("strategy", _DEFAULT_STRATEGY)
        raw_target = cfg.get("target_size_bytes")
        target_size_bytes: int | None = (
            int(raw_target) if raw_target is not None else None
        )

        section_types: dict[str, str] | None = cfg.get("section_types")

        budget_optimizer: BudgetOptimizer | None = None
        if strategy == "budget_optimized":
            budget_optimizer = BudgetOptimizer(
                extraction_budget_usd=float(
                    cfg.get("extraction_budget_usd", 1.0)
                ),
                min_triple_target=int(cfg.get("min_triple_target", 50)),
                sample_fragments=int(cfg.get("sample_fragments", 3)),
            )

        return cls(
            settings=settings,
            strategy=strategy,
            target_size_bytes=target_size_bytes,
            cache_dir=cache_dir,
            model_provider=cfg.get("model_provider"),
            model_name=cfg.get("model_name"),
            section_types=section_types,
            budget_optimizer=budget_optimizer,
        )

    def distill(
        self,
        raw_text: str,
        content_hash: bytes,
        profile: Any,
    ) -> DistillationResult:
        """Return a distilled version of *raw_text*.

        Checks the disk cache first.  On a miss, runs the selected strategy
        and writes the result to cache before returning.

        Args:
            raw_text: The full source document text.
            content_hash: ``xxh3_128`` digest bytes of the source content.
                Used as part of the cache key.
            profile: The active ``CompilerProfile`` (used to resolve LLM config).

        Returns:
            A :class:`DistillationResult`.  On failure the result contains the
            original *raw_text* unchanged so the pipeline continues.
        """
        original_bytes = len(raw_text.encode("utf-8"))
        strategy = self._strategy

        # budget_optimized: select concrete strategy first
        if strategy == "budget_optimized":
            optimizer = self._budget_optimizer or BudgetOptimizer()
            selected = optimizer.select_strategy(original_bytes)
            if selected == "skip":
                logger.debug(
                    "Distillation (budget_optimized): document already small enough, skipping"
                )
                return DistillationResult(
                    distilled_text=raw_text,
                    cache_hit=False,
                    strategy_used="budget_optimized:skip",
                    original_bytes=original_bytes,
                    distilled_bytes=original_bytes,
                )
            strategy = selected
            logger.debug(
                "Distillation (budget_optimized): selected strategy=%s", strategy
            )

        cache_key = self._cache_key(content_hash, strategy)
        cached = self._load_cache(cache_key)
        if cached is not None:
            logger.debug(
                "Distillation: cache hit for %s (strategy=%s)", cache_key, strategy
            )
            return DistillationResult(
                distilled_text=cached,
                cache_hit=True,
                strategy_used=strategy,
                original_bytes=original_bytes,
                distilled_bytes=len(cached.encode("utf-8")),
            )

        # Run the selected strategy
        result_text, llm_calls, prompt_tokens, completion_tokens = self._run_strategy(
            raw_text, strategy, profile
        )

        if not result_text:
            logger.warning(
                "Distillation: strategy %r produced empty output — using original text",
                strategy,
            )
            result_text = raw_text

        self._save_cache(cache_key, result_text)
        distilled_bytes = len(result_text.encode("utf-8"))
        logger.info(
            "Distillation: %d → %d bytes (%.1f%% of original) strategy=%s cached",
            original_bytes,
            distilled_bytes,
            100 * distilled_bytes / max(original_bytes, 1),
            strategy,
        )
        return DistillationResult(
            distilled_text=result_text,
            cache_hit=False,
            strategy_used=strategy,
            original_bytes=original_bytes,
            distilled_bytes=distilled_bytes,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    # ------------------------------------------------------------------
    # Strategy dispatch
    # ------------------------------------------------------------------

    def _run_strategy(
        self, raw_text: str, strategy: str, profile: Any
    ) -> tuple[str, int, int, int]:
        """Run *strategy* and return ``(text, llm_calls, prompt_tokens, completion_tokens)``."""

        if strategy == "boilerplate_removal":
            filtered = BoilerplateFilter().filter(raw_text)
            return filtered, 0, 0, 0

        if strategy in ("aggressive", "moderate", "conservative"):
            return self._run_llm_strategy(raw_text, strategy, profile)

        if strategy == "section_aware":
            return self._run_section_aware(raw_text, profile)

        # Unknown strategy — fall back to boilerplate_removal
        logger.warning(
            "Distillation: unknown strategy %r — using boilerplate_removal", strategy
        )
        filtered = BoilerplateFilter().filter(raw_text)
        return filtered, 0, 0, 0

    def _run_llm_strategy(
        self, raw_text: str, strategy: str, profile: Any
    ) -> tuple[str, int, int, int]:
        """Run an LLM-based single-call strategy (aggressive/moderate/conservative)."""
        try:
            client, model_name, provider = self._get_llm_client(profile)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Distillation: could not build LLM client: %s", exc)
            return BoilerplateFilter().filter(raw_text), 0, 0, 0

        target_size = self._target_size_bytes or _TARGET_SIZE_DEFAULTS.get(strategy, 10_240)
        target_kb = target_size / 1024

        if strategy == "aggressive":
            system_prompt = _PROMPT_AGGRESSIVE.format(
                target_kb=target_kb, target_size_bytes=target_size
            )
        elif strategy == "moderate":
            system_prompt = _PROMPT_MODERATE.format(
                target_kb=target_kb, target_size_bytes=target_size
            )
        else:  # conservative
            system_prompt = _PROMPT_CONSERVATIVE

        extra_kwargs: dict = {}
        if provider == "ollama":
            extra_kwargs["extra_body"] = {"keep_alive": "5m"}

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": raw_text},
                ],
                **extra_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Distillation: LLM call failed: %s", str(exc)[:200])
            return BoilerplateFilter().filter(raw_text), 1, 0, 0

        distilled = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        if not distilled:
            logger.warning(
                "Distillation: LLM returned empty content for strategy=%s", strategy
            )
            return BoilerplateFilter().filter(raw_text), 1, prompt_tokens, completion_tokens

        return distilled, 1, prompt_tokens, completion_tokens

    def _run_section_aware(
        self, raw_text: str, profile: Any
    ) -> tuple[str, int, int, int]:
        """Two-pass section-aware distillation."""
        sections = _parse_sections(raw_text)
        if not sections:
            return raw_text, 0, 0, 0

        try:
            client, model_name, provider = self._get_llm_client(profile)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Distillation: could not build LLM client: %s", exc)
            return BoilerplateFilter().filter(raw_text), 0, 0, 0

        classifier = SectionClassifier(client, model_name, provider)

        # Pass 1: classify all headings in one call
        headings = [s["heading"] for s in sections if s["heading"]]
        classification = classifier.classify_sections(headings)
        llm_calls = 1 if headings else 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        # Pass 2: build output applying section_types actions
        output_parts: list[str] = []
        for sec in sections:
            heading = sec["heading"]
            content = sec["content"]
            sec_type = classification.get(heading, "factual")
            action = self._section_types.get(sec_type, "keep")

            if action == "remove":
                continue
            elif action == "summarize" and content.strip():
                summary, pt, ct = classifier.summarize_section(heading, content)
                llm_calls += 1
                total_prompt_tokens += pt
                total_completion_tokens += ct
                if heading:
                    output_parts.append(f"## {heading}\n\n{summary}")
                else:
                    output_parts.append(summary)
            else:  # keep
                if heading:
                    output_parts.append(f"## {heading}\n\n{content}".rstrip())
                else:
                    output_parts.append(content.rstrip())

        return (
            "\n\n".join(output_parts),
            llm_calls,
            total_prompt_tokens,
            total_completion_tokens,
        )

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, content_hash: bytes, strategy: str) -> str:
        """Return the cache key: ``<hash>_<strategy>_<target_bytes>``."""
        return f"{content_hash.hex()}_{strategy}_{self._target_size_bytes}"

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.md"

    def _load_cache(self, cache_key: str) -> str | None:
        path = self._cache_path(cache_key)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.debug("Distillation: cache read failed for %s: %s", path, exc)
        return None

    def _save_cache(self, cache_key: str, text: str) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(cache_key).write_text(text, encoding="utf-8")
        except OSError as exc:
            logger.debug("Distillation: cache write failed: %s", exc)

    # ------------------------------------------------------------------
    # LLM client helper
    # ------------------------------------------------------------------

    def _get_llm_client(self, profile: Any) -> tuple[Any, str, str]:
        """Return a ``(raw_openai_client, model_name, provider)`` triple."""
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("openai package not installed") from exc

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415
            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = self._model_provider_override or getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434")
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = self._model_name_override or getattr(llm, "model", "llama3.2")

        if provider in ("ollama", "vllm") and not api_base.endswith("/v1"):
            api_base = api_base.rstrip("/") + "/v1"

        if provider == "copilot":
            client = OpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=api_key,
            )
        else:
            client = OpenAI(base_url=api_base, api_key=api_key)

        return client, model_name, provider


# ---------------------------------------------------------------------------
# Section parser helper
# ---------------------------------------------------------------------------


def _parse_sections(text: str) -> list[dict[str, str]]:
    """Split Markdown text into a list of ``{heading, content}`` dicts.

    Sections without a heading (preamble before the first heading) are
    represented with an empty string heading.
    """
    sections: list[dict[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            content = "\n".join(current_lines).strip()
            if content or current_heading:
                sections.append({"heading": current_heading, "content": content})
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    content = "\n".join(current_lines).strip()
    if content or current_heading:
        sections.append({"heading": current_heading, "content": content})

    return sections
