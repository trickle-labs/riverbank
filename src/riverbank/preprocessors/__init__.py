"""LLM document preprocessing for riverbank (v0.11.0).

Phase 1 — Document-level preprocessing (one LLM call per document):
  1. Document summary  — 2-3 sentences of domain context
  2. Entity catalog    — canonical entity names, types, and aliases

The ``PreprocessingResult`` is injected into the extraction prompt for every
fragment in that document, giving the extraction LLM:
  - domain grounding (what this document is about)
  - canonical entity names (eliminate terminology drift)
  - predefined predicates from the profile (eliminate invented predicates)

Phase 2 (planned) — Corpus-level clustering:
  - Embed all document summaries
  - Cluster similar documents (~15 per cluster)
  - Generate cluster + corpus summaries
  - Inject corpus → cluster → document context hierarchy into extraction

Usage::

    preprocessor = DocumentPreprocessor(settings)
    result = preprocessor.preprocess(raw_text, profile)
    enriched_prompt = preprocessor.build_extraction_prompt(result, profile)

"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class EntityCatalogEntry:
    """A canonical entity extracted during preprocessing."""

    canonical_name: str       # lowercase-hyphenated IRI slug, e.g. "sesam-dataset"
    label: str                # human-readable name as it appears in the document
    entity_type: str          # one of: Concept System Component Process Role Configuration Event
    aliases: list[str] = field(default_factory=list)


@dataclass
class PreprocessingResult:
    """Output of the LLM preprocessing pass for a single document."""

    summary: str                                   # 2-3 sentence document summary
    entity_catalog: list[EntityCatalogEntry]       # canonical entities with aliases
    noise_sections: list[str] = field(default_factory=list)  # heading paths to skip
    prompt_tokens: int = 0                         # tokens consumed by preprocessing calls
    completion_tokens: int = 0                     # tokens produced by preprocessing calls


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT = """\
Summarize this document in 2-3 sentences.
Focus on:
- What domain or system it describes
- The main concepts and their relationships
- The purpose of the documentation

Return only the summary text, nothing else. Maximum 100 words.
"""

_ENTITY_CATALOG_PROMPT = """\
You are a knowledge graph ontologist. Analyze this document and produce a \
canonical entity catalog.

For each named entity, concept, or technical term, provide:
- canonical_name: lowercase-hyphenated identifier (e.g. "sesam-dataset")
- label: human-readable name exactly as it appears most often in the document
- entity_type: one of [Concept, System, Component, Process, Role, Configuration, Event]
- aliases: list of other surface forms for the same entity found in the document

Rules:
- Include ONLY entities that appear in the text
- Maximum 50 entities
- Do NOT hallucinate entities absent from the text
- Merge variants: "Dataset", "data set", "datasets" → one entry with aliases
- Return a JSON array of objects with keys: canonical_name, label, entity_type, aliases

