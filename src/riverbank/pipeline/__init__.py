from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import xxhash
import yaml
from opentelemetry import trace as otel_trace

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiler profile
# ---------------------------------------------------------------------------

_DEFAULT_PROMPT = """\
You are a knowledge graph compiler.  Extract factual claims from the following
technical document section as RDF triples.

For each claim provide subject, predicate, object_value, confidence (0.0–1.0),
and an evidence span with exact character offsets and a verbatim excerpt.
Only extract claims directly supported by the text.
"""


@dataclass
class CompilerProfile:
    """A versioned compiler profile loaded from YAML or built programmatically."""

    name: str
    version: int = 1
    extractor: str = "noop"
    model_provider: str = "ollama"
    model_name: str = "llama3.2"
    embed_model: str = "nomic-embed-text"
    max_fragment_tokens: int = 2000
    prompt_text: str = _DEFAULT_PROMPT
    schema_json: dict = field(default_factory=dict)
    editorial_policy: dict = field(
        default_factory=lambda: {
            "min_fragment_length": 50,
            "max_fragment_length": 8000,
            "confidence_threshold": 0.7,
            "allowed_languages": ["en"],
        }
    )
    named_graph: str = "http://riverbank.example/graph/trusted"
    # v0.4.0: vocabulary graph and run mode sequence
    vocab_graph: str = "http://riverbank.example/graph/vocab"
    run_mode_sequence: list = field(default_factory=lambda: ["full"])
    competency_questions: list = field(default_factory=list)
    # v0.5.0: Singer tap configuration; NER and embedding model settings
    singer_taps: list = field(default_factory=list)
    ner_model: str = "en_core_web_sm"
    # v0.11.0: LLM preprocessing (document summary + entity catalog)
    preprocessing: dict = field(default_factory=dict)
    # v0.11.0: Few-shot golden example injection (Strategy 6)
    few_shot: dict = field(default_factory=dict)
    # v0.11.0: Corpus-level hierarchical clustering (Phase 2)
    corpus_preprocessing: dict = field(default_factory=dict)
    # v0.11.0: Post-2 self-critique verification pass
    verification: dict = field(default_factory=dict)
    # v0.11.1: Token efficiency settings (per-fragment filtering, keep-alive, etc.)
    token_efficiency: dict = field(default_factory=dict)
    # v0.12.0: Ontology-grounded extraction — closed-world predicate/class allowlists
    allowed_predicates: list = field(default_factory=list)
    allowed_classes: list = field(default_factory=list)
    # v0.12.0: Tentative graph IRI for per-triple confidence routing
    tentative_graph: str = "http://riverbank.example/graph/tentative"
    # v0.12.0: Extraction strategy (mode, safety cap, overlapping windows, coreference)
    extraction_strategy: dict = field(default_factory=dict)
    # v0.12.0: Token optimization (compact schema, budget manager, merged preprocessing)
    token_optimization: dict = field(default_factory=dict)
    # v0.12.1: Functional predicate hints — max_cardinality: 1 annotations
    predicate_constraints: dict = field(default_factory=dict)
    # v0.13.0: Tentative cleanup TTL in days (0 = disabled)
    tentative_ttl_days: int = 30
    # v0.13.1: Knowledge-prefix adapter — inject existing graph context at extraction time
    knowledge_prefix: dict = field(default_factory=dict)
    # v0.14.0: Constrained decoding — force JSON schema conformance for Ollama backends
    constrained_decoding: bool = False
    # v0.14.0: Fragmenter selection — "heading" (default), "semantic", or "llm_statement"
    fragmenter: str = "heading"
    # v0.14.0: Semantic chunking — embedding-based boundary detection
    # v0.15.0: Set auto_tune: true to derive parameters from a corpus pre-scan
    semantic_chunking: dict = field(default_factory=dict)
    # v0.16.0: LLM statement fragmentation — send full document to LLM, split into statements
    llm_statement_fragmentation: dict = field(default_factory=dict)
    # v0.16.0: Direct extraction — whole-document single-fragment config
    direct_extraction: dict = field(default_factory=dict)
    # v0.15.2: Document distillation — optional pre-fragmentation content-selection step
    distillation: dict = field(default_factory=dict)
    # v0.15.3: Vocabulary normalisation — post-extraction categorical/predicate normalisation
    vocabulary_normalisation: dict = field(default_factory=dict)
    # v0.16.0: Entity resolution — post-extraction owl:sameAs alias merging
    entity_resolution: dict = field(default_factory=dict)
    # v0.17.0: Extraction focus — precision vs recall trade-off at extraction layer
    # Options: "comprehensive" (default), "high_precision", "facts_only"
    extraction_focus: str = "comprehensive"
    # v0.14.0: SPARQL CONSTRUCT inference rules (list of SPARQL CONSTRUCT query strings)
    construct_rules: list = field(default_factory=list)
    # v0.14.0: SHACL shape validation
    shacl_validation: dict = field(default_factory=dict)
    # v0.14.0: OWL 2 RL forward-chaining
    owl_rl: dict = field(default_factory=dict)
    # v0.18.0: Predicate inference — LLM-driven schema discovery from documents
    predicate_inference: dict = field(default_factory=dict)
    # v0.15.4: Seed predicates — static domain-common predicates merged with
    # inference proposals before PREDICATE HINTS injection.  Applied even when
    # predicate_inference is disabled.
    seed_predicates: list = field(default_factory=list)
    # id is set after the profile is registered in the catalog DB
    id: Optional[int] = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CompilerProfile":
        """Load a compiler profile from a YAML file."""
        with open(path) as fh:
            data = yaml.safe_load(fh)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def default(cls) -> "CompilerProfile":
        return cls(name="default")


# ---------------------------------------------------------------------------
# Ingest pipeline
# ---------------------------------------------------------------------------


