from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# SQL functions provided by the pg_ripple extension
_LOAD_TRIPLES_SQL = "SELECT pg_ripple.load_triples_with_confidence($1::jsonb, $2)"
_SHACL_SCORE_SQL = "SELECT pg_ripple.shacl_score($1)"


def load_triples_with_confidence(
    conn: Any,
    triples: list,
    named_graph: str,
) -> int:
    """Write extracted triples to a named graph via pg_ripple.

    Calls ``pg_ripple.load_triples_with_confidence(triples_json, named_graph)``
    and returns the number of triples submitted.

    Falls back gracefully (logs a warning, returns 0) when pg_ripple is not
    installed in the target database — this allows the catalog plumbing to be
    tested against stock PostgreSQL in CI.

    Each element of ``triples`` must be an ``ExtractedTriple`` (or any object
    with ``.subject``, ``.predicate``, ``.object_value``, ``.confidence``, and
    ``.evidence`` attributes).
    """
    if not triples:
        return 0

    rows = []
    for t in triples:
        ev: Any | None = getattr(t, "evidence", None)
        rows.append(
            {
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object_value,
                "confidence": t.confidence,
                "named_graph": getattr(t, "named_graph", named_graph),
                "prov_fragment_iri": getattr(ev, "source_iri", "") if ev else "",
                "prov_char_start": getattr(ev, "char_start", 0) if ev else 0,
                "prov_char_end": getattr(ev, "char_end", 0) if ev else 0,
                "prov_excerpt": getattr(ev, "excerpt", "") if ev else "",
            }
        )

    try:
        conn.execute(_LOAD_TRIPLES_SQL, (json.dumps(rows), named_graph))
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.warning(
                "pg_ripple not available — triples not written to graph. "
                "Install pg_ripple to enable graph persistence. error=%s",
                exc,
            )
            return 0
        raise


def shacl_score(
    conn: Any,
    named_graph: str,
    profile: Any = None,
) -> float:
    """Run SHACL validation on a named graph and return a quality score [0, 1].

    Calls ``pg_ripple.shacl_score(named_graph)`` and returns the score.

    Falls back to ``1.0`` (pass-through / treat all output as trusted) when
    pg_ripple is not installed.
    """
    try:
        row = conn.execute(_SHACL_SCORE_SQL, (named_graph,)).fetchone()
        return float(row[0]) if row else 1.0
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.debug(
                "pg_ripple not available — shacl_score returns 1.0 (pass-through). error=%s",
                exc,
            )
            return 1.0
        raise


