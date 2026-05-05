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


def _is_missing_extension(error_msg: str) -> bool:
    """Return True when the error indicates a missing pg_ripple extension."""
    keywords = ("pg_ripple", "does not exist", "undefined function", "unknown function")
    return any(kw in error_msg for kw in keywords)
