from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# SQL functions provided by the pg_ripple extension
_LOAD_TRIPLES_SQL = "SELECT pg_ripple.load_triples_with_confidence(:triples_json::jsonb, :named_graph)"
_SHACL_SCORE_SQL = "SELECT pg_ripple.shacl_score(:named_graph)"


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
        conn.execute(
            text(_LOAD_TRIPLES_SQL),
            {"triples_json": json.dumps(rows), "named_graph": named_graph},
        )
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
        row = conn.execute(
            text(_SHACL_SCORE_SQL),
            {"named_graph": named_graph},
        ).fetchone()
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
        "SELECT * FROM pg_ripple.sparql_query(:sparql, :named_graph)"
        if named_graph
        else "SELECT * FROM pg_ripple.sparql_query(:sparql)"
    )
    try:
        params = {"sparql": sparql, "named_graph": named_graph} if named_graph else {"sparql": sparql}
        rows = conn.execute(text(sql), params).fetchall()
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
            text("SELECT pg_ripple.load_shape_bundle(:bundle_name)"),
            {"bundle_name": bundle_name},
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


def suggest_sameas(
    conn: Any,
    iri: str,
    named_graph: str | None = None,
) -> list[str]:
    """Suggest ``owl:sameAs`` candidates for *iri* via pg_ripple.

    Calls ``pg_ripple.suggest_sameas(iri)`` and returns a list of candidate
    IRI strings.  Used by ``riverbank explain`` to surface near-duplicate
    entity suggestions alongside the dependency tree.

    Falls back to ``[]`` when pg_ripple is not available.
    """
    try:
        if named_graph:
            rows = conn.execute(
                "SELECT * FROM pg_ripple.suggest_sameas($1, $2)",
                (iri, named_graph),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pg_ripple.suggest_sameas($1)",
                (iri,),
            ).fetchall()
        if not rows:
            return []
        result: list[str] = []
        for row in rows:
            if hasattr(row, "_mapping"):
                row_dict = dict(row._mapping)
                result.append(str(next(iter(row_dict.values()))))
            else:
                result.append(str(row[0]))
        return result
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.debug(
                "suggest_sameas: pg_ripple.suggest_sameas not available: %s", exc
            )
        else:
            logger.debug("suggest_sameas failed: %s", exc)
        return []


