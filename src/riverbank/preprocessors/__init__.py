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
        pre_computed_summary: str | None = None,
    ) -> PreprocessingResult | None:
        """Run preprocessing on *raw_text* and return a ``PreprocessingResult``.

        Args:
            raw_text: Raw document text to preprocess.
            profile: Compiler profile with ``preprocessing`` config.
            pre_computed_summary: If provided, skip the LLM summary call and
                use this value directly.  Enables Phase 2 pre-scan dedup
                (§3.6) — the corpus pre-scan already computed the summary so
                Phase 1 reuses it for free.

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

        # v0.12.0: merged preprocessing for short documents.
        # When the document is below merge_preprocessing_below_chars, combine
        # the document summary and entity catalog into a single LLM call.
        token_opt: dict = getattr(profile, "token_optimization", {})
        merge_threshold: int = token_opt.get("merge_preprocessing_below_chars", 0)
        should_merge = (
            merge_threshold > 0
            and len(raw_text) < merge_threshold
            and "document_summary" in strategies
            and "entity_catalog" in strategies
            and pre_computed_summary is None
        )

        if should_merge:
            merged_sum, merged_cat, pt, ct = self._extract_merged(raw_text, profile)
            summary = merged_sum or ""
            entity_catalog = merged_cat
            prompt_tokens_total += pt
            completion_tokens_total += ct
        else:
            if "document_summary" in strategies:
                if pre_computed_summary is not None:
                    # §3.6 Phase 2 pre-scan dedup: reuse cached summary, no LLM call
                    summary = pre_computed_summary
                else:
                    summary_text, pt, ct = self._extract_summary(raw_text, profile)
                    summary = summary_text or ""
                    prompt_tokens_total += pt
                    completion_tokens_total += ct

            if "entity_catalog" in strategies:
                max_entities: int = preprocessing_cfg.get("max_entities", 50)
                entity_catalog, pt, ct = self._extract_entity_catalog(raw_text, profile, max_entities)
                prompt_tokens_total += pt
                completion_tokens_total += ct

        # §Noise sections: propagate profile-configured noise section headings
        noise_sections: list[str] = preprocessing_cfg.get("noise_sections", [])

        return PreprocessingResult(
            summary=summary,
            entity_catalog=entity_catalog,
            noise_sections=noise_sections,
            prompt_tokens=prompt_tokens_total,
            completion_tokens=completion_tokens_total,
        )

    def build_extraction_prompt(
        self,
        result: PreprocessingResult | None,
        profile: Any,
        fragment_text: str = "",
    ) -> str:
        """Build an enriched extraction prompt from *result* and *profile*.

        Args:
            result: The preprocessing result containing summary and catalog.
            profile: The compiler profile.
            fragment_text: The fragment text being extracted.  When provided,
                the entity catalog is filtered to only include entries whose
                label or aliases appear in the fragment (§3.1 per-fragment
                entity catalog filtering).

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
            # §3.1 Per-fragment entity catalog filtering:
            # Only inject entities whose label or aliases appear in the fragment.
            if fragment_text:
                text_lower = fragment_text.lower()
                relevant = [
                    e for e in result.entity_catalog
                    if e.label.lower() in text_lower
                    or any(a.lower() in text_lower for a in e.aliases)
                ]
            else:
                relevant = result.entity_catalog

            if relevant:
                lines = ["ENTITY CATALOG (map all mentions to these canonical names):"]
                for entry in relevant:
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

    def _get_llm_client(self, profile: Any) -> tuple[Any, str, str]:
        """Return an (instructor_client, model_name, provider) triple from profile/settings."""
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

        return client, model_name, provider

    def _extract_merged(
        self,
        raw_text: str,
        profile: Any,
    ) -> tuple[str | None, list[EntityCatalogEntry], int, int]:
        """v0.12.0: Combine document summary + entity catalog into a single LLM call.

        Halves preprocessing LLM calls for short documents and saves ~2 000
        input tokens per document.

        Returns ``(summary, entity_catalog, prompt_tokens, completion_tokens)``.
        """
        _MERGED_PROMPT = """\
You are a knowledge graph ontologist. Analyze this document and produce:
1. A 2-3 sentence summary focusing on domain, main concepts, and purpose.
2. A canonical entity catalog of named entities, concepts, and technical terms.

Return a JSON object with:
- "summary": string (2-3 sentences, max 100 words)
- "entities": array of objects with keys:
    - canonical_name: lowercase-hyphenated identifier
    - label: human-readable name as it appears most often
    - entity_type: one of [Concept, System, Component, Process, Role, Configuration, Event]
    - aliases: list of other surface forms

Rules for entities:
- Include ONLY entities that appear in the text
- Maximum 50 entities
- Do NOT hallucinate entities absent from the text
- Merge variants: "Dataset", "data set", "datasets" → one entry with aliases
"""
        text_for_merged = raw_text[:10000] if len(raw_text) > 10000 else raw_text
        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _EntryIn(BaseModel):
                canonical_name: str
                label: str
                entity_type: str
                aliases: list[str] = []

            class _MergedOut(BaseModel):
                summary: str
                entities: list[_EntryIn] = []

            client, model_name, provider = self._get_llm_client(profile)
            extra_kwargs: dict = {"extra_body": {"keep_alive": "5m"}} if provider == "ollama" else {}
            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _MERGED_PROMPT},
                    {"role": "user", "content": text_for_merged},
                ],
                response_model=_MergedOut,
                **extra_kwargs,
            )
            usage = completion.usage if completion else None
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0

            preprocessing_cfg: dict = getattr(profile, "preprocessing", {})
            max_entities: int = preprocessing_cfg.get("max_entities", 50)
            entries: list[EntityCatalogEntry] = []
            for entry in result.entities[:max_entities]:
                safe_name = entry.canonical_name.lower().replace(" ", "-").replace("_", "-")
                valid_aliases = [a for a in entry.aliases if a and a in raw_text]
                entries.append(EntityCatalogEntry(
                    canonical_name=safe_name,
                    label=entry.label,
                    entity_type=entry.entity_type,
                    aliases=valid_aliases,
                ))

            logger.debug(
                "Merged preprocessing: summary=%d chars, %d entities, %d+%d tokens",
                len(result.summary),
                len(entries),
                prompt_tokens,
                completion_tokens,
            )
            return result.summary.strip(), entries, prompt_tokens, completion_tokens
        except Exception as exc:  # noqa: BLE001
            logger.warning("Merged preprocessing failed: %s", exc)
            return None, [], 0, 0

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

            client, model_name, provider = self._get_llm_client(profile)
            # §3.8 Ollama keep-alive: reuse KV cache across calls with identical prompts
            extra_kwargs: dict = {"extra_body": {"keep_alive": "5m"}} if provider == "ollama" else {}
            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SUMMARY_PROMPT},
                    {"role": "user", "content": text_for_summary},
                ],
                response_model=_Summary,
                **extra_kwargs,
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

            client, model_name, provider = self._get_llm_client(profile)
            # §3.8 Ollama keep-alive: reuse KV cache across calls with identical prompts
            extra_kwargs: dict = {"extra_body": {"keep_alive": "5m"}} if provider == "ollama" else {}
            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _ENTITY_CATALOG_PROMPT},
                    {"role": "user", "content": text_for_catalog},
                ],
                response_model=_Catalog,
                **extra_kwargs,
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


