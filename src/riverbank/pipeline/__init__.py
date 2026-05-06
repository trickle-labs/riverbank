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
        ``cost_usd``, ``errors``.
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
        }
        with tracer.start_as_current_span("ingest_pipeline.run") as span:
            for run_mode in sequence:
                stats = self._run_inner(corpus_path, profile, dry_run, span, run_mode, progress_callback)
                for k in combined:
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
        progress_callback: Callable[[str, dict], None] | None = None,
    ) -> dict:
        from riverbank.connectors.fs import FilesystemConnector  # noqa: PLC0415
        from riverbank.fragmenters.heading import HeadingFragmenter  # noqa: PLC0415
        from riverbank.ingest_gate import IngestGate, IngestGateConfig  # noqa: PLC0415
        from riverbank.parsers.markdown import MarkdownParser  # noqa: PLC0415

        connector = FilesystemConnector()
        parser = MarkdownParser()
        fragmenter = HeadingFragmenter()
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
                            progress_callback=progress_callback,
                            preprocessor=preprocessor,
                            few_shot_injector=few_shot_injector,
                            corpus_analysis=corpus_analysis,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Failed to process %s: %s", source.iri, exc)
                        src_span.set_status(otel_trace.StatusCode.ERROR, str(exc))
                        stats["errors"] += 1

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
        fragments = list(fragmenter.fragment(doc))
        existing_hashes = self._get_existing_hashes(conn, source.iri)
        tracer = otel_trace.get_tracer(__name__)

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

            # Fragment hash check — skip if content unchanged
            if (
                frag.fragment_key in existing_hashes
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

            # Upsert source record (needed before we can upsert fragments)
            self._ensure_source(conn, source, profile)

            # NER pre-resolution step (v0.5.0) — runs before the LLM call.
            # When a vocabulary pass has run, matched concept IRIs are injected
            # into the structured context block passed to the extractor.
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

            # Extract triples
            with tracer.start_as_current_span("ingest_pipeline.extract") as ex_span:
                ex_span.set_attribute("fragment.key", frag.fragment_key)
                # §3.1 Per-fragment entity catalog filtering: rebuild the enriched
                # prompt with only entities relevant to this fragment's text.
                frag_profile = extraction_profile
                if preprocess_result is not None and preprocessor is not None:
                    from dataclasses import replace as _dc_replace_frag  # noqa: PLC0415
                    filtered_prompt = preprocessor.build_extraction_prompt(
                        preprocess_result, profile, fragment_text=frag.text
                    )
                    frag_profile = _dc_replace_frag(extraction_profile, prompt_text=filtered_prompt)
                # Strategy 6: inject few-shot examples into the extraction prompt
                if few_shot_injector is not None and not dry_run:
                    from dataclasses import replace as _dc_replace2  # noqa: PLC0415
                    enriched_with_shots = few_shot_injector.inject(
                        frag_profile.prompt_text, profile
                    )
                    if enriched_with_shots != frag_profile.prompt_text:
                        frag_profile = _dc_replace2(frag_profile, prompt_text=enriched_with_shots)
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

            if mode == "vocabulary":
                # Vocabulary pass: convert ExtractedEntity objects to SKOS triples
                # and write them to the <vocab> graph.
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
                    _record_triples_deps(
                        conn, vocab_triples, frag_iri, profile, record_artifact_dep
                    )
            else:
                # Full pass: standard SHACL-gated extraction to the trusted graph
                score = shacl_score(conn, profile.named_graph, profile)
                threshold = _confidence_threshold(profile)
                target_graph = profile.named_graph if score >= threshold else "<draft>"

                if result.triples:
                    written = load_triples_with_confidence(
                        conn, result.triples, target_graph
                    )
                    stats["triples_written"] += written
                    # Record artifact dependency edges for each subject
                    _record_triples_deps(
                        conn, result.triples, frag_iri, profile, record_artifact_dep
                    )

                # Embedding generation step (v0.5.0) — generate embeddings for
                # each unique subject and store them via pg_ripple / pgVector.
                _generate_and_store_embeddings(
                    conn, result.triples, profile, frag.text
                )

            # Record fragment + run in the catalog
            self._upsert_fragment(conn, source, frag)
            self._record_run(conn, source, frag, profile, result)

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


# ---------------------------------------------------------------------------
# v0.5.0 helpers
# ---------------------------------------------------------------------------


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
