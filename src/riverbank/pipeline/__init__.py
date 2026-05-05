from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
    competency_questions: list = field(default_factory=list)
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
    ) -> None:
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415

            settings = get_settings()
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
    ) -> dict:
        """Run the pipeline against a corpus directory or single file.

        Returns a stats dict:
        ``fragments_processed``, ``fragments_skipped``, ``fragments_skipped_hash``,
        ``triples_written``, ``llm_calls``, ``prompt_tokens``, ``completion_tokens``,
        ``cost_usd``, ``errors``.
        """
        if profile is None:
            profile = CompilerProfile.default()

        tracer = otel_trace.get_tracer(__name__)
        with tracer.start_as_current_span("ingest_pipeline.run") as span:
            stats = self._run_inner(corpus_path, profile, dry_run, span)
            span.set_attribute("ingest.fragments_processed", stats["fragments_processed"])
            span.set_attribute("ingest.fragments_skipped", stats["fragments_skipped"])
            span.set_attribute("ingest.triples_written", stats["triples_written"])
            return stats

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_inner(
        self,
        corpus_path: str,
        profile: CompilerProfile,
        dry_run: bool,
        span: Any,
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
    ) -> None:
        from riverbank.catalog.graph import (  # noqa: PLC0415
            load_triples_with_confidence,
            shacl_score,
        )

        doc = parser.parse(source)
        fragments = list(fragmenter.fragment(doc))
        existing_hashes = self._get_existing_hashes(conn, source.iri)
        tracer = otel_trace.get_tracer(__name__)

        for frag in fragments:
            frag_hash_hex = frag.content_hash.hex()

            # Fragment hash check — skip if content unchanged
            if (
                frag.fragment_key in existing_hashes
                and existing_hashes[frag.fragment_key] == frag_hash_hex
            ):
                stats["fragments_skipped_hash"] += 1
                stats["fragments_skipped"] += 1
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
                continue

            stats["fragments_processed"] += 1

            if dry_run:
                # In dry-run mode we parse + fragment but skip extraction
                continue

            # Upsert source record (needed before we can upsert fragments)
            self._ensure_source(conn, source, profile)

            # Extract triples
            with tracer.start_as_current_span("ingest_pipeline.extract") as ex_span:
                ex_span.set_attribute("fragment.key", frag.fragment_key)
                result = extractor.extract(fragment=frag, profile=profile, trace=None)

            stats["llm_calls"] += result.diagnostics.get("llm_calls", 0)
            stats["prompt_tokens"] += result.diagnostics.get("prompt_tokens", 0)
            stats["completion_tokens"] += result.diagnostics.get("completion_tokens", 0)

            # Route by SHACL score
            score = shacl_score(conn, profile.named_graph, profile)
            threshold = _confidence_threshold(profile)
            target_graph = profile.named_graph if score >= threshold else "<draft>"

            # Write triples to the knowledge graph
            if result.triples:
                written = load_triples_with_confidence(conn, result.triples, target_graph)
                stats["triples_written"] += written

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
                    "VALUES (:name, :version, :schema_json::jsonb, :prompt_hash, :prompt_text, "
                    "        :editorial_policy::jsonb, :model_provider, :model_name, "
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
            return int(row[0]) if row else None
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
                    "        :cost_usd, :diagnostics::jsonb)"
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
# Cost estimation helpers
# ---------------------------------------------------------------------------


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
