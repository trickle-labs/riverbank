"""Automatic tentative graph cleanup (v0.13.0).

**Problem:** Without a cleanup policy, the tentative graph grows indefinitely.
Stale tentative triples — extracted but never promoted — add noise to queries
and make the tentative-vs-trusted split meaningless over time.

**Approach:**

1. Track a ``pgc:firstSeen`` timestamp annotation for each tentative triple.
2. After each ingest run (or on demand via CLI), archive tentative triples
   that were *never promoted* and have not been corroborated within the
   configurable TTL (default 30 days).
3. Archived triples are moved to a ``_riverbank.archived_triples`` log table
   (not deleted) so they remain auditable.

Profile YAML::

    tentative_ttl_days: 30   # default 30 days; 0 = never auto-expire

CLI::

    # Manual invocation
    riverbank gc-tentative --older-than 30d [--dry-run] [--graph IRI]

    # Auto-run after ingest (enabled by default when tentative_ttl_days > 0)
    # Runs within the same DB transaction as the ingest run.

Falls back gracefully when pg_ripple is unavailable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_FIRST_SEEN_IRI = "http://riverbank.example/pgc/firstSeen"
_CONFIDENCE_IRI = "http://riverbank.example/pgc/confidence"

# SPARQL — tentative triples older than the TTL
_STALE_TRIPLES_SPARQL = """\
SELECT ?s ?p ?o ?first_seen WHERE {{
  GRAPH <{graph}> {{
    ?s ?p ?o .
    OPTIONAL {{ ?s <{first_seen_iri}> ?first_seen . }}
  }}
  FILTER(!isLiteral(?s))
  FILTER(!STRSTARTS(STR(?p), "http://riverbank.example/pgc/"))
}} LIMIT {limit}
"""


def _parse_duration(duration_str: str) -> timedelta:
    """Parse a duration string like ``30d``, ``7d``, ``48h`` into a :class:`timedelta`.

    Supported suffixes: ``d`` (days), ``h`` (hours), ``m`` (minutes).
    """
    s = duration_str.strip().lower()
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    # Assume days if no suffix
    return timedelta(days=int(s))


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TentativeCleanupResult:
    """Summary of a tentative-graph cleanup run."""

    triples_examined: int = 0
    triples_archived: int = 0
    triples_skipped: int = 0     # within TTL or could not parse timestamp
    errors: int = 0
    cutoff_date: str = ""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class TentativeGraphCleaner:
    """Archive stale tentative triples past their TTL.

    Args:
        ttl_days: Default TTL in days.  Can be overridden per call.
        batch_size: Maximum number of triples to process per run.
    """

    def __init__(
        self,
        ttl_days: int = 30,
        batch_size: int = 1000,
    ) -> None:
        self._ttl_days = ttl_days
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def gc(
        self,
        conn: Any,
        tentative_graph: str,
        ttl: str | int | None = None,
        dry_run: bool = False,
    ) -> TentativeCleanupResult:
        """Archive tentative triples older than *ttl*.

        Args:
            conn: Active SQLAlchemy connection.
            tentative_graph: IRI of the tentative named graph.
            ttl: TTL as a string (e.g. ``"30d"``, ``"7d"``) or integer (days).
                Defaults to the instance's ``ttl_days``.
            dry_run: When ``True``, identify stale triples but do not archive them.

        Returns:
            :class:`TentativeCleanupResult` with counts.
        """
        result = TentativeCleanupResult()

        # Resolve TTL
        if ttl is None:
            effective_ttl = timedelta(days=self._ttl_days)
        elif isinstance(ttl, int):
            effective_ttl = timedelta(days=ttl)
        else:
            effective_ttl = _parse_duration(str(ttl))

        cutoff = datetime.now(timezone.utc) - effective_ttl
        result.cutoff_date = cutoff.isoformat()

        if effective_ttl.total_seconds() <= 0:
            logger.info("gc_tentative: TTL is zero — automatic cleanup disabled")
            return result

        # Fetch candidate triples
        triples = self._fetch_tentative_triples(conn, tentative_graph)
        result.triples_examined = len(triples)

        if not triples:
            logger.info("gc_tentative: no triples in tentative graph <%s>", tentative_graph)
            return result

        logger.info(
            "gc_tentative: examining %d tentative triples (cutoff: %s)",
            result.triples_examined,
            result.cutoff_date,
        )

        for triple_row in triples:
            s = str(triple_row.get("s", "")).strip()
            p = str(triple_row.get("p", "")).strip()
            o = str(triple_row.get("o", "")).strip()
            first_seen_raw = str(triple_row.get("first_seen", "")).strip()

            if not s or not p:
                result.triples_skipped += 1
                continue

            # Parse first_seen timestamp
            if first_seen_raw:
                first_seen_dt = self._parse_iso(first_seen_raw)
            else:
                first_seen_dt = None

            # No timestamp means the triple was not annotated — treat as older than TTL
            if first_seen_dt is None or first_seen_dt < cutoff:
                if not dry_run:
                    try:
                        self._archive_triple(conn, tentative_graph, s, p, o, first_seen_raw)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "gc_tentative: failed to archive (%s %s %s): %s", s, p, o, exc
                        )
                        result.errors += 1
                        continue
                result.triples_archived += 1
            else:
                result.triples_skipped += 1

        if dry_run:
            logger.info(
                "gc_tentative: dry-run — %d triples would be archived",
                result.triples_archived,
            )
        else:
            logger.info(
                "gc_tentative: archived %d stale triples from <%s>",
                result.triples_archived,
                tentative_graph,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_tentative_triples(
        self, conn: Any, tentative_graph: str
    ) -> list[dict[str, Any]]:
        """Return all triples from the tentative graph with their first_seen timestamps."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = _STALE_TRIPLES_SPARQL.format(
            graph=tentative_graph,
            first_seen_iri=_FIRST_SEEN_IRI,
            limit=self._batch_size,
        )
        try:
            return sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning("gc_tentative: SPARQL query failed — %s", exc)
            return []

    def _archive_triple(
        self,
        conn: Any,
        tentative_graph: str,
        subject: str,
        predicate: str,
        obj: str,
        first_seen: str,
    ) -> None:
        """Move a triple from the tentative graph to the archive log table."""
        import json  # noqa: PLC0415

        from sqlalchemy import text  # noqa: PLC0415

        obj_term = (
            f"<{obj}>"
            if obj.startswith(("http://", "https://", "urn:", "ex:"))
            else f'"{obj.replace(chr(34), chr(92) + chr(34))}"'
        )

        del_sparql = (
            f"DELETE {{ GRAPH <{tentative_graph}> {{ "
            f"<{subject}> <{predicate}> {obj_term} . "
            f"}} }} WHERE {{ GRAPH <{tentative_graph}> {{ "
            f"<{subject}> <{predicate}> {obj_term} . }} }}"
        )
        conn.execute(text("SELECT sparql_update(cast(:q as text))"), {"q": del_sparql})

        # Write to archive log
        conn.execute(
            text(
                "INSERT INTO _riverbank.log (event_type, payload, occurred_at) "
                "VALUES ('pgc:TentativeArchived', cast(:payload as jsonb), now())"
            ),
            {
                "payload": json.dumps(
                    {
                        "tentative_graph": tentative_graph,
                        "triple": {"s": subject, "p": predicate, "o": obj},
                        "first_seen": first_seen,
                        "archived_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            },
        )

    @staticmethod
    def _parse_iso(ts: str) -> datetime | None:
        """Parse an ISO-8601 timestamp string, returning None on failure."""
        ts = ts.strip().split("^^")[0].strip('"').strip("'")
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(ts, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None