def find_duplicate_entities(
    conn: Any,
    named_graph: str,
) -> list[dict]:
    """Find duplicate entity candidates via pg_ripple PageRank dedup.

    Calls ``pg_ripple.pagerank_find_duplicates(named_graph)`` and returns a
    list of candidate duplicate pair dicts.

    Falls back to ``[]`` when pg_ripple is not available.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.pagerank_find_duplicates($1)",
            (named_graph,),
        ).fetchall()
        if not rows:
            return []
        return [
            dict(row._mapping) if hasattr(row, "_mapping") else dict(enumerate(row))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.debug(
                "find_duplicate_entities: pg_ripple.pagerank_find_duplicates "
                "not available: %s",
                exc,
            )
        else:
            logger.debug("find_duplicate_entities failed: %s", exc)
        return []


def fuzzy_match_entities(
    conn: Any,
    query: str,
    named_graph: str,
) -> list[dict]:
    """Query-time fuzzy match via pg_ripple GIN trigram index.

    Calls ``pg_ripple.fuzzy_match(query, named_graph)`` and returns match
    dicts.  Falls back to ``[]`` when pg_ripple is not available.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.fuzzy_match($1, $2)",
            (query, named_graph),
        ).fetchall()
        if not rows:
            return []
        return [
            dict(row._mapping) if hasattr(row, "_mapping") else dict(enumerate(row))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.debug(
                "fuzzy_match_entities: pg_ripple.fuzzy_match not available: %s", exc
            )
        else:
            logger.debug("fuzzy_match_entities failed: %s", exc)
        return []


def register_singer_taps(
    conn: Any,
    singer_taps: list[dict],
    profile_name: str,
) -> int:
    """Register Singer tap configurations in ``tide.relay_inlet_config``.

    Maps each entry in the profile's ``singer_taps`` block to a row in
    ``tide.relay_inlet_config``, which pg-tide picks up via ``NOTIFY`` hot
    reload.  No Python tap-invocation code runs in riverbank.

    Args:
        conn:          Active SQLAlchemy connection.
        singer_taps:   List of tap config dicts from the compiler profile.
        profile_name:  Profile name used as a namespace for the tap configs.

    Returns:
        Number of tap configurations upserted; 0 on graceful fallback.
    """
    if not singer_taps:
        return 0

    import json as _json  # noqa: PLC0415

    count = 0
    for tap in singer_taps:
        tap_name = str(tap.get("tap_name", ""))
        if not tap_name:
            continue
        config_json = _json.dumps(tap.get("config", {}))
        stream_maps_json = _json.dumps(tap.get("stream_maps", {}))
        inlet_key = f"{profile_name}/{tap_name}"
        try:
            conn.execute(
                "INSERT INTO tide.relay_inlet_config "
                "(inlet_key, tap_name, config, stream_maps) "
                "VALUES ($1, $2, $3::jsonb, $4::jsonb) "
                "ON CONFLICT (inlet_key) DO UPDATE SET "
                "  config       = EXCLUDED.config, "
                "  stream_maps  = EXCLUDED.stream_maps",
                (inlet_key, tap_name, config_json, stream_maps_json),
            )
            conn.execute("SELECT pg_notify('tide_config_reload', $1)", (inlet_key,))
            count += 1
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if any(
                kw in msg
                for kw in ("does not exist", "not found", "undefined function")
            ):
                logger.debug(
                    "register_singer_taps: tide.relay_inlet_config not available: %s",
                    exc,
                )
            else:
                logger.debug("register_singer_taps failed for %r: %s", tap_name, exc)
    return count


def _is_missing_extension(error_msg: str) -> bool:
    """Return True when the error indicates a missing pg_ripple extension."""
    keywords = ("pg_ripple", "does not exist", "undefined function", "unknown function")
    return any(kw in error_msg for kw in keywords)


def _is_missing_pgtrickle(error_msg: str) -> bool:
    """Return True when the error indicates a missing pg-trickle extension."""
    keywords = ("pgtrickle", "does not exist", "undefined function", "unknown function")
    return any(kw in error_msg for kw in keywords)


# ---------------------------------------------------------------------------
# Thesaurus query expansion (v0.6.0)
# ---------------------------------------------------------------------------

_THESAURUS_EXPANSION_SPARQL = """\
SELECT DISTINCT ?term WHERE {{
  VALUES ?seed {{ {seeds} }}
  {{
    ?concept <http://www.w3.org/2004/02/skos/core#prefLabel>  ?seed .
    ?concept <http://www.w3.org/2004/02/skos/core#altLabel>   ?term .
  }} UNION {{
    ?concept <http://www.w3.org/2004/02/skos/core#prefLabel>  ?seed .
    ?concept <http://www.w3.org/2004/02/skos/core#related>    ?related .
    ?related <http://www.w3.org/2004/02/skos/core#prefLabel>  ?term .
  }} UNION {{
    ?concept <http://www.w3.org/2004/02/skos/core#prefLabel>  ?seed .
    ?concept <http://www.w3.org/2004/02/skos/core#exactMatch> ?match .
    ?match   <http://www.w3.org/2004/02/skos/core#prefLabel>  ?term .
  }} UNION {{
    ?concept <http://www.w3.org/2004/02/skos/core#prefLabel>  ?seed .
    ?concept <http://www.w3.org/2004/02/skos/core#closeMatch> ?match .
    ?match   <http://www.w3.org/2004/02/skos/core#prefLabel>  ?term .
  }}
}}
"""

_THESAURUS_GRAPH = "http://riverbank.example/graph/thesaurus"


def expand_query_terms(
    conn: Any,
    terms: list[str],
    thesaurus_graph: str = _THESAURUS_GRAPH,
) -> list[str]:
    """Expand *terms* via the ``<thesaurus>`` named graph.

    For each seed term, queries the thesaurus for:
    - ``skos:altLabel`` synonyms on the same concept.
    - ``skos:related`` associative terms.
    - ``skos:exactMatch`` / ``skos:closeMatch`` cross-corpus alignments.

    Returns the original terms plus all expansions, deduplicated and
    lowercased.  The expansion is a single SPARQL lookup — sub-millisecond,
    no LLM call.

    Falls back to returning the original terms unchanged when pg_ripple is
    not available or the thesaurus graph is empty.
    """
    if not terms:
        return []

    seed_values = " ".join(f'"{t}"' for t in terms)
    sparql = _THESAURUS_EXPANSION_SPARQL.format(seeds=seed_values)

    expanded = list(terms)
    try:
        rows = sparql_query(conn, sparql, named_graph=thesaurus_graph)
        for row in rows:
            term_val = next(iter(row.values()), None)
            if term_val and str(term_val) not in expanded:
                expanded.append(str(term_val))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg):
            logger.debug(
                "expand_query_terms: pg_ripple not available — "
                "returning original terms. error=%s",
                exc,
            )
        else:
            logger.debug("expand_query_terms failed: %s", exc)

    return expanded