Return only the JSON array, nothing else.
"""


# ---------------------------------------------------------------------------
# Preprocessor
# ---------------------------------------------------------------------------

class DocumentPreprocessor:
    """Run a lightweight LLM preprocessing pass over a document before fragmentation.

    Produces a ``PreprocessingResult`` containing a document summary and an
    entity catalog.  These are used by ``build_extraction_prompt()`` to enrich
    the extraction prompt for every fragment in the document.

    Falls back gracefully when the LLM call fails — extraction continues with
    the unmodified base prompt.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preprocess(
        self,
        raw_text: str,
        profile: Any,
    ) -> PreprocessingResult | None:
        """Run preprocessing on *raw_text* and return a ``PreprocessingResult``.

        Returns ``None`` on failure so callers can fall back gracefully.
        """
        preprocessing_cfg: dict = getattr(profile, "preprocessing", {})
        if not preprocessing_cfg.get("enabled", False):
            return None

        strategies: list[str] = preprocessing_cfg.get(
            "strategies", ["document_summary", "entity_catalog"]
        )

        summary = ""
        entity_catalog: list[EntityCatalogEntry] = []
        prompt_tokens_total = 0
        completion_tokens_total = 0

        if "document_summary" in strategies:
            summary_text, pt, ct = self._extract_summary(raw_text, profile)
            summary = summary_text or ""
            prompt_tokens_total += pt
            completion_tokens_total += ct

        if "entity_catalog" in strategies:
            max_entities: int = preprocessing_cfg.get("max_entities", 50)
            entity_catalog, pt, ct = self._extract_entity_catalog(raw_text, profile, max_entities)
            prompt_tokens_total += pt
            completion_tokens_total += ct

        return PreprocessingResult(
            summary=summary,
            entity_catalog=entity_catalog,
            prompt_tokens=prompt_tokens_total,
            completion_tokens=completion_tokens_total,
        )

    def build_extraction_prompt(
        self,
        result: PreprocessingResult | None,
        profile: Any,
    ) -> str:
        """Build an enriched extraction prompt from *result* and *profile*.

        Falls back to the profile's base ``prompt_text`` when *result* is None.
        """
        base_prompt: str = getattr(profile, "prompt_text", "")
        if result is None:
            return base_prompt

        preprocessing_cfg: dict = getattr(profile, "preprocessing", {})
        predefined_predicates: list[str] = preprocessing_cfg.get(
            "predefined_predicates", []
        )

        parts: list[str] = ["You are a knowledge graph compiler.\n"]

        if result.summary:
            parts.append(f"DOCUMENT CONTEXT:\n{result.summary}\n")

        if result.entity_catalog:
            lines = ["ENTITY CATALOG (map all mentions to these canonical names):"]
            for entry in result.entity_catalog:
                alias_str = (
                    f' (aliases: {", ".join(repr(a) for a in entry.aliases)})'
                    if entry.aliases
                    else ""
                )
                lines.append(
                    f"  - ex:{entry.canonical_name} [{entry.entity_type}]"
                    f' label="{entry.label}"{alias_str}'
                )
            parts.append("\n".join(lines) + "\n")

        if predefined_predicates:
            pred_lines = ["ALLOWED PREDICATES (use only these):"]
            for p in predefined_predicates:
                pred_lines.append(f"  - {p}")
            pred_lines.append(
                "  - ex:relatedTo  (fallback for uncategorized relationships, confidence ≤ 0.6)"
            )
            parts.append("\n".join(pred_lines) + "\n")

        # Append the domain-specific extraction instructions from the profile
        # (strip the generic "You are a knowledge graph compiler" intro if
        #  the base prompt starts with it, since we already wrote that above)
        stripped = base_prompt.strip()
        if stripped.lower().startswith("you are a knowledge graph compiler"):
            # keep everything after the first sentence
            first_nl = stripped.find("\n")
            if first_nl != -1:
                stripped = stripped[first_nl:].strip()

        if stripped:
            parts.append(stripped)

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_llm_client(self, profile: Any) -> tuple[Any, str]:
        """Return an (instructor_client, model_name) pair from profile/settings."""
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "instructor and openai are required for preprocessing. "
                "Install with: pip install 'riverbank[ingest]'"
            ) from exc

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415
            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434/v1")
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(llm, "model", getattr(profile, "model_name", "llama3.2"))

        if provider == "copilot":
            mode = instructor.Mode.JSON
            client = instructor.from_openai(
                OpenAI(base_url="https://models.inference.ai.azure.com", api_key=api_key),
                mode=mode,
            )
        else:
            mode = (
                instructor.Mode.MD_JSON
                if provider in ("ollama", "vllm")
                else instructor.Mode.JSON
            )
            client = instructor.from_openai(
                OpenAI(base_url=api_base, api_key=api_key),
                mode=mode,
            )

        return client, model_name

    def _extract_summary(self, raw_text: str, profile: Any) -> tuple[str | None, int, int]:
        """Call the LLM to produce a 2-3 sentence document summary.

        Returns ``(summary_text, prompt_tokens, completion_tokens)``.
        All token counts are 0 when the call fails.
        """
        text_for_summary = raw_text[:8000] if len(raw_text) > 8000 else raw_text
        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _Summary(BaseModel):
                summary: str

            client, model_name = self._get_llm_client(profile)
            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SUMMARY_PROMPT},
                    {"role": "user", "content": text_for_summary},
                ],
                response_model=_Summary,
            )
            usage = completion.usage if completion else None
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            summary = result.summary.strip()
            logger.debug("Preprocessing summary (%d chars): %s…", len(summary), summary[:80])
            return summary, prompt_tokens, completion_tokens
        except Exception as exc:  # noqa: BLE001
            logger.warning("Preprocessing: summary extraction failed: %s", exc)
            return None, 0, 0

    def _extract_entity_catalog(
        self,
        raw_text: str,
        profile: Any,
        max_entities: int,
    ) -> tuple[list[EntityCatalogEntry], int, int]:
        """Call the LLM to produce a canonical entity catalog for the document.

        Returns ``(entries, prompt_tokens, completion_tokens)``.
        """
        text_for_catalog = raw_text[:12000] if len(raw_text) > 12000 else raw_text
        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _Entry(BaseModel):
                canonical_name: str
                label: str
                entity_type: str
                aliases: list[str] = []

            class _Catalog(BaseModel):
                entities: list[_Entry]

            client, model_name = self._get_llm_client(profile)
            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _ENTITY_CATALOG_PROMPT},
                    {"role": "user", "content": text_for_catalog},
                ],
                response_model=_Catalog,
            )
            usage = completion.usage if completion else None
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0

            entries: list[EntityCatalogEntry] = []
            for entry in result.entities[:max_entities]:
                safe_name = (
                    entry.canonical_name.lower()
                    .replace(" ", "-")
                    .replace("_", "-")
                )
                valid_aliases = [
                    a for a in entry.aliases if a and a in raw_text
                ]
                entries.append(
                    EntityCatalogEntry(
                        canonical_name=safe_name,
                        label=entry.label,
                        entity_type=entry.entity_type,
                        aliases=valid_aliases,
                    )
                )

            logger.debug(
                "Preprocessing: extracted %d entities from catalog", len(entries)
            )
            return entries, prompt_tokens, completion_tokens
        except Exception as exc:  # noqa: BLE001
            logger.warning("Preprocessing: entity catalog extraction failed: %s", exc)
            return [], 0, 0


