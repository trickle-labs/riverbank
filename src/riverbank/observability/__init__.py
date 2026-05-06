from __future__ import annotations

"""Observability helpers and Prefect flows for riverbank (v0.6.0).

This module introduces Prefect as the workflow orchestrator (v0.6.0).
Two flows are registered here:

* :func:`snapshot_shacl_scores` — daily flow that calls
  ``pg_ripple.shacl_score()`` for each named graph and records the result in
  ``_riverbank.shacl_score_history``.

* :func:`run_nightly_lint` — nightly Prefect flow that runs the full
  ``riverbank lint`` pass, writes ``pgc:LintFinding`` triples to the knowledge
  graph, and returns a summary dict.

Both flows fall back gracefully when Prefect is not installed.
"""

import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from sqlalchemy import create_engine
from typing import Any

logger = logging.getLogger(__name__)

_initialized: bool = False

# Named graphs tracked by default
_DEFAULT_TRACKED_GRAPHS = [
    "http://riverbank.example/graph/trusted",
    "http://riverbank.example/graph/draft",
    "http://riverbank.example/graph/vocab",
    "http://riverbank.example/graph/human-review",
]

# ---------------------------------------------------------------------------
# Prefect flow decorator — degrade gracefully when Prefect is absent
# ---------------------------------------------------------------------------

try:
    from prefect import flow as _prefect_flow  # type: ignore[import-untyped]
    from prefect import task as _prefect_task  # type: ignore[import-untyped]

    _PREFECT_AVAILABLE = True
except ImportError:
    _PREFECT_AVAILABLE = False

    def _prefect_flow(fn=None, **kwargs):  # type: ignore[misc]
        if fn is not None:
            return fn
        def decorator(f):
            return f
        return decorator

    def _prefect_task(fn=None, **kwargs):  # type: ignore[misc]
        if fn is not None:
            return fn
        def decorator(f):
            return f
        return decorator


def setup_tracing(service_name: str = "riverbank") -> None:
    """Configure the OpenTelemetry TracerProvider.

    Phase 0: exports spans to console (stdout) when no OTLP endpoint is set.
    Phase 1+: set OTEL_EXPORTER_OTLP_ENDPOINT to route spans to Langfuse or
    any compatible collector.
    """
    global _initialized
    if _initialized:
        return

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer(name: str = "riverbank") -> trace.Tracer:
    """Return a named tracer from the configured provider."""
    return trace.get_tracer(name)


# ---------------------------------------------------------------------------
# SHACL score history
# ---------------------------------------------------------------------------

