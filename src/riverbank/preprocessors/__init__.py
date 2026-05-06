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

        if "document_summary" in strategies:
            summary = self._extract_summary(raw_text, profile) or ""

        if "entity_catalog" in strategies:
            max_entities: int = preprocessing_cfg.get("max_entities", 50)
            entity_catalog = self._extract_entity_catalog(raw_text, profile, max_entities)

        return PreprocessingResult(
            summary=summary,
            entity_catalog=entity_catalog,
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

    def _extract_summary(self, raw_text: str, profile: Any) -> str | None:
        """Call the LLM to produce a 2-3 sentence document summary."""
        # Truncate very long documents for the summary call
        text_for_summary = raw_text[:8000] if len(raw_text) > 8000 else raw_text
        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _Summary(BaseModel):
                summary: str

            client, model_name = self._get_llm_client(profile)
            result = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SUMMARY_PROMPT},
                    {"role": "user", "content": text_for_summary},
                ],
                response_model=_Summary,
            )
            summary = result.summary.strip()
            logger.debug("Preprocessing summary (%d chars): %s…", len(summary), summary[:80])
            return summary
        except Exception as exc:  # noqa: BLE001
            logger.warning("Preprocessing: summary extraction failed: %s", exc)
            return None

    def _extract_entity_catalog(
        self,
        raw_text: str,
        profile: Any,
        max_entities: int,
    ) -> list[EntityCatalogEntry]:
        """Call the LLM to produce a canonical entity catalog for the document."""
        text_for_catalog = raw_text[:12000] if len(raw_text) > 12000 else raw_text
        try:
            import json  # noqa: PLC0415
            from pydantic import BaseModel  # noqa: PLC0415

            class _Entry(BaseModel):
                canonical_name: str
                label: str
                entity_type: str
                aliases: list[str] = []

            class _Catalog(BaseModel):
                entities: list[_Entry]

            client, model_name = self._get_llm_client(profile)
            result = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _ENTITY_CATALOG_PROMPT},
                    {"role": "user", "content": text_for_catalog},
                ],
                response_model=_Catalog,
            )

            entries: list[EntityCatalogEntry] = []
            for entry in result.entities[:max_entities]:
                # Validate canonical_name is URL-safe
                safe_name = (
                    entry.canonical_name.lower()
                    .replace(" ", "-")
                    .replace("_", "-")
                )
                # Validate aliases are present in the text
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
            return entries
        except Exception as exc:  # noqa: BLE001
            logger.warning("Preprocessing: entity catalog extraction failed: %s", exc)
            return []