# ---------------------------------------------------------------------------
# Phase 2: Corpus-Level Preprocessing — hierarchical clustering
# ---------------------------------------------------------------------------


@dataclass
class ClusterSummary:
    """Summary of one document cluster produced by CorpusPreprocessor."""

    cluster_id: int
    label: str                          # e.g. "Architecture"
    doc_iris: list[str]                 # source IRIs of documents in this cluster
    summary: str                        # cluster-level 2-3 sentence summary
    entity_vocabulary: list[str] = field(default_factory=list)   # canonical ex: IRIs seen
    predicate_vocabulary: list[str] = field(default_factory=list) # predicates seen


@dataclass
class CorpusAnalysis:
    """Output of CorpusPreprocessor.analyze() — cached per corpus content hash."""

    corpus_summary: str                       # 2-3 sentences covering the whole corpus
    clusters: list[ClusterSummary]            # one entry per cluster
    doc_cluster_map: dict[str, int]           # source_iri → cluster_id
    corpus_hash: str = ""                     # hex hash of all source IRIs+hashes (for cache)
    _doc_summaries: dict = field(default_factory=dict, repr=False)  # source_iri → summary (internal)


_CORPUS_SUMMARY_PROMPT = """\
You are given summaries of all documents in a knowledge corpus.
Write a single cohesive summary (2-3 sentences) that describes:
- What domain or system the corpus covers
- The main topic areas present
- The intended audience or purpose

Return only the summary text. Maximum 120 words.
"""

_CLUSTER_SUMMARY_PROMPT = """\
You are given summaries of a group of related documents.
Write a short summary (2-3 sentences) that describes what this group has in common:
- The shared domain or sub-topic
- The main concepts and entity types involved
- The key relationships typically described

Also propose a short label (1-3 words, title-case) for this cluster, e.g. "Architecture", "Configuration", "Operations".

Return JSON with keys: label (string), summary (string).
"""