@_prefect_task
def _record_shacl_score(conn: Any, named_graph: str) -> dict:
    """Record the current SHACL score for one named graph."""
    from riverbank.catalog.graph import shacl_score  # noqa: PLC0415

    score = shacl_score(conn, named_graph)
    try:
        from sqlalchemy import text  # noqa: PLC0415

        conn.execute(
            text(
                "INSERT INTO _riverbank.shacl_score_history "
                "  (named_graph, score, recorded_at) "
                "VALUES (:graph, :score, now()) "
                "ON CONFLICT DO NOTHING"
            ),
            {"graph": named_graph, "score": score},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("_record_shacl_score: could not insert history row: %s", exc)

    logger.info("shacl_score_history: graph=%r score=%.4f", named_graph, score)
    return {"named_graph": named_graph, "score": score}


@_prefect_flow(name="riverbank-shacl-score-snapshot")
def snapshot_shacl_scores(
    named_graphs: list[str] | None = None,
    db_dsn: str | None = None,
) -> list[dict]:
    """Daily Prefect flow: snapshot ``shacl_score()`` for all tracked graphs.

    Calls ``pg_ripple.shacl_score()`` for each named graph and writes the
    results into ``_riverbank.shacl_score_history``.

    Returns a list of ``{"named_graph": ..., "score": ...}`` dicts.
    """
    if named_graphs is None:
        named_graphs = list(_DEFAULT_TRACKED_GRAPHS)

    if db_dsn is None:
        from riverbank.config import get_settings  # noqa: PLC0415

        db_dsn = get_settings().db.dsn

    engine = create_engine(db_dsn)
    results: list[dict] = []
    try:
        with engine.connect() as conn:
            for graph in named_graphs:
                result = _record_shacl_score(conn, graph)
                results.append(result)
            conn.commit()
    finally:
        engine.dispose()

    return results


# ---------------------------------------------------------------------------
# Lint finding helpers
# ---------------------------------------------------------------------------

@_prefect_task
def _write_lint_finding(
    conn: Any,
    named_graph: str,
    finding_type: str,
    subject_iri: str,
    message: str,
    severity: str = "warning",
) -> None:
    """Write one ``pgc:LintFinding`` triple-set to the knowledge graph."""
    import hashlib  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    finding_iri = (
        "pgc:finding/"
        + hashlib.sha256(f"{named_graph}{subject_iri}{finding_type}".encode()).hexdigest()[:16]
    )

    triples_payload = [
        {"subject": finding_iri, "predicate": "rdf:type",
         "object": "pgc:LintFinding", "confidence": 1.0,
         "named_graph": named_graph, "prov_fragment_iri": "",
         "prov_char_start": 0, "prov_char_end": 0, "prov_excerpt": ""},
        {"subject": finding_iri, "predicate": "pgc:findingType",
         "object": finding_type, "confidence": 1.0,
         "named_graph": named_graph, "prov_fragment_iri": "",
         "prov_char_start": 0, "prov_char_end": 0, "prov_excerpt": ""},
        {"subject": finding_iri, "predicate": "pgc:findingSubject",
         "object": subject_iri, "confidence": 1.0,
         "named_graph": named_graph, "prov_fragment_iri": "",
         "prov_char_start": 0, "prov_char_end": 0, "prov_excerpt": ""},
        {"subject": finding_iri, "predicate": "pgc:findingMessage",
         "object": message, "confidence": 1.0,
         "named_graph": named_graph, "prov_fragment_iri": "",
         "prov_char_start": 0, "prov_char_end": 0, "prov_excerpt": ""},
        {"subject": finding_iri, "predicate": "pgc:severity",
         "object": severity, "confidence": 1.0,
         "named_graph": named_graph, "prov_fragment_iri": "",
         "prov_char_start": 0, "prov_char_end": 0, "prov_excerpt": ""},
    ]

    try:
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)",
            (_json.dumps(triples_payload), named_graph),
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(kw in msg for kw in ("pg_ripple", "does not exist", "undefined function")):
            logger.debug("_write_lint_finding: pg_ripple not available: %s", exc)
        else:
            logger.warning("_write_lint_finding failed: %s", exc)


def run_full_lint(
    conn: Any,
    named_graph: str,
    threshold: float = 0.7,
) -> dict:
    """Run a full lint pass against *named_graph*.

    Combines SHACL quality gate and SKOS integrity shape bundle.
    Violations are written as ``pgc:LintFinding`` triples.

    Returns a summary dict with keys: ``named_graph``, ``shacl_score``,
    ``passed``, ``finding_count``, ``findings``.
    """
    from riverbank.catalog.graph import run_shape_bundle, shacl_score  # noqa: PLC0415

    score = shacl_score(conn, named_graph)
    violations = run_shape_bundle(conn, "skos-integrity", named_graph)

    findings: list[dict] = []
    for v in violations:
        subject_iri = str(v.get("focus_node", v.get("subject", "")))
        finding_type = str(v.get("constraint_component", "shacl:Violation"))
        message = str(v.get("result_message", v.get("message", "SHACL violation")))
        severity = str(v.get("severity", "warning")).lower()

        findings.append(
            {
                "subject_iri": subject_iri,
                "finding_type": finding_type,
                "message": message,
                "severity": severity,
            }
        )
        _write_lint_finding(conn, named_graph, finding_type, subject_iri, message, severity)

    passed = score >= threshold and len(findings) == 0
    return {
        "named_graph": named_graph,
        "shacl_score": score,
        "passed": passed,
        "finding_count": len(findings),
        "findings": findings,
    }


@_prefect_flow(name="riverbank-nightly-lint")
def run_nightly_lint(
    named_graphs: list[str] | None = None,
    threshold: float = 0.7,
    db_dsn: str | None = None,
) -> list[dict]:
    """Nightly Prefect flow: full lint pass across all tracked named graphs.

    For each graph:
    1. Runs the SHACL quality gate.
    2. Runs the ``pg:skos-integrity`` shape bundle.
    3. Writes any violations as ``pgc:LintFinding`` triples.

    Returns a list of lint summary dicts (one per graph).
    """
    if named_graphs is None:
        named_graphs = list(_DEFAULT_TRACKED_GRAPHS)

    if db_dsn is None:
        from riverbank.config import get_settings  # noqa: PLC0415

        db_dsn = get_settings().db.dsn

    engine = create_engine(db_dsn)
    results: list[dict] = []
    try:
        with engine.connect() as conn:
            for graph in named_graphs:
                summary = run_full_lint(conn, graph, threshold=threshold)
                results.append(summary)
            conn.commit()
    finally:
        engine.dispose()

    return results