# ---------------------------------------------------------------------------
# Few-Shot Golden Example Injector (Strategy 6)
# ---------------------------------------------------------------------------


@dataclass
class FewShotExample:
    """One verified (subject, predicate, object) triple used as a few-shot example."""

    subject: str         # e.g. "ex:sesam-pipe"
    predicate: str       # e.g. "schema:isPartOf"
    object_value: str    # e.g. "ex:sesam-system"
    confidence: float    # e.g. 0.95
    source: str = ""     # optional: which file this came from


@dataclass
class FewShotConfig:
    """Configuration for the few-shot injector, typically from the profile YAML."""

    enabled: bool = False
    source: str = "tests/golden/"          # directory of .ttl or .yaml example files
    max_examples: int = 3
    selection: str = "random"              # "random" | "fixed" | (future: "semantic")


class FewShotInjector:
    """Inject verified golden triples as few-shot examples into extraction prompts.

    The examples are loaded once and cached for the lifetime of the injector.
    They are prepended to the extraction prompt as ``EXAMPLES (correct triples
    for this corpus):``, giving the extraction LLM a concrete anchor for the
    expected output format and ontology.

    Falls back gracefully when no golden examples exist — the unmodified base
    prompt is returned.

    Supported source formats:
    - ``.yaml`` files with a ``triples:`` list  (riverbank golden format)
    - ``.ttl`` files are planned but not yet supported

    Profile YAML::

        few_shot:
          enabled: true
          source: tests/golden/
          max_examples: 3
          selection: random
    """

    def __init__(self, cfg: FewShotConfig | None = None) -> None:
        self._cfg: FewShotConfig = cfg or FewShotConfig()
        self._examples: list[FewShotExample] | None = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any) -> "FewShotInjector":
        """Create a ``FewShotInjector`` from a ``CompilerProfile``."""
        raw: dict = getattr(profile, "few_shot", {})
        if not raw or not raw.get("enabled", False):
            return cls(FewShotConfig(enabled=False))
        cfg = FewShotConfig(
            enabled=True,
            source=raw.get("source", "tests/golden/"),
            max_examples=int(raw.get("max_examples", 3)),
            selection=raw.get("selection", "random"),
        )
        return cls(cfg)

    def inject(self, prompt: str, profile: Any | None = None) -> str:
        """Return *prompt* with a FEW-SHOT EXAMPLES block prepended.

        Returns *prompt* unchanged when disabled or when no examples are found.
        """
        if not self._cfg.enabled:
            return prompt

        examples = self._load_examples()
        if not examples:
            return prompt

        selected = self._select(examples)
        if not selected:
            return prompt

        lines = ["FEW-SHOT EXAMPLES (correct triples for this corpus — use the same style):"]
        for ex in selected:
            lines.append(
                f"  {ex.subject}  {ex.predicate}  {ex.object_value}"
                f"  (confidence: {ex.confidence:.2f})"
            )
        examples_block = "\n".join(lines)

        return f"{examples_block}\n\n{prompt}"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_examples(self) -> list[FewShotExample]:
        """Load and cache examples from disk. Returns [] on any failure."""
        if self._examples is not None:
            return self._examples

        from pathlib import Path  # noqa: PLC0415

        source_path = Path(self._cfg.source)
        examples: list[FewShotExample] = []

        if not source_path.exists():
            logger.debug("FewShotInjector: source path %s does not exist", source_path)
            self._examples = examples
            return examples

        # Load from .yaml files
        for yaml_file in sorted(source_path.glob("**/*.yaml")):
            try:
                import yaml  # noqa: PLC0415

                data = yaml.safe_load(yaml_file.read_text())
                if not isinstance(data, dict):
                    continue
                for triple in data.get("triples", []):
                    examples.append(
                        FewShotExample(
                            subject=triple.get("subject", ""),
                            predicate=triple.get("predicate", ""),
                            object_value=triple.get("object_value", ""),
                            confidence=float(triple.get("confidence", 0.9)),
                            source=str(yaml_file),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("FewShotInjector: failed to load %s: %s", yaml_file, exc)

        logger.debug("FewShotInjector: loaded %d examples from %s", len(examples), source_path)
        self._examples = examples
        return examples

    def _select(self, examples: list[FewShotExample]) -> list[FewShotExample]:
        """Select up to ``max_examples`` examples according to the selection strategy."""
        if not examples:
            return []

        n = self._cfg.max_examples

        if self._cfg.selection == "fixed":
            return examples[:n]

        # Default: random
        import random  # noqa: PLC0415

        pool = list(examples)
        random.shuffle(pool)
        return pool[:n]