def sparql_query(
    conn: Any,
    sparql: str,
    named_graph: str | None = None,
) -> list[dict]:
    """Execute a SPARQL SELECT or ASK query via pg_ripple.

    Returns a list of result row dicts for SELECT queries, or a single dict
    ``{"result": True/False}`` for ASK queries.

    Falls back gracefully (logs a warning, returns ``[]``) when pg_ripple is
    not installed — this allows the catalog plumbing to be tested against
    stock PostgreSQL in CI.
    """
    sql = (
        "SELECT * FROM pg_ripple.sparql_query($1, $2)"
        if named_graph
        else "SELECT * FROM pg_ripple.sparql_query($1)"
    )
    try:
        params = (sparql, named_graph) if named_graph else (sparql,)
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            return []
        # Convert each Row to a plain dict
        return [dict(row._mapping) if hasattr(row, "_mapping") else dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.warning(
                "pg_ripple not available — SPARQL query not executed. "
                "Install pg_ripple to enable graph queries. error=%s",
                exc,
            )
            return []
        raise


def record_artifact_dep(
    conn: Any,
    artifact_iri: str,
    dep_kind: str,
    dep_ref: str,
) -> None:
    """Upsert one edge in the artifact dependency graph.

    Inserts ``(artifact_iri, dep_kind, dep_ref)`` into
    ``_riverbank.artifact_deps``.  Silently ignores conflicts (idempotent).

    Falls back gracefully when the table does not exist (e.g. stock
    PostgreSQL without migrations applied).
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        conn.execute(
            text(
                "INSERT INTO _riverbank.artifact_deps (artifact_iri, dep_kind, dep_ref) "
                "VALUES (:artifact_iri, :dep_kind, :dep_ref) "
                "ON CONFLICT DO NOTHING"
            ),
            {"artifact_iri": artifact_iri, "dep_kind": dep_kind, "dep_ref": dep_ref},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_artifact_dep failed: %s", exc)


def get_artifact_deps(conn: Any, artifact_iri: str) -> list[dict]:
    """Return all dependency edges for a given artifact IRI.

    Returns a list of dicts with keys ``dep_kind`` and ``dep_ref``,
    or an empty list when the table is not found or the artifact is unknown.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        rows = conn.execute(
            text(
                "SELECT dep_kind, dep_ref "
                "FROM _riverbank.artifact_deps "
                "WHERE artifact_iri = :iri "
                "ORDER BY dep_kind, dep_ref"
            ),
            {"iri": artifact_iri},
        ).fetchall()
        return [{"dep_kind": r[0], "dep_ref": r[1]} for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_artifact_deps failed: %s", exc)
        return []


def get_artifacts_depending_on_fragment(conn: Any, fragment_iri: str) -> list[str]:
    """Return artifact IRIs that depend on the given fragment.

    Used during recompile to find which compiled artifacts must be
    invalidated when a fragment changes.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        rows = conn.execute(
            text(
                "SELECT DISTINCT artifact_iri "
                "FROM _riverbank.artifact_deps "
                "WHERE dep_kind = 'fragment' AND dep_ref = :frag "
                "ORDER BY artifact_iri"
            ),
            {"frag": fragment_iri},
        ).fetchall()
        return [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_artifacts_depending_on_fragment failed: %s", exc)
        return []


def delete_artifact_deps(conn: Any, artifact_iri: str) -> int:
    """Delete all dependency edges for the given artifact IRI.

    Returns the number of rows deleted, or 0 on error.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        result = conn.execute(
            text(
                "DELETE FROM _riverbank.artifact_deps WHERE artifact_iri = :iri"
            ),
            {"iri": artifact_iri},
        )
        return result.rowcount
    except Exception as exc:  # noqa: BLE001
        logger.debug("delete_artifact_deps failed: %s", exc)
        return 0


def emit_outbox_event(
    conn: Any,
    event_type: str,
    payload: dict,
) -> bool:
    """Emit a semantic diff event on the pg-trickle outbox.

    Calls ``pgtrickle.attach_outbox(event_type, payload::jsonb)``.

    Falls back gracefully (logs a warning, returns ``False``) when
    pg-trickle is not installed — this preserves the ability to run
    riverbank without a CDC relay sidecar.
    """
    try:
        import json as _json  # noqa: PLC0415

        conn.execute(
            "SELECT pgtrickle.attach_outbox($1, $2::jsonb)",
            (event_type, _json.dumps(payload)),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_pgtrickle(msg):
            logger.warning(
                "pg-trickle not available — outbox event not emitted. "
                "Install pg-trickle to enable CDC relay. error=%s",
                exc,
            )
            return False
        raise


def load_shape_bundle(conn: Any, bundle_name: str) -> bool:
    """Activate a named shape bundle via pg_ripple.

    Calls ``pg_ripple.load_shape_bundle(bundle_name)``.  Returns ``True``
    when the bundle was loaded, ``False`` when pg_ripple is unavailable.
    """
    try:
        conn.execute(
            "SELECT pg_ripple.load_shape_bundle($1)",
            (bundle_name,),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.warning(
                "pg_ripple not available — shape bundle '%s' not loaded. error=%s",
                bundle_name,
                exc,
            )
            return False
        raise


def run_shape_bundle(
    conn: Any,
    bundle_name: str,
    named_graph: str,
) -> list[dict]:
    """Run a named shape bundle against a named graph via pg_ripple.

    Returns a list of validation result dicts, or an empty list when
    pg_ripple is unavailable.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.run_shape_bundle($1, $2)",
            (bundle_name, named_graph),
        ).fetchall()
        if not rows:
            return []
        return [dict(r._mapping) if hasattr(r, "_mapping") else dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.warning(
                "pg_ripple not available — shape bundle run skipped. error=%s",
                exc,
            )
            return []
        raise


def _is_missing_extension(error_msg: str) -> bool:
    """Return True when the error indicates a missing pg_ripple extension."""
    keywords = ("pg_ripple", "does not exist", "undefined function", "unknown function")
    return any(kw in error_msg for kw in keywords)


def _is_missing_pgtrickle(error_msg: str) -> bool:
    """Return True when the error indicates a missing pg-trickle extension."""
    keywords = ("pgtrickle", "does not exist", "undefined function", "unknown function")
    return any(kw in error_msg for kw in keywords)