class CorpusPreprocessor:
    """Phase 2 preprocessing: corpus-level clustering and context generation.

    Runs once before any document preprocessing.  Embeds all document summaries,
    clusters them into topic groups, and generates:
      - A corpus-wide summary
      - A per-cluster summary with entity and predicate vocabulary

    These are injected into every fragment extraction call as a tiered context
    hierarchy:  CORPUS → CLUSTER → DOCUMENT → fragment.

    Requires ``sentence-transformers`` for embedding (``pip install riverbank[embed]``).
    Falls back gracefully when unavailable — Phase 1 doc-level context still works.

    Profile YAML::

        corpus_preprocessing:
          enabled: true
          min_docs: 20              # skip clustering below this corpus size
          target_cluster_size: 15  # target documents per cluster
          cache: true              # re-use analysis when corpus hash unchanged

    Usage::

        cp = CorpusPreprocessor(settings)
        analysis = cp.analyze(doc_summaries, profile)  # {source_iri: summary_text}
        context = cp.build_context(source_iri, analysis, doc_summary)
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        doc_summaries: dict[str, str],   # source_iri → summary_text
        profile: Any,
    ) -> CorpusAnalysis | None:
        """Embed + cluster *doc_summaries*, summarise each cluster, return analysis.

        Returns ``None`` when corpus is too small, clustering is disabled, or
        ``sentence-transformers`` is unavailable.
        """
        cfg: dict = getattr(profile, "corpus_preprocessing", {})
        if not cfg.get("enabled", False):
            return None

        min_docs: int = cfg.get("min_docs", 20)
        if len(doc_summaries) < min_docs:
            logger.info(
                "CorpusPreprocessor: corpus has %d docs (< min_docs=%d), skipping clustering",
                len(doc_summaries),
                min_docs,
            )
            return None

        try:
            embeddings = self._embed_summaries(doc_summaries, profile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CorpusPreprocessor: embedding failed (%s), skipping Phase 2", exc)
            return None

        target_size: int = cfg.get("target_cluster_size", 15)
        n_clusters = max(2, round(len(doc_summaries) / target_size))
        cluster_assignments = self._cluster(embeddings, n_clusters)

        # Build per-cluster doc lists
        cluster_docs: dict[int, list[str]] = {}
        for iri, cid in cluster_assignments.items():
            cluster_docs.setdefault(cid, []).append(iri)

        # Summarise each cluster
        clusters: list[ClusterSummary] = []
        for cid, iris in sorted(cluster_docs.items()):
            summaries_for_cluster = {iri: doc_summaries[iri] for iri in iris if iri in doc_summaries}
            cs = self._summarize_cluster(cid, iris, summaries_for_cluster, profile)
            clusters.append(cs)

        # Summarise the whole corpus
        corpus_summary = self._summarize_corpus(
            [cs.summary for cs in clusters], profile
        )

        corpus_hash = self._hash_corpus(doc_summaries)
        analysis = CorpusAnalysis(
            corpus_summary=corpus_summary,
            clusters=clusters,
            doc_cluster_map=cluster_assignments,
            corpus_hash=corpus_hash,
            _doc_summaries=dict(doc_summaries),
        )
        logger.info(
            "CorpusPreprocessor: analyzed %d docs → %d clusters",
            len(doc_summaries),
            len(clusters),
        )
        return analysis

    def build_context(
        self,
        source_iri: str,
        analysis: CorpusAnalysis | None,
        doc_summary: str = "",
    ) -> str:
        """Return a tiered CORPUS → CLUSTER → DOCUMENT context block for injection.

        Returns an empty string when *analysis* is None (Phase 2 disabled / unavailable).
        """
        if analysis is None:
            return ""

        parts: list[str] = []

        if analysis.corpus_summary:
            parts.append(f"CORPUS CONTEXT:\n{analysis.corpus_summary}")

        cluster_id = analysis.doc_cluster_map.get(source_iri)
        if cluster_id is not None:
            cluster = next((c for c in analysis.clusters if c.cluster_id == cluster_id), None)
            if cluster:
                cluster_ctx = f"CLUSTER CONTEXT ({cluster.label}):\n{cluster.summary}"
                if cluster.entity_vocabulary:
                    cluster_ctx += "\n  Expected entities: " + ", ".join(cluster.entity_vocabulary[:10])
                if cluster.predicate_vocabulary:
                    cluster_ctx += "\n  Expected predicates: " + ", ".join(cluster.predicate_vocabulary[:8])
                parts.append(cluster_ctx)

        if doc_summary:
            parts.append(f"DOCUMENT CONTEXT:\n{doc_summary}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Private: embedding
    # ------------------------------------------------------------------

    def _embed_summaries(
        self,
        doc_summaries: dict[str, str],
        profile: Any,
    ) -> dict[str, list[float]]:
        """Embed each document summary using sentence-transformers.

        Returns ``{source_iri: embedding_vector}``.
        Raises ``ImportError`` when sentence-transformers is absent.
        """
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for corpus clustering. "
                "Install with: pip install 'riverbank[embed]'"
            ) from exc

        embed_model: str = getattr(profile, "embed_model", "nomic-embed-text")
        # nomic-embed-text is Ollama-specific; fall back to a model ST ships with
        st_model = embed_model if "/" in embed_model or embed_model.startswith("all-") else "all-MiniLM-L6-v2"
        logger.debug("CorpusPreprocessor: embedding with %s", st_model)

        model = SentenceTransformer(st_model)
        iris = list(doc_summaries.keys())
        texts = [doc_summaries[iri] for iri in iris]
        vectors = model.encode(texts, show_progress_bar=False)
        return {iri: vec.tolist() for iri, vec in zip(iris, vectors)}

    # ------------------------------------------------------------------
    # Private: clustering
    # ------------------------------------------------------------------

    def _cluster(
        self,
        embeddings: dict[str, list[float]],
        n_clusters: int,
    ) -> dict[str, int]:
        """K-means cluster embeddings, return {source_iri: cluster_id}."""
        import numpy as np  # noqa: PLC0415

        try:
            from sklearn.cluster import KMeans  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "scikit-learn is required for corpus clustering. "
                "Install with: pip install 'riverbank[embed]'"
            ) from exc

        iris = list(embeddings.keys())
        X = np.array([embeddings[iri] for iri in iris])

        n = min(n_clusters, len(iris))
        km = KMeans(n_clusters=n, random_state=42, n_init="auto")
        labels = km.fit_predict(X)
        return {iri: int(label) for iri, label in zip(iris, labels)}

    # ------------------------------------------------------------------
    # Private: LLM summarisation
    # ------------------------------------------------------------------

    def _summarize_cluster(
        self,
        cluster_id: int,
        doc_iris: list[str],
        summaries: dict[str, str],
        profile: Any,
    ) -> ClusterSummary:
        """Ask the LLM to summarise a cluster and give it a label."""
        combined = "\n\n".join(
            f"Document: {iri}\n{summary}"
            for iri, summary in list(summaries.items())[:10]  # cap to avoid huge prompts
        )
        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _ClusterSummaryResponse(BaseModel):
                label: str
                summary: str

            client, model_name = self._get_llm_client(profile)
            resp, _completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _CLUSTER_SUMMARY_PROMPT},
                    {"role": "user", "content": combined},
                ],
                response_model=_ClusterSummaryResponse,
            )
            return ClusterSummary(
                cluster_id=cluster_id,
                label=resp.label.strip(),
                doc_iris=doc_iris,
                summary=resp.summary.strip(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("CorpusPreprocessor: cluster %d summarization failed: %s", cluster_id, exc)
            doc_names = [iri.rsplit("/", 1)[-1] for iri in doc_iris[:3]]
            return ClusterSummary(
                cluster_id=cluster_id,
                label=f"Cluster-{cluster_id}",
                doc_iris=doc_iris,
                summary=f"A group of {len(doc_iris)} related documents: {', '.join(doc_names)}…",
            )

    def _summarize_corpus(
        self,
        cluster_summaries: list[str],
        profile: Any,
    ) -> str:
        """Summarise the entire corpus from the cluster summaries."""
        combined = "\n\n".join(
            f"Cluster {i+1}: {s}" for i, s in enumerate(cluster_summaries)
        )
        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _CorpusSummary(BaseModel):
                summary: str

            client, model_name = self._get_llm_client(profile)
            resp, _completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _CORPUS_SUMMARY_PROMPT},
                    {"role": "user", "content": combined},
                ],
                response_model=_CorpusSummary,
            )
            return resp.summary.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("CorpusPreprocessor: corpus summarization failed: %s", exc)
            return f"A corpus of {len(cluster_summaries)} topic clusters."

    def _get_llm_client(self, profile: Any) -> tuple[Any, str]:
        """Return an (instructor_client, model_name) pair — same pattern as DocumentPreprocessor."""
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "instructor and openai are required for corpus preprocessing. "
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

    # ------------------------------------------------------------------
    # Private: cache key
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_corpus(doc_summaries: dict[str, str]) -> str:
        """Stable hash of the corpus content (IRI + summary pairs, sorted)."""
        import hashlib  # noqa: PLC0415

        h = hashlib.sha256()
        for iri in sorted(doc_summaries):
            h.update(iri.encode())
            h.update(doc_summaries[iri].encode())
        return h.hexdigest()[:16]