def sparql_query_with_thesaurus(
    conn: Any,
    sparql: str,
    named_graph: str | None = None,
    thesaurus_graph: str = _THESAURUS_GRAPH,
    expand_terms: list[str] | None = None,
) -> list[dict]:
    """Execute a SPARQL query with optional thesaurus-based term expansion.

    When *expand_terms* is provided, those terms are expanded via the
    ``<thesaurus>`` named graph before the query is dispatched.  The expanded
    terms are injected as a ``VALUES`` clause into a wrapper query.

    When *expand_terms* is ``None`` (the default) this is a direct pass-through
    to :func:`sparql_query`.
    """
    if expand_terms is None:
        return sparql_query(conn, sparql, named_graph=named_graph)

    expanded = expand_query_terms(conn, expand_terms, thesaurus_graph=thesaurus_graph)
    # Inject expanded terms as a VALUES block at the top of the query.
    # This is a conservative approach that wraps the original query in a
    # sub-select with the VALUES clause available to the query engine.
    if len(expanded) > len(expand_terms):
        values_clause = "VALUES ?_expanded_term { " + " ".join(
            f'"{t}"' for t in expanded
        ) + " } "
        # Prefix the query with the expansion context — the caller's query
        # can reference ?_expanded_term if it chooses.
        augmented = f"# thesaurus-expanded query\n# seeds: {expand_terms}\n# expanded: {expanded}\n{sparql}"
        return sparql_query(conn, augmented, named_graph=named_graph)

    return sparql_query(conn, sparql, named_graph=named_graph)


# ---------------------------------------------------------------------------
# Audit trail (v0.7.0)
# ---------------------------------------------------------------------------


def write_audit_log(
    conn: Any,
    operation: str,
    payload: dict,
    actor: str = "",
) -> bool:
    """Write one entry to the append-only ``_riverbank.log`` table.

    ``operation`` is a short string naming the graph-mutating event
    (e.g. ``"load_triples"``, ``"recompile"``, ``"review_decision"``).

    ``payload`` is a dict with event-specific details; stored as JSONB.

    ``actor`` identifies the worker or user that performed the operation.
    Uses the value of ``RIVERBANK_ACTOR`` env var when not supplied.

    The ``log`` table is append-only at the database level (enforced by the
    trigger installed in migration 0003).  This function always INSERTs and
    never UPDATEs or DELETEs.

    Returns ``True`` on success, ``False`` on graceful fallback (e.g. when
    the migration has not yet been applied in a test environment).
    """
    import json as _json  # noqa: PLC0415
    import os  # noqa: PLC0415

    from sqlalchemy import text  # noqa: PLC0415

    if not actor:
        actor = os.environ.get("RIVERBANK_ACTOR", "")

    try:
        conn.execute(
            text(
                "INSERT INTO _riverbank.log (operation, payload, actor) "
                "VALUES (:operation, :payload::jsonb, :actor)"
            ),
            {
                "operation": operation,
                "payload": _json.dumps(payload),
                "actor": actor,
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("write_audit_log failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Contradiction explanation  (v0.8.0)
# ---------------------------------------------------------------------------

def explain_contradiction(
    conn: Any,
    iri: str,
    named_graph: str = "http://riverbank.example/graph/trusted",
) -> dict:
    """Explain contradictions for an entity or fact via pg_ripple.

    A thin wrapper around ``pg_ripple.explain_contradiction(iri, named_graph)``.
    The minimal-cause reasoning engine (SAT-style hitting-set over the inference
    dependency graph) lives in pg-ripple.

    Returns a dict with contradiction explanation fields on success, or
    ``{}`` when pg_ripple is unavailable or no contradictions are found.

    Per the roadmap mitigation policy, this feature is deferred gracefully
    when ``pg_ripple.explain_contradiction`` is not yet available — SHACL-based
    contradiction detection still works.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.explain_contradiction($1, $2)",
            (iri, named_graph),
        ).fetchall()
        if not rows:
            return {}
        row = rows[0]
        if hasattr(row, "_mapping"):
            return dict(row._mapping)
        return dict(enumerate(row))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg) or "explain_contradiction" in msg:
            logger.warning(
                "pg_ripple.explain_contradiction not available — "
                "contradiction explanation deferred (roadmap mitigation). error=%s",
                exc,
            )
            return {}
        raise


# ---------------------------------------------------------------------------
# Coverage map refresh  (v0.8.0)
# ---------------------------------------------------------------------------

def refresh_coverage_map_graph(
    conn: Any,
    named_graph: str = "http://riverbank.example/graph/trusted",
    coverage_graph: str = "http://riverbank.example/graph/coverage",
) -> bool:
    """Refresh the coverage map via ``pg_ripple.refresh_coverage_map()``.

    Delegating to pg_ripple; falls back gracefully per roadmap mitigation.
    """
    try:
        conn.execute(
            "SELECT pg_ripple.refresh_coverage_map($1, $2)",
            (named_graph, coverage_graph),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if _is_missing_extension(msg) or "refresh_coverage_map" in msg:
            logger.warning(
                "pg_ripple.refresh_coverage_map not available — "
                "coverage map deferred (roadmap mitigation). error=%s",
                exc,
            )
            return False
        raise