class IngestPipeline:
    """Orchestrates the full v0.2.0 ingestion pipeline.

    Pipeline stages (per source file):

    1. ``FilesystemConnector.discover()`` — enumerate source files
    2. Fragment hash check (xxh3_128) — skip unchanged fragments (0 LLM calls)
    3. ``MarkdownParser.parse()`` — parse source into markdown-it tokens
    4. ``HeadingFragmenter.fragment()`` — split into heading sections
    5. ``IngestGate.check()`` — editorial policy filter
    6. Extractor (``NoOpExtractor`` or ``InstructorExtractor``) — extract triples
    7. Citation validation — reject fabricated excerpts
    8. ``shacl_score()`` — route output to ``<trusted>`` or ``<draft>`` named graph
    9. ``load_triples_with_confidence()`` — write facts to pg_ripple
    10. Catalog recording — upsert source/fragment, insert run record
    """

    def __init__(
        self,
        settings: Any = None,
        db_engine: Any = None,
        set_overrides: list[str] | None = None,
    ) -> None:
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415

            overrides: dict | None = None
            if set_overrides:
                overrides = {}
                for item in set_overrides:
                    if "=" not in item:
                        raise ValueError(f"--set value must be in key=value format, got: {item!r}")
                    key, _, value = item.partition("=")
                    overrides[key.strip()] = value.strip()

            settings = get_settings(overrides=overrides)
        self._settings = settings
        self._db_engine = db_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        corpus_path: str,
        profile: Optional[CompilerProfile] = None,
        dry_run: bool = False,
        mode: str = "full",
        force: bool = False,
        progress_callback: Callable[[str, dict], None] | None = None,
    ) -> dict:
        """Run the pipeline against a corpus directory or single file.

        ``mode`` controls the extraction strategy:

        * ``"full"`` (default) — standard relationship extraction, writes to
          ``profile.named_graph``.
        * ``"vocabulary"`` — entity extraction only; writes ``skos:Concept``
          triples to ``profile.vocab_graph`` for use as a context constraint
          in subsequent full passes.

        When the profile declares ``run_mode_sequence: ['vocabulary', 'full']``,
        calling ``run()`` without an explicit ``mode`` will execute both passes
        in sequence (vocabulary first, full second) and accumulate stats.

        Returns a stats dict:
        ``fragments_processed``, ``fragments_skipped``, ``fragments_skipped_hash``,
        ``triples_written``, ``llm_calls``, ``prompt_tokens``, ``completion_tokens``,
        ``cost_usd``, ``errors``, ``corpus_bytes``.
        """
        if profile is None:
            profile = CompilerProfile.default()

        # Determine the sequence of modes to execute
        sequence = profile.run_mode_sequence if profile.run_mode_sequence else [mode]
        # An explicit mode= argument overrides the profile sequence
        if mode != "full":
            sequence = [mode]

        tracer = otel_trace.get_tracer(__name__)
        combined: dict[str, Any] = {
            "fragments_processed": 0,
            "fragments_skipped": 0,
            "fragments_skipped_hash": 0,
            "triples_written": 0,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "errors": 0,
            "preprocessing_calls": 0,
            "preprocessing_prompt_tokens": 0,
            "preprocessing_completion_tokens": 0,
            # v0.12.0 extraction stats
            "triples_trusted": 0,
            "triples_tentative": 0,
            "triples_discarded": 0,
            "triples_rejected_ontology": 0,
            "triples_capped": 0,
            # v0.12.1
            "triples_promoted": 0,
            # v0.16.0
            "entity_resolution_calls": 0,
            "entity_resolution_triples": 0,
            # Extraction funnel tracing
            "triples_extracted": 0,
            "triples_citation_rejected": 0,
            "triples_invalid": 0,
            # v0.15.2: document distillation
            "distillation_runs": 0,
            "distillation_calls": 0,
            "distillation_cache_hits": 0,
            "distillation_prompt_tokens": 0,
            "distillation_completion_tokens": 0,
            "distillation_bytes_removed": 0,
            "distillation_strategy_used": "",
            # v0.15.3: vocabulary normalisation
            "vocab_literals_promoted": 0,
            "vocab_predicates_collapsed": 0,
            "vocab_facts_decomposed": 0,
            "vocab_uris_rewritten": 0,
            # v0.18.0: predicate inference
            "predicate_inference_calls": 0,
            "predicate_inference_proposed": 0,
            # v0.15.4: predicate guidance injection
            "predicate_hints_injected": 0,
        }
        with tracer.start_as_current_span("ingest_pipeline.run") as span:
            for run_mode in sequence:
                stats = self._run_inner(corpus_path, profile, dry_run, span, run_mode, force, progress_callback)
                for k in combined:
                    if isinstance(combined[k], str):
                        # String stats: take last non-empty value
                        if stats.get(k):
                            combined[k] = stats[k]
                    else:
                        combined[k] += stats[k]  # type: ignore[operator]
            span.set_attribute("ingest.fragments_processed", combined["fragments_processed"])
            span.set_attribute("ingest.fragments_skipped", combined["fragments_skipped"])
            span.set_attribute("ingest.triples_written", combined["triples_written"])
            return combined

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_inner(
        self,
        corpus_path: str,
        profile: CompilerProfile,
        dry_run: bool,
        span: Any,
        mode: str = "full",
        force: bool = False,
        progress_callback: Callable[[str, dict], None] | None = None,
    ) -> dict:
        from riverbank.connectors.fs import FilesystemConnector  # noqa: PLC0415
        from riverbank.fragmenters.heading import HeadingFragmenter  # noqa: PLC0415
        from riverbank.ingest_gate import IngestGate, IngestGateConfig  # noqa: PLC0415
        from riverbank.parsers.markdown import MarkdownParser  # noqa: PLC0415

        connector = FilesystemConnector()
        parser = MarkdownParser()
        # v0.12.0: overlapping fragment windows from extraction_strategy config
        overlap_sentences: int = getattr(profile, "extraction_strategy", {}).get(
            "overlap_sentences", 0
        )

        # v0.14.0 / v0.15.0: select fragmenter from profile; run adaptive pre-scan
        # when semantic chunking is enabled with auto_tune: true.
        fragmenter = self._load_fragmenter(profile, corpus_path, overlap_sentences, progress_callback)
        gate = IngestGate()
        gate_config = _gate_config_from_profile(profile)
        extractor = self._load_extractor(profile)

        stats: dict[str, Any] = {
            "fragments_processed": 0,
            "fragments_skipped": 0,
            "fragments_skipped_hash": 0,
            "triples_written": 0,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "errors": 0,
            "preprocessing_calls": 0,
            "preprocessing_prompt_tokens": 0,
            "preprocessing_completion_tokens": 0,
            # v0.12.0 extraction stats
            "triples_trusted": 0,
            "triples_tentative": 0,
            "triples_discarded": 0,
            "triples_rejected_ontology": 0,
            "triples_capped": 0,
            # v0.12.1
            "triples_promoted": 0,
            # v0.16.0
            "entity_resolution_calls": 0,
            "entity_resolution_triples": 0,
            # Extraction funnel tracing
            "triples_extracted": 0,
            "triples_citation_rejected": 0,
            "triples_invalid": 0,
            # v0.15.2: document distillation
            "distillation_runs": 0,
            "distillation_calls": 0,
            "distillation_cache_hits": 0,
            "distillation_prompt_tokens": 0,
            "distillation_completion_tokens": 0,
            "distillation_bytes_removed": 0,
            "distillation_strategy_used": "",
            # v0.15.3: vocabulary normalisation
            "vocab_literals_promoted": 0,
            "vocab_predicates_collapsed": 0,
            "vocab_facts_decomposed": 0,
            "vocab_uris_rewritten": 0,
            # v0.18.0: predicate inference
            "predicate_inference_calls": 0,
            "predicate_inference_proposed": 0,
            # v0.15.4: predicate guidance injection
            "predicate_hints_injected": 0,
            # Corpus size for yield metrics
            "corpus_bytes": 0,
        }

        p = Path(corpus_path)
        if p.is_dir():
            sources = list(connector.discover({"path": str(p)}))
        else:
            # Single file
            content = p.read_bytes()
            from riverbank.connectors.fs import SourceRecord  # noqa: PLC0415

            sources = [
                SourceRecord(
                    iri=p.as_uri(),
                    path=p,
                    content=content,
                    content_hash=xxhash.xxh3_128(content).digest(),
                    mime_type="text/markdown",
                )
            ]

        # Sum corpus bytes from all sources for yield metrics
        stats["corpus_bytes"] = sum(len(src.content) for src in sources if src.content)

        tracer = otel_trace.get_tracer(__name__)
        with self._get_db() as conn:
            # Register the profile once per run
            profile_db_id = self._ensure_profile(conn, profile)
            profile.id = profile_db_id

            # Phase 1 preprocessing: build document preprocessor once (re-used per source)
            preprocessor = None
            if getattr(profile, "preprocessing", {}).get("enabled", False):
                from riverbank.preprocessors import DocumentPreprocessor  # noqa: PLC0415
                preprocessor = DocumentPreprocessor(self._settings)

            # Strategy 6: few-shot golden example injector (built once, used per fragment)
            from riverbank.preprocessors import FewShotInjector  # noqa: PLC0415
            few_shot_injector = FewShotInjector.from_profile(profile)

            # Phase 2 preprocessing: corpus-level clustering.
            # Requires Phase 1 summaries — collect them first via a lightweight pre-scan,
            # then analyze once before the full extraction loop.
            corpus_analysis = None
            if getattr(profile, "corpus_preprocessing", {}).get("enabled", False):
                from riverbank.preprocessors import CorpusPreprocessor, DocumentPreprocessor as _DP  # noqa: PLC0415
                _cp_pre = _DP(self._settings) if preprocessor is None else preprocessor
                doc_summaries: dict[str, str] = {}
                if progress_callback:
                    progress_callback("corpus_analysis_start", {"n_docs": len(sources)})
                for _src in sources:
                    try:
                        _doc = parser.parse(_src)
                        _summary_text, _pt, _ct = _cp_pre._extract_summary(_doc.raw_text, profile)
                        if _summary_text:
                            doc_summaries[_src.iri] = _summary_text
                            stats["preprocessing_prompt_tokens"] += _pt
                            stats["preprocessing_completion_tokens"] += _ct
                    except Exception as _exc:  # noqa: BLE001
                        logger.debug("Phase 2 pre-scan failed for %s: %s", _src.iri, _exc)
                _corpus_proc = CorpusPreprocessor(self._settings)
                corpus_analysis = _corpus_proc.analyze(doc_summaries, profile)
                if corpus_analysis is not None:
                    if progress_callback:
                        progress_callback(
                            "corpus_analysis_done",
                            {"n_clusters": len(corpus_analysis.clusters)},
                        )
                    logger.info(
                        "Phase 2: corpus analysis complete — %d clusters, corpus_hash=%s",
                        len(corpus_analysis.clusters),
                        corpus_analysis.corpus_hash,
                    )

            for source in sources:
                with tracer.start_as_current_span("ingest_pipeline.source") as src_span:
                    src_span.set_attribute("source.iri", source.iri)
                    try:
                        self._process_source(
                            conn,
                            source,
                            parser,
                            fragmenter,
                            gate,
                            gate_config,
                            extractor,
                            profile,
                            dry_run,
                            stats,
                            mode=mode,
                            force=force,
                            progress_callback=progress_callback,
                            preprocessor=preprocessor,
                            few_shot_injector=few_shot_injector,
                            corpus_analysis=corpus_analysis,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Failed to process %s: %s", source.iri, exc)
                        src_span.set_status(otel_trace.StatusCode.ERROR, str(exc))
                        stats["errors"] += 1

            conn.commit()

        return stats

    def _process_source(
        self,
        conn: Any,
        source: Any,
        parser: Any,
        fragmenter: Any,
        gate: Any,
        gate_config: Any,
        extractor: Any,
        profile: CompilerProfile,
        dry_run: bool,
        stats: dict,
        mode: str = "full",
        force: bool = False,
        progress_callback: Callable[[str, dict], None] | None = None,
        preprocessor: Any = None,
        few_shot_injector: Any = None,
        corpus_analysis: Any = None,
    ) -> None:
        from riverbank.catalog.graph import (  # noqa: PLC0415
            delete_artifact_deps,
            emit_outbox_event,
            get_artifacts_depending_on_fragment,
            load_triples_with_confidence,
            record_artifact_dep,
            shacl_score,
        )

        doc = parser.parse(source)
        tracer = otel_trace.get_tracer(__name__)

        # v0.15.2: Document distillation — optional pre-fragmentation content-selection
        # step.  The distilled text replaces the original for fragmentation,
        # preprocessing, and extraction.  Results are cached on disk keyed by
        # content hash + strategy so unchanged documents incur no LLM cost on
        # re-ingest.  The original content_hash is preserved for deduplication.
        distillation_cfg: dict = getattr(profile, "distillation", {})
        if distillation_cfg.get("enabled", False) and not dry_run:
            with tracer.start_as_current_span("ingest_pipeline.distill") as dist_span:
                dist_span.set_attribute("source.iri", source.iri)
                try:
                    from riverbank.distillers import DocumentDistiller  # noqa: PLC0415
                    _distiller = DocumentDistiller.from_profile(profile, settings=self._settings)
                    _distill_result = _distiller.distill(
                        raw_text=doc.raw_text,
                        content_hash=source.content_hash,
                        profile=profile,
                    )
                    if _distill_result.distilled_text and _distill_result.distilled_text != doc.raw_text:
                        from riverbank.connectors.fs import SourceRecord as _SR_D  # noqa: PLC0415
                        _distilled_source = _SR_D(
                            iri=source.iri,
                            path=source.path,
                            content=_distill_result.distilled_text.encode("utf-8"),
                            content_hash=source.content_hash,  # keep original hash for dedup
                            mime_type=source.mime_type,
                        )
                        doc = parser.parse(_distilled_source)
                    stats["distillation_runs"] += 1
                    stats["distillation_calls"] += _distill_result.llm_calls
                    stats["distillation_cache_hits"] += 1 if _distill_result.cache_hit else 0
                    stats["distillation_prompt_tokens"] += _distill_result.prompt_tokens
                    stats["distillation_completion_tokens"] += _distill_result.completion_tokens
                    _bytes_removed = max(0, _distill_result.original_bytes - _distill_result.distilled_bytes)
                    stats["distillation_bytes_removed"] += _bytes_removed
                    if _distill_result.strategy_used:
                        stats["distillation_strategy_used"] = _distill_result.strategy_used
                    dist_span.set_attribute("distillation.cache_hit", _distill_result.cache_hit)
                    dist_span.set_attribute("distillation.llm_calls", _distill_result.llm_calls)
                    dist_span.set_attribute("distillation.strategy", _distill_result.strategy_used)
                    if progress_callback:
                        progress_callback(
                            "distillation_done",
                            {
                                "source": source.iri,
                                "cache_hit": _distill_result.cache_hit,
                                "strategy_used": _distill_result.strategy_used,
                                "original_bytes": _distill_result.original_bytes,
                                "distilled_bytes": _distill_result.distilled_bytes,
                            },
                        )
                except Exception as _dist_exc:  # noqa: BLE001
                    logger.warning(
                        "Distillation failed for %s — continuing with original text: %s",
                        source.iri,
                        _dist_exc,
                    )

        # v0.12.0: coreference resolution — runs on the full document text before
        # fragmentation to replace pronouns/anaphoric refs with entity names.
        coref_mode: str = getattr(profile, "preprocessing", {}).get("coreference", "disabled")
        if coref_mode and coref_mode != "disabled" and not dry_run:
            try:
                from riverbank.extractors.coreference import CoreferenceResolver  # noqa: PLC0415
                _resolver = CoreferenceResolver(self._settings)
                resolved_text = _resolver.resolve(doc.raw_text, profile)
                if resolved_text != doc.raw_text:
                    # Rebuild the parsed doc with the resolved text
                    from riverbank.parsers.markdown import MarkdownParser as _MP  # noqa: PLC0415
                    import io  # noqa: PLC0415
                    from riverbank.connectors.fs import SourceRecord as _SR  # noqa: PLC0415
                    _resolved_source = _SR(
                        iri=source.iri,
                        path=source.path,
                        content=resolved_text.encode("utf-8"),
                        content_hash=source.content_hash,  # keep original hash
                        mime_type=source.mime_type,
                    )
                    doc = parser.parse(_resolved_source)
                    logger.debug(
                        "Coreference resolved: %s (mode=%s)", source.iri, coref_mode
                    )
            except Exception as _coref_exc:  # noqa: BLE001
                logger.debug("Coreference resolution skipped: %s", _coref_exc)

        # v0.18.0: Predicate inference — propose schema before extraction
        # v0.15.4: When use_for_extraction: false, inject PREDICATE HINTS block
        #          into the extraction prompt as soft guidance.
        predicate_inference_cfg: dict = getattr(profile, "predicate_inference", {})
        seed_predicates: list = list(getattr(profile, "seed_predicates", []) or [])
        _hint_predicates: dict[str, list[str]] = {"high": [], "medium": [], "exploratory": []}
        if predicate_inference_cfg.get("enabled", False) and not dry_run:
            try:
                from riverbank.inference.schema_proposer import SchemaProposer  # noqa: PLC0415
                proposer = SchemaProposer(settings=self._settings)
                inference_result = proposer.propose(doc.raw_text, profile)
                proposed_predicates = inference_result.get("allowed_predicates", [])
                use_for_extraction = predicate_inference_cfg.get("use_for_extraction", False)

                stats["predicate_inference_calls"] += 1
                stats["predicate_inference_proposed"] += len(proposed_predicates)
                if proposed_predicates and use_for_extraction:
                    # Merge proposed predicates into profile's allowed_predicates
                    existing = set(getattr(profile, "allowed_predicates", []))
                    proposed = set(proposed_predicates)
                    merged = sorted(existing | proposed)
                    profile.allowed_predicates = merged
                    logger.info(
                        "Predicate inference: merged %d proposed predicates "
                        "(existing: %d, new: %d, total: %d)",
                        len(proposed_predicates),
                        len(existing),
                        len(proposed - existing),
                        len(merged),
                    )
                    if progress_callback:
                        progress_callback(
                            "predicate_inference_done",
                            {
                                "proposed_count": len(proposed_predicates),
                                "merged_count": len(merged),
                                "inference_diagnostics": inference_result.get("diagnostics", {}),
                            },
                        )
                else:
                    # v0.15.4: use_for_extraction: false — collect hints for injection
                    _hint_predicates = inference_result.get(
                        "suggested_predicates",
                        {"high": [], "medium": [], "exploratory": []},
                    )
                    logger.debug(
                        "Predicate inference: proposed %d predicates (use_for_extraction=%s)",
                        len(proposed_predicates),
                        use_for_extraction,
                    )
            except Exception as _infer_exc:  # noqa: BLE001
                logger.warning("Predicate inference failed, continuing without it: %s", _infer_exc)

        # v0.15.4: Build and inject PREDICATE HINTS block into extraction prompt.
        # Seed predicates are always treated as "high" confidence hints; they are
        # merged with the inference proposals before injection.  Injection happens
        # when there are any hints to inject (seed or inferred) and the profile is
        # NOT using constrained extraction (use_for_extraction: true already adds
        # predicates to allowed_predicates as hard constraints, so hints would be
        # redundant).
        _use_for_extraction = predicate_inference_cfg.get("use_for_extraction", False)
        if not _use_for_extraction and not dry_run:
            # Merge seed predicates into "high" tier
            merged_high = list(_hint_predicates.get("high", []))
            for _sp in seed_predicates:
                if _sp not in merged_high:
                    merged_high.append(_sp)
            _hint_predicates = dict(_hint_predicates)
            _hint_predicates["high"] = merged_high

            _all_hints = (
                _hint_predicates.get("high", [])
                + _hint_predicates.get("medium", [])
                + _hint_predicates.get("exploratory", [])
            )
            if _all_hints:
                stats["predicate_hints_injected"] += len(_all_hints)
                _hints_block = _build_predicate_hints_block(_hint_predicates)
                from dataclasses import replace as _dc_replace_hints  # noqa: PLC0415
                profile = _dc_replace_hints(
                    profile,
                    prompt_text=profile.prompt_text + "\n\n" + _hints_block,
                )
                logger.info(
                    "Predicate guidance injection: %d hints injected into extraction prompt "
                    "(%d high, %d medium, %d exploratory)",
                    len(_all_hints),
                    len(_hint_predicates.get("high", [])),
                    len(_hint_predicates.get("medium", [])),
                    len(_hint_predicates.get("exploratory", [])),
                )
                if progress_callback:
                    progress_callback(
                        "predicate_hints_injected",
                        {
                            "source": source.iri,
                            "hints_count": len(_all_hints),
                            "high": _hint_predicates.get("high", []),
                            "medium": _hint_predicates.get("medium", []),
                            "exploratory": _hint_predicates.get("exploratory", []),
                        },
                    )

        fragments = list(fragmenter.fragment(doc))
        existing_hashes = self._get_existing_hashes(conn, source.iri)

        # §3.9 Adaptive preprocessing: skip preprocessing for small single-fragment
        # documents where the value of entity canonicalization is minimal.
        preprocessing_cfg: dict = getattr(profile, "preprocessing", {})
        adaptive_threshold: int = preprocessing_cfg.get("adaptive_threshold", 2000)
        _skip_preprocessing_adaptive = (
            len(fragments) <= 1
            and len(doc.raw_text) < adaptive_threshold
        )
        if _skip_preprocessing_adaptive and preprocessor is not None:
            logger.debug(
                "Adaptive preprocessing: skipping for small document %s "
                "(%d chars, %d fragment(s))",
                source.iri,
                len(doc.raw_text),
                len(fragments),
            )

        # Phase 1 preprocessing: run once per document before extraction begins
        # §3.6 Phase 2 pre-scan dedup: reuse cached summary if available
        preprocess_result = None
        extraction_profile = profile
        if preprocessor is not None and not dry_run and not _skip_preprocessing_adaptive:
            with tracer.start_as_current_span("ingest_pipeline.preprocess") as pp_span:
                pp_span.set_attribute("source.iri", source.iri)
                from dataclasses import replace as _dc_replace  # noqa: PLC0415
                if progress_callback:
                    progress_callback("preprocessing_start", {"source": source.iri})
                # §3.6: reuse Phase 2 pre-scan summary to avoid duplicate LLM call
                pre_summary = (
                    corpus_analysis._doc_summaries.get(source.iri)
                    if corpus_analysis is not None
                    else None
                )
                preprocess_result = preprocessor.preprocess(
                    doc.raw_text, profile, pre_computed_summary=pre_summary
                )
                if preprocess_result is not None:
                    # §3.1 fragment_text passed later per-fragment; use empty string
                    # here to build a base prompt (filtering happens per fragment below)
                    enriched_prompt = preprocessor.build_extraction_prompt(
                        preprocess_result, profile
                    )
                    extraction_profile = _dc_replace(profile, prompt_text=enriched_prompt)
                    stats["preprocessing_calls"] = stats.get("preprocessing_calls", 0) + 1
                    stats["preprocessing_prompt_tokens"] = (
                        stats.get("preprocessing_prompt_tokens", 0) + preprocess_result.prompt_tokens
                    )
                    stats["preprocessing_completion_tokens"] = (
                        stats.get("preprocessing_completion_tokens", 0) + preprocess_result.completion_tokens
                    )
                    logger.debug(
                        "Preprocessing: enriched prompt for %s (%d entities, %d+%d tokens)",
                        source.iri,
                        len(preprocess_result.entity_catalog),
                        preprocess_result.prompt_tokens,
                        preprocess_result.completion_tokens,
                    )
                if progress_callback:
                    progress_callback("preprocessing_done", {"source": source.iri})

        # Phase 2: inject corpus + cluster context on top of Phase 1 enrichment
        if corpus_analysis is not None and not dry_run:
            from dataclasses import replace as _dc_replace_p2  # noqa: PLC0415
            from riverbank.preprocessors import CorpusPreprocessor as _CorpusProc  # noqa: PLC0415
            _cp = _CorpusProc(self._settings)
            doc_summary_text = corpus_analysis._doc_summaries.get(source.iri, "")
            corpus_ctx = _cp.build_context(source.iri, corpus_analysis, doc_summary_text)
            if corpus_ctx:
                current_prompt = extraction_profile.prompt_text
                extraction_profile = _dc_replace_p2(
                    extraction_profile,
                    prompt_text=f"{corpus_ctx}\n\n{current_prompt}",
                )
                logger.debug(
                    "Phase 2: injected corpus/cluster context for %s (cluster %s)",
                    source.iri,
                    corpus_analysis.doc_cluster_map.get(source.iri, "?"),
                )

        if progress_callback:
            progress_callback("source_start", {"source": source.iri, "total_fragments": len(fragments)})

        # v0.16.0: entity resolution — accumulate subjects across all fragments
        entity_resolution_cfg: dict = getattr(profile, "entity_resolution", {})
        source_subjects: set[str] = set()

        # v0.15.3: vocabulary normalisation — deferred write when enabled
        vocab_norm_cfg: dict = getattr(profile, "vocabulary_normalisation", {})
        vocab_norm_enabled: bool = (
            vocab_norm_cfg.get("enabled", False)
            and not dry_run
            and mode == "full"
        )
        # Triple buffer for deferred write; None = immediate per-fragment write (default)
        vocab_norm_buffer: list | None = [] if vocab_norm_enabled else None

        # v0.17.0: Batch extraction disabled (v0.15.1 limitation)
        # Batch mode not working reliably with Gemma/Ollama due to structured output
        # and multiple tool calls limitations. Use per-fragment mode for now.
        extraction_strategy: dict = getattr(profile, "extraction_strategy", {})
        batch_size: int = extraction_strategy.get("batch_size", 0)
        use_batching: bool = False  # Disabled in v0.15.1
        if batch_size > 0:
            logger.warning(
                "extraction_strategy.batch_size=%d is set but batch extraction is disabled in v0.15.1 — "
                "setting has no effect; all fragments are processed individually.",
                batch_size,
            )

        # Pre-filter fragments to determine which ones need extraction
        fragments_to_process: list[tuple[Any, str, Any]] = []  # (frag, frag_iri, frag_profile)
        for frag in fragments:
            frag_hash_hex = frag.content_hash.hex()
            frag_iri = f"{source.iri}#{frag.fragment_key}"

            # --- Recompile detection -------------------------------------------
            # If the fragment existed before with a *different* hash, we must
            # invalidate all compiled artifacts that depended on it and emit a
            # semantic diff event on the pg-trickle outbox.
            fragment_changed = (
                frag.fragment_key in existing_hashes
                and existing_hashes[frag.fragment_key] != frag_hash_hex
            )
            if fragment_changed and not dry_run:
                stale_artifacts = get_artifacts_depending_on_fragment(conn, frag_iri)
                for art_iri in stale_artifacts:
                    delete_artifact_deps(conn, art_iri)
                if stale_artifacts:
                    emit_outbox_event(
                        conn,
                        "semantic_diff",
                        {
                            "fragment_iri": frag_iri,
                            "profile": f"{profile.name}@v{profile.version}",
                            "invalidated": stale_artifacts,
                        },
                    )
                    logger.info(
                        "Recompile: fragment %s changed — invalidated %d artifact dep(s)",
                        frag_iri,
                        len(stale_artifacts),
                    )

            # Fragment hash check — skip if content unchanged (unless --force is set)
            if (
                not force
                and frag.fragment_key in existing_hashes
                and existing_hashes[frag.fragment_key] == frag_hash_hex
            ):
                stats["fragments_skipped_hash"] += 1
                stats["fragments_skipped"] += 1
                if progress_callback:
                    progress_callback("fragment", {"key": frag.fragment_key, "status": "skipped_hash"})
                continue

            # §Noise section filtering: skip fragments whose heading path matches
            # a configured noise section (e.g. "References", "Changelog").
            if preprocess_result is not None and preprocess_result.noise_sections:
                if frag.fragment_key in preprocess_result.noise_sections or any(
                    frag.fragment_key.startswith(ns) for ns in preprocess_result.noise_sections
                ):
                    stats["fragments_skipped"] += 1
                    logger.debug(
                        "Fragment %s skipped: noise section (%s)",
                        frag.fragment_key,
                        preprocess_result.noise_sections,
                    )
                    if progress_callback:
                        progress_callback("fragment", {"key": frag.fragment_key, "status": "skipped_noise"})
                    continue

            # Editorial policy gate
            gate_result = gate.check(frag, gate_config)
            if not gate_result.accepted:
                stats["fragments_skipped"] += 1
                logger.debug(
                    "Fragment %s skipped by gate: %s",
                    frag.fragment_key,
                    gate_result.reason,
                )
                if progress_callback:
                    progress_callback("fragment", {"key": frag.fragment_key, "status": "skipped_gate"})
                continue

            stats["fragments_processed"] += 1
            if progress_callback:
                progress_callback("fragment", {"key": frag.fragment_key, "status": "processing"})

            if dry_run:
                # In dry-run mode we parse + fragment but skip extraction
                continue

            # Build the fragment profile (with per-fragment customizations)
            frag_profile = extraction_profile
            if preprocess_result is not None and preprocessor is not None:
                from dataclasses import replace as _dc_replace_frag  # noqa: PLC0415
                filtered_prompt = preprocessor.build_extraction_prompt(
                    preprocess_result, profile, fragment_text=frag.text
                )
                frag_profile = _dc_replace_frag(extraction_profile, prompt_text=filtered_prompt)
            # Strategy 6: inject few-shot examples into the extraction prompt
            if few_shot_injector is not None:
                from dataclasses import replace as _dc_replace2  # noqa: PLC0415
                enriched_with_shots = few_shot_injector.inject(
                    frag_profile.prompt_text,
                    profile,
                    fragment_text=frag.text,
                )
                if enriched_with_shots != frag_profile.prompt_text:
                    frag_profile = _dc_replace2(frag_profile, prompt_text=enriched_with_shots)

            fragments_to_process.append((frag, frag_iri, frag_profile))

        # Ensure source record exists
        if fragments_to_process and not dry_run:
            self._ensure_source(conn, source, profile)

        # Process fragments (batched or per-fragment)
        if use_batching:
            # v0.17.0: Batch extraction mode
            for batch_start in range(0, len(fragments_to_process), batch_size):
                batch_end = min(batch_start + batch_size, len(fragments_to_process))
                batch = fragments_to_process[batch_start:batch_end]
                batch_frags = [f for f, _, _ in batch]

                logger.debug(
                    "Batch extraction: %d fragments (batch %d-%d)",
                    len(batch_frags),
                    batch_start,
                    batch_end - 1,
                )

                with tracer.start_as_current_span("ingest_pipeline.extract_batch") as ex_span:
                    ex_span.set_attribute("batch.size", len(batch_frags))
                    try:
                        batch_results = extractor.extract_batch(
                            fragments=batch_frags,
                            profile=extraction_profile,
                            trace=None,
                        )
                    except Exception as ex_exc:  # noqa: BLE001
                        logger.warning("Batch extraction failed: %s", str(ex_exc)[:200])
                        stats["errors"] += 1
                        for frag, frag_iri, _ in batch:
                            stats["errors"] += 1
                        continue

                # Process results for each fragment in the batch
                for frag, frag_iri, _ in batch:
                    frag_key = frag.fragment_key
                    result = batch_results.get(frag_key)
                    if result is None:
                        logger.warning("Batch extraction did not return result for fragment %s", frag_key)
                        stats["errors"] += 1
                        continue

                    stats["llm_calls"] += result.diagnostics.get("llm_calls", 0)
                    stats["prompt_tokens"] += result.diagnostics.get("prompt_tokens", 0)
                    stats["completion_tokens"] += result.diagnostics.get("completion_tokens", 0)

                    # Process triples (same logic as per-fragment extraction)
                    frag_subjects = _process_extraction_result(
                        conn, result, frag, frag_iri, source, profile, mode, stats, tracer, preprocessing_cfg,
                        triple_buffer=vocab_norm_buffer,
                    )
                    source_subjects.update(frag_subjects)
        else:
            # Standard per-fragment extraction
            for frag, frag_iri, frag_profile in fragments_to_process:
                # NER pre-resolution step (v0.5.0)
                ner_context: dict = {}
                try:
                    from riverbank.ner import SpacyNERExtractor, lookup_vocabulary  # noqa: PLC0415

                    _ner = SpacyNERExtractor(model_name=profile.ner_model)
                    ner_result = _ner.extract(frag.text)
                    if ner_result.entities:
                        vocab_matches: dict[str, str] = {}
                        for entity in ner_result.entities:
                            iri_match = lookup_vocabulary(conn, entity.text)
                            if iri_match:
                                vocab_matches[entity.text] = iri_match
                        if vocab_matches:
                            ner_context = {"vocabulary_matches": vocab_matches}
                except Exception as _ner_exc:  # noqa: BLE001
                    logger.debug("NER pre-resolution step failed: %s", _ner_exc)

                # v0.13.1: knowledge-prefix adapter — inject KNOWN GRAPH CONTEXT
                from riverbank.extractors.knowledge_prefix import (  # noqa: PLC0415
                    KnowledgePrefixAdapter,
                )
                kp_adapter = KnowledgePrefixAdapter.from_profile(profile)
                if kp_adapter.is_enabled():
                    kp_result = kp_adapter.build_context(
                        conn,
                        profile.named_graph,
                        frag.text,
                    )
                    if kp_result.context_block:
                        from dataclasses import replace as _dc_replace_kp  # noqa: PLC0415
                        kp_prompt = kp_result.context_block + "\n\n" + frag_profile.prompt_text
                        frag_profile = _dc_replace_kp(frag_profile, prompt_text=kp_prompt)

                # Extract triples
                with tracer.start_as_current_span("ingest_pipeline.extract") as ex_span:
                    ex_span.set_attribute("fragment.key", frag.fragment_key)
                    try:
                        result = extractor.extract(fragment=frag, profile=frag_profile, trace=None)
                    except Exception as ex_exc:  # noqa: BLE001
                        logger.warning(
                            "Extraction failed for fragment %s: %s",
                            frag.fragment_key,
                            str(ex_exc)[:200],
                        )
                        stats["errors"] += 1
                        continue

                stats["llm_calls"] += result.diagnostics.get("llm_calls", 0)
                stats["prompt_tokens"] += result.diagnostics.get("prompt_tokens", 0)
                stats["completion_tokens"] += result.diagnostics.get("completion_tokens", 0)

                # Process the extraction result
                frag_subjects = _process_extraction_result(
                    conn, result, frag, frag_iri, source, profile, mode, stats, tracer, preprocessing_cfg,
                    triple_buffer=vocab_norm_buffer,
                )
                source_subjects.update(frag_subjects)


        # Record fragments and collect subjects for entity resolution
        for frag in fragments_to_process:
            frag_obj, frag_iri, _ = frag
            self._upsert_fragment(conn, source, frag_obj)
            # Note: batch results are already processed above via _process_extraction_result
            # which handles source_subjects collection for entity resolution


        # v0.16.0: Entity resolution pass — merge entity aliases with owl:sameAs
        if entity_resolution_cfg.get("enabled") and not dry_run and source_subjects and mode == "full":
            from riverbank.extractors.entity_resolution import EntityResolutionPass  # noqa: PLC0415
            _er_pass = EntityResolutionPass(self._settings)
            er_triples, er_pt, er_ct = _er_pass.run(
                doc.raw_text, source.iri, list(source_subjects), profile
            )
            if er_triples:
                if vocab_norm_buffer is not None:
                    # Defer: add entity resolution triples to the buffer so
                    # URICanonicaliser can use the owl:sameAs links.
                    vocab_norm_buffer.extend(er_triples)
                    # Track ER triple count but defer triples_written update
                    stats["entity_resolution_triples"] += len(er_triples)
                else:
                    written_er = load_triples_with_confidence(conn, er_triples, profile.named_graph)
                    stats["triples_written"] += written_er
                    stats["triples_trusted"] += written_er
                    stats["entity_resolution_triples"] += written_er
            stats["entity_resolution_calls"] += 1
            stats["preprocessing_prompt_tokens"] += er_pt
            stats["preprocessing_completion_tokens"] += er_ct
            logger.info(
                "Entity resolution: %d owl:sameAs triples written for %s",
                len(er_triples) if er_triples else 0,
                source.iri,
            )

        # v0.15.3: Vocabulary normalisation — apply to deferred triple buffer and write
        if vocab_norm_buffer is not None and vocab_norm_buffer:
            with tracer.start_as_current_span("ingest_pipeline.vocab_normalise") as vn_span:
                vn_span.set_attribute("source.iri", source.iri)
                vn_span.set_attribute("vocab_norm.input_triples", len(vocab_norm_buffer))
                try:
                    from riverbank.vocabulary import (  # noqa: PLC0415
                        VocabularyNormalisationPass,
                        build_llm_predicate_collapser,
                    )

                    _vn_pass = VocabularyNormalisationPass.from_profile(profile)
                    _llm_collapser = None
                    if vocab_norm_cfg.get("predicate_collapse_backend") == "llm":
                        _llm_collapser = build_llm_predicate_collapser(
                            self._settings, profile
                        )
                    vn_result = _vn_pass.run(vocab_norm_buffer, llm_client=_llm_collapser)

                    stats["vocab_literals_promoted"] += vn_result.vocab_literals_promoted
                    stats["vocab_predicates_collapsed"] += vn_result.vocab_predicates_collapsed
                    stats["vocab_facts_decomposed"] += vn_result.vocab_facts_decomposed
                    stats["vocab_uris_rewritten"] += vn_result.vocab_uris_rewritten
                    vn_span.set_attribute("vocab_norm.literals_promoted", vn_result.vocab_literals_promoted)
                    vn_span.set_attribute("vocab_norm.predicates_collapsed", vn_result.vocab_predicates_collapsed)
                    vn_span.set_attribute("vocab_norm.facts_decomposed", vn_result.vocab_facts_decomposed)
                    vn_span.set_attribute("vocab_norm.uris_rewritten", vn_result.vocab_uris_rewritten)

                    # Write normalised triples grouped by named graph
                    from itertools import groupby  # noqa: PLC0415

                    sorted_triples = sorted(
                        vn_result.triples, key=lambda t: t.named_graph
                    )
                    for named_graph, group in groupby(
                        sorted_triples, key=lambda t: t.named_graph
                    ):
                        batch = list(group)
                        written = load_triples_with_confidence(conn, batch, named_graph)
                        stats["triples_written"] += written
                        if named_graph == profile.tentative_graph:
                            stats["triples_tentative"] += written
                        else:
                            stats["triples_trusted"] += written

                    logger.info(
                        "Vocabulary normalisation: %d→%d triples for %s "
                        "(+%d promoted, +%d collapsed, +%d decomposed, +%d rewritten)",
                        len(vocab_norm_buffer),
                        len(vn_result.triples),
                        source.iri,
                        vn_result.vocab_literals_promoted,
                        vn_result.vocab_predicates_collapsed,
                        vn_result.vocab_facts_decomposed,
                        vn_result.vocab_uris_rewritten,
                    )
                except Exception as _vn_exc:  # noqa: BLE001
                    logger.warning(
                        "Vocabulary normalisation failed for %s — writing original triples: %s",
                        source.iri,
                        _vn_exc,
                    )
                    # Fall back: write the un-normalised buffered triples
                    from itertools import groupby as _gb  # noqa: PLC0415

                    for named_graph, group in _gb(
                        sorted(vocab_norm_buffer, key=lambda t: t.named_graph),
                        key=lambda t: t.named_graph,
                    ):
                        batch = list(group)
                        written = load_triples_with_confidence(conn, batch, named_graph)
                        stats["triples_written"] += written

        stats["cost_usd"] += _estimate_cost(
            stats["prompt_tokens"], stats["completion_tokens"], profile
        )

    # ------------------------------------------------------------------
    # Catalog helpers
    # ------------------------------------------------------------------

    def _get_db(self) -> Any:
        if self._db_engine is not None:
            return self._db_engine.connect()
        from sqlalchemy import create_engine  # noqa: PLC0415

        engine = create_engine(self._settings.db.dsn)
        return engine.connect()

    def _get_existing_hashes(self, conn: Any, source_iri: str) -> dict[str, str]:
        try:
            from sqlalchemy import text  # noqa: PLC0415

            rows = conn.execute(
                text(
                    "SELECT f.fragment_key, encode(f.content_hash, 'hex') "
                    "FROM _riverbank.fragments f "
                    "JOIN _riverbank.sources s ON f.source_id = s.id "
                    "WHERE s.iri = :iri"
                ),
                {"iri": source_iri},
            ).fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not load existing hashes: %s", exc)
            return {}

    def _ensure_profile(self, conn: Any, profile: CompilerProfile) -> Optional[int]:
        """Insert the profile if it does not exist; return its DB id."""
        try:
            import hashlib  # noqa: PLC0415
            import json  # noqa: PLC0415

            from sqlalchemy import text  # noqa: PLC0415

            prompt_hash = hashlib.sha256(profile.prompt_text.encode()).digest()
            row = conn.execute(
                text(
                    "SELECT id FROM _riverbank.profiles WHERE name = :name AND version = :version"
                ),
                {"name": profile.name, "version": profile.version},
            ).fetchone()
            if row:
                return int(row[0])

            result = conn.execute(
                text(
                    "INSERT INTO _riverbank.profiles "
                    "(name, version, schema_json, prompt_hash, prompt_text, "
                    " editorial_policy, model_provider, model_name, embedding_model, "
                    " max_fragment_tokens) "
                    "VALUES (:name, :version, cast(:schema_json as jsonb), :prompt_hash, :prompt_text, "
                    "        cast(:editorial_policy as jsonb), :model_provider, :model_name, "
                    "        :embed_model, :max_fragment_tokens) "
                    "RETURNING id"
                ),
                {
                    "name": profile.name,
                    "version": profile.version,
                    "schema_json": json.dumps(profile.schema_json),
                    "prompt_hash": prompt_hash,
                    "prompt_text": profile.prompt_text,
                    "editorial_policy": json.dumps(profile.editorial_policy),
                    "model_provider": profile.model_provider,
                    "model_name": profile.model_name,
                    "embed_model": profile.embed_model,
                    "max_fragment_tokens": profile.max_fragment_tokens,
                },
            )
            conn.commit()
            row = result.fetchone()
            db_id = int(row[0]) if row else None

            # v0.5.0: Register singer tap configurations in tide.relay_inlet_config
            if profile.singer_taps and db_id is not None:
                from riverbank.catalog.graph import register_singer_taps  # noqa: PLC0415

                register_singer_taps(conn, profile.singer_taps, profile.name)

            return db_id
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not register profile: %s", exc)
            return None

    def _ensure_source(self, conn: Any, source: Any, profile: CompilerProfile) -> None:
        """Upsert a source record into ``_riverbank.sources``."""
        try:
            from sqlalchemy import text  # noqa: PLC0415

            now = datetime.now(timezone.utc)
            conn.execute(
                text(
                    "INSERT INTO _riverbank.sources "
                    "(iri, source_type, connector, profile_id, named_graph, "
                    " content_hash, last_seen_at, status) "
                    "VALUES (:iri, :source_type, :connector, :profile_id, :named_graph, "
                    "        :content_hash, :last_seen_at, 'pending') "
                    "ON CONFLICT (iri) DO UPDATE SET "
                    "  content_hash = EXCLUDED.content_hash, "
                    "  last_seen_at = EXCLUDED.last_seen_at"
                ),
                {
                    "iri": source.iri,
                    "source_type": getattr(source, "mime_type", "text/markdown"),
                    "connector": "filesystem",
                    "profile_id": profile.id,
                    "named_graph": profile.named_graph,
                    "content_hash": source.content_hash,
                    "last_seen_at": now,
                },
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not upsert source: %s", exc)

    def _upsert_fragment(self, conn: Any, source: Any, frag: Any) -> None:
        """Insert or update a fragment record in ``_riverbank.fragments``."""
        try:
            from sqlalchemy import text  # noqa: PLC0415

            conn.execute(
                text(
                    "INSERT INTO _riverbank.fragments "
                    "(source_id, fragment_key, content_hash, char_start, char_end, "
                    " heading_path, text_excerpt) "
                    "VALUES ("
                    "  (SELECT id FROM _riverbank.sources WHERE iri = :iri), "
                    "  :fragment_key, :content_hash, :char_start, :char_end, "
                    "  :heading_path, :text_excerpt"
                    ") "
                    "ON CONFLICT (source_id, fragment_key) DO UPDATE SET "
                    "  content_hash = EXCLUDED.content_hash, "
                    "  char_start   = EXCLUDED.char_start, "
                    "  char_end     = EXCLUDED.char_end, "
                    "  heading_path = EXCLUDED.heading_path, "
                    "  text_excerpt = EXCLUDED.text_excerpt"
                ),
                {
                    "iri": source.iri,
                    "fragment_key": frag.fragment_key,
                    "content_hash": frag.content_hash,
                    "char_start": frag.char_start,
                    "char_end": frag.char_end,
                    "heading_path": frag.heading_path,
                    "text_excerpt": frag.text[:200] if frag.text else None,
                },
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not upsert fragment: %s", exc)

    def _record_run(
        self,
        conn: Any,
        source: Any,
        frag: Any,
        profile: CompilerProfile,
        result: Any,
    ) -> None:
        """Insert a run record into ``_riverbank.runs``."""
        try:
            import json  # noqa: PLC0415

            from sqlalchemy import text  # noqa: PLC0415

            now = datetime.now(timezone.utc)

            fragment_row = conn.execute(
                text(
                    "SELECT f.id FROM _riverbank.fragments f "
                    "JOIN _riverbank.sources s ON f.source_id = s.id "
                    "WHERE s.iri = :iri AND f.fragment_key = :fk"
                ),
                {"iri": source.iri, "fk": frag.fragment_key},
            ).fetchone()
            if fragment_row is None:
                return

            prompt_tokens = result.diagnostics.get("prompt_tokens", 0)
            completion_tokens = result.diagnostics.get("completion_tokens", 0)
            cost_usd = _estimate_cost_single(prompt_tokens, completion_tokens, profile)

            conn.execute(
                text(
                    "INSERT INTO _riverbank.runs "
                    "(fragment_id, profile_id, started_at, finished_at, outcome, "
                    " prompt_tokens, completion_tokens, cost_usd, diagnostics) "
                    "VALUES (:fragment_id, :profile_id, :started_at, :finished_at, "
                    "        :outcome, :prompt_tokens, :completion_tokens, "
                    "        :cost_usd, cast(:diagnostics as jsonb))"
                ),
                {
                    "fragment_id": fragment_row[0],
                    "profile_id": profile.id,
                    "started_at": now,
                    "finished_at": datetime.now(timezone.utc),
                    "outcome": "success" if not result.diagnostics.get("error") else "error",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_usd": cost_usd,
                    "diagnostics": json.dumps(result.diagnostics),
                },
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not record run: %s", exc)

    def _load_extractor(self, profile: CompilerProfile) -> Any:
        """Load the extractor declared by the profile."""
        if profile.extractor == "instructor":
            try:
                from riverbank.extractors.instructor_extractor import (  # noqa: PLC0415
                    InstructorExtractor,
                )

                return InstructorExtractor(settings=self._settings)
            except ImportError:
                logger.warning(
                    "instructor not available — falling back to noop extractor"
                )

        from riverbank.extractors.noop import NoOpExtractor  # noqa: PLC0415

        return NoOpExtractor()

    def _load_fragmenter(
        self,
        profile: CompilerProfile,
        corpus_path: str,
        overlap_sentences: int,
        progress_callback: Callable[[str, dict], None] | None,
    ) -> Any:
        """Load the fragmenter declared in *profile.fragmenter*.

        For the ``semantic`` fragmenter, also runs the corpus pre-scan when
        ``semantic_chunking.auto_tune`` is ``true`` and applies adaptive
        parameter tuning before constructing the fragmenter.

        Falls back to ``HeadingFragmenter`` for unknown names.
        """
        from riverbank.fragmenters.heading import HeadingFragmenter  # noqa: PLC0415

        fragmenter_name: str = getattr(profile, "fragmenter", "heading")

        if fragmenter_name == "llm_statement":
            from riverbank.fragmenters.llm_statement import LLMStatementFragmenter  # noqa: PLC0415
            return LLMStatementFragmenter.from_profile(profile, settings=self._settings)

        if fragmenter_name in ("direct", "noop"):
            from riverbank.fragmenters.direct import DirectFragmenter  # noqa: PLC0415
            fallback = HeadingFragmenter(overlap_sentences=overlap_sentences)
            return DirectFragmenter.from_profile(profile, fallback=fallback)

        if fragmenter_name != "semantic":
            return HeadingFragmenter(overlap_sentences=overlap_sentences)

        # --- Semantic fragmenter path ---
        cfg: dict = dict(getattr(profile, "semantic_chunking", {}) or {})
        auto_tune: bool = bool(cfg.get("auto_tune", False))

        if auto_tune:
            cfg = self._auto_tune_semantic(corpus_path, cfg, profile, progress_callback)

        try:
            from riverbank.fragmenters.semantic import SemanticFragmenter  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "riverbank.fragmenters.semantic not available — using HeadingFragmenter"
            )
            return HeadingFragmenter(overlap_sentences=overlap_sentences)

        return SemanticFragmenter(
            model_name=cfg.get("model", "all-MiniLM-L6-v2"),
            similarity_threshold=float(cfg.get("similarity_threshold", 0.75)),
            min_sentences_per_chunk=int(cfg.get("min_sentences_per_chunk", 2)),
            max_sentences_per_chunk=int(cfg.get("max_sentences_per_chunk", 20)),
        )

    def _auto_tune_semantic(
        self,
        corpus_path: str,
        cfg: dict,
        profile: CompilerProfile,
        progress_callback: Callable[[str, dict], None] | None,
    ) -> dict:
        """Run a corpus pre-scan and merge adaptive defaults into *cfg*.

        Manually-specified keys in *cfg* always win.  Returns the merged cfg.
        """
        from riverbank.connectors.fs import FilesystemConnector  # noqa: PLC0415
        from riverbank.fragmenters.scanner import CorpusScanner  # noqa: PLC0415

        p = Path(corpus_path)
        if p.is_dir():
            connector = FilesystemConnector()
            source_paths = [
                rec.path
                for rec in connector.discover({"path": str(p)})
                if rec.path is not None
            ]
        else:
            source_paths = [p]

        if progress_callback:
            progress_callback("corpus_scan_start", {"n_files": len(source_paths)})

        scanner = CorpusScanner()
        scan_result = scanner.scan(source_paths)
        # Store on the pipeline for external introspection
        self._last_scan_result = scan_result

        tuned_cfg = scanner.tune(scan_result, profile_cfg=cfg)

        if progress_callback:
            progress_callback(
                "corpus_scan_done",
                {
                    "num_files": scan_result.num_files,
                    "median_words": scan_result.median_words,
                    "band": scan_result.band,
                    "tuned_params": scan_result.tuned_params,
                },
            )

        logger.info(
            "Auto-tune: band=%s, threshold=%.2f, sentences=%d–%d, length=%d–%d",
            scan_result.band,
            tuned_cfg.get("similarity_threshold"),
            tuned_cfg.get("min_sentences_per_chunk"),
            tuned_cfg.get("max_sentences_per_chunk"),
            tuned_cfg.get("min_fragment_length", 0),
            tuned_cfg.get("max_fragment_length", 0),
        )
        return tuned_cfg


# ---------------------------------------------------------------------------
# v0.5.0 helpers
# ---------------------------------------------------------------------------


def _process_extraction_result(
    conn: Any,
    result: Any,
    frag: Any,
    frag_iri: str,
    source: Any,
    profile: CompilerProfile,
    mode: str,
    stats: dict,
    tracer: Any,
    preprocessing_cfg: dict,
    triple_buffer: list | None = None,
) -> set[str]:
    """Process extraction result (vocabulary or full pass).
    
    v0.17.0: Extracted to support both per-fragment and batch extraction modes.
    v0.15.3: Added optional *triple_buffer* — when not ``None``, triples are
             appended to the buffer instead of written to the database.  The
             caller is responsible for running vocabulary normalisation on the
             buffer and flushing it after all fragments are processed.
    Returns: set of subject IRIs for entity resolution pass.
    """
    from riverbank.catalog.graph import (  # noqa: PLC0415
        load_triples_with_confidence,
        record_artifact_dep,
    )

    frag_subjects: set[str] = set()

    if mode == "vocabulary":
        # Vocabulary pass: convert ExtractedEntity objects to SKOS triples
        entities = getattr(result, "entities", [])
        vocab_triples: list[Any] = []
        for entity in entities:
            vocab_triples.extend(entity.to_skos_triples(profile.vocab_graph))
        # Also treat any triples already returned (noop extractor returns [])
        vocab_triples.extend(result.triples)
        if vocab_triples:
            written = load_triples_with_confidence(
                conn, vocab_triples, profile.vocab_graph
            )
            stats["triples_written"] += written
            # Record artifact deps for each concept subject
            record_artifact_dep(conn, vocab_triples, frag_iri, profile)
    else:
        # Full pass: v0.12.0 per-triple confidence routing
        from riverbank.extractors.ontology_filter import OntologyFilter  # noqa: PLC0415
        from riverbank.prov import ExtractedTriple as _ET  # noqa: PLC0415
        from dataclasses import replace as _dc_r  # noqa: PLC0415

        allowed_predicates: list = getattr(profile, "allowed_predicates", [])
        allowed_classes: list = getattr(profile, "allowed_classes", [])
        ontology_filt = OntologyFilter(allowed_predicates, allowed_classes)

        all_triples = list(result.triples)
        # Accumulate extraction funnel stats from extractor diagnostics
        stats["triples_capped"] += result.diagnostics.get("triples_capped", 0)
        stats["triples_extracted"] += result.diagnostics.get("triples_extracted", len(all_triples))
        stats["triples_citation_rejected"] += result.diagnostics.get("triples_citation_rejected", 0)
        stats["triples_invalid"] += result.diagnostics.get("triples_invalid", 0)

        # Pre-write structural filtering
        passed_triples, rejected_count = ontology_filt.filter(all_triples)
        stats["triples_rejected_ontology"] += rejected_count

        # Literal normalisation + dedup
        passed_triples = ontology_filt.normalize_triples(passed_triples)

        # Per-triple confidence routing
        trusted_triples: list[Any] = []
        tentative_triples: list[Any] = []
        for triple in passed_triples:
            conf = float(getattr(triple, "confidence", 0.0))
            subj = getattr(triple, "subject", "?")
            pred = getattr(triple, "predicate", "?")
            obj = getattr(triple, "object_value", "?")
            if conf >= 0.75:
                trusted_triples.append(triple)
                logger.debug("→ trusted   (conf=%.2f): %s %s %s", conf, subj, pred, obj)
            elif conf >= 0.35:
                # Route to tentative graph
                tentative_triples.append(
                    _ET(
                        subject=triple.subject,
                        predicate=triple.predicate,
                        object_value=triple.object_value,
                        confidence=triple.confidence,
                        evidence=triple.evidence,
                        named_graph=profile.tentative_graph,
                    )
                )
                logger.debug("→ tentative (conf=%.2f): %s %s %s", conf, subj, pred, obj)
            else:
                stats["triples_discarded"] += 1
                logger.debug("→ discarded (conf=%.2f): %s %s %s", conf, subj, pred, obj)

        # Write trusted triples (or buffer for deferred vocab normalisation)
        if trusted_triples:
            if triple_buffer is not None:
                triple_buffer.extend(trusted_triples)
            else:
                written = load_triples_with_confidence(
                    conn, trusted_triples, profile.named_graph
                )
                stats["triples_written"] += written
                stats["triples_trusted"] += written
                record_artifact_dep(conn, trusted_triples, frag_iri, profile)

        # Write tentative triples (or buffer for deferred vocab normalisation)
        if tentative_triples:
            if triple_buffer is not None:
                triple_buffer.extend(tentative_triples)
            else:
                written_tent = load_triples_with_confidence(
                    conn, tentative_triples, profile.tentative_graph
                )
                stats["triples_written"] += written_tent
                stats["triples_tentative"] += written_tent
                record_artifact_dep(conn, tentative_triples, frag_iri, profile)

        logger.info(
            "Fragment %s: %d passed ontology → %d trusted, %d tentative, %d discarded",
            frag_iri.rsplit("#", 1)[-1],
            len(passed_triples),
            len(trusted_triples),
            len(tentative_triples),
            stats["triples_discarded"],
        )

        # v0.16.0: Collect subjects for entity resolution pass
        frag_subjects.update(
            t.subject for t in (trusted_triples + tentative_triples)
            if getattr(t, "subject", None)
        )

        # Embedding generation step (v0.5.0)
        _generate_and_store_embeddings(
            conn, trusted_triples, profile, frag.text
        )

    return frag_subjects


def _generate_and_store_embeddings(
    conn: Any,
    triples: list,
    profile: CompilerProfile,
    fragment_text: str,
) -> None:
    """Generate embeddings for unique triple subjects and store them.

    Uses :class:`~riverbank.embeddings.EmbeddingGenerator` with the profile's
    ``embed_model``.  Falls back silently when sentence-transformers is not
    installed or pg_ripple / pgVector are unavailable.
    """
    if not triples:
        return
    try:
        from riverbank.embeddings import EmbeddingGenerator, store_entity_embedding  # noqa: PLC0415

        generator = EmbeddingGenerator(model_name=profile.embed_model)
        seen_subjects: set[str] = set()
        for triple in triples:
            subject = getattr(triple, "subject", None)
            if not subject or subject in seen_subjects:
                continue
            seen_subjects.add(subject)
            # Use the object value or the fragment text as the embedding input.
            text_for_embedding = getattr(triple, "object_value", None) or fragment_text
            embedding = generator.generate(text_for_embedding)
            if embedding:
                store_entity_embedding(conn, subject, embedding)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Embedding generation step failed: %s", exc)


# ---------------------------------------------------------------------------
# Cost estimation helpers
# ---------------------------------------------------------------------------


def _record_triples_deps(
    conn: Any,
    triples: list,
    frag_iri: str,
    profile: "CompilerProfile",
    record_fn: Any,
) -> None:
    """Record artifact dependency edges for a batch of extracted triples.

    For each unique subject in the triple list we record three edges:
    * ``(subject_iri, fragment, frag_iri)`` — which fragment was the source
    * ``(subject_iri, profile_version, name@vN)`` — which profile version compiled it
    * ``(subject_iri, rule_set, profile_name)`` — which rule set was used
    """
    seen: set[str] = set()
    profile_ver = f"{profile.name}@v{profile.version}"
    for triple in triples:
        subject = getattr(triple, "subject", None)
        if not subject or subject in seen:
            continue
        seen.add(subject)
        record_fn(conn, subject, "fragment", frag_iri)
        record_fn(conn, subject, "profile_version", profile_ver)
        record_fn(conn, subject, "rule_set", profile.name)


def _estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    profile: CompilerProfile,
) -> float:
    from riverbank.cost_tables import estimate_cost  # noqa: PLC0415

    return estimate_cost(prompt_tokens, completion_tokens, profile.model_name)


def _estimate_cost_single(
    prompt_tokens: int,
    completion_tokens: int,
    profile: CompilerProfile,
) -> float:
    return _estimate_cost(prompt_tokens, completion_tokens, profile)


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------


def _gate_config_from_profile(profile: CompilerProfile) -> Any:
    from riverbank.ingest_gate import IngestGateConfig  # noqa: PLC0415

    ep = profile.editorial_policy or {}
    return IngestGateConfig(
        min_heading_depth=ep.get("min_heading_depth", 0),
        min_fragment_length=ep.get("min_fragment_length", 50),
        max_fragment_length=ep.get("max_fragment_length", 8000),
        allowed_languages=ep.get("allowed_languages", ["en"]),
        require_heading=ep.get("require_heading", False),
    )


def _confidence_threshold(profile: CompilerProfile) -> float:
    ep = profile.editorial_policy or {}
    return float(ep.get("confidence_threshold", 0.7))


# ---------------------------------------------------------------------------
# v0.15.4: Predicate guidance helpers
# ---------------------------------------------------------------------------


def _build_predicate_hints_block(
    hint_predicates: dict[str, list[str]],
) -> str:
    """Build the PREDICATE HINTS block for injection into the extraction prompt.

    Args:
        hint_predicates: Dict with keys ``"high"``, ``"medium"``, ``"exploratory"``
                         mapping to lists of predicate IRI strings.

    Returns:
        A formatted multi-line string block, or empty string if no hints.
    """
    high = hint_predicates.get("high", [])
    medium = hint_predicates.get("medium", [])
    exploratory = hint_predicates.get("exploratory", [])

    if not (high or medium or exploratory):
        return ""

    lines = [
        "PREDICATE HINTS (prefer these when relevant, but propose others freely):",
    ]
    if high:
        lines.append(f"  High confidence:   {', '.join(high)}")
    if medium:
        lines.append(f"  Medium confidence: {', '.join(medium)}")
    if exploratory:
        lines.append(f"  Exploratory:       {', '.join(exploratory)}")

    return "\n".join(lines)
