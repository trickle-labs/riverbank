"""Contradiction detection & confidence demotion for functional predicates (v0.13.0).

**Problem:** When a functional predicate (``max_cardinality: 1``) is extracted
with two different objects for the same subject, one of them must be wrong.
Without contradiction detection, the graph silently accumulates conflicting
facts and the trusted graph becomes unreliable.

**Approach:**

1. For each predicate annotated as ``max_cardinality: 1`` in the
   ``predicate_constraints`` block of the compiler profile, query the graph
   for all ``(s, p, o)`` triples.
2. Group by ``(s, p)`` — any group with more than one distinct ``o`` is a
   conflict.
3. Reduce confidence of ALL triples in the conflict group by 30%.
4. Demote triples whose new confidence drops below the trusted threshold to
   the tentative graph (or mark them as conflicted).
5. Write a ``pgc:ConflictRecord`` provenance record for each detected conflict.

**Identity verification layer:** Triples that survive contradiction detection
are demonstrably more trustworthy — they have not been contradicted by any
other extraction.

Usage::

    from riverbank.postprocessors.contradiction import ContradictionDetector

    detector = ContradictionDetector(trusted_threshold=0.75)
    result = detector.detect(conn, profile, named_graph, dry_run=True)
    print(result.conflicts_found, "conflicts detected")

Falls back gracefully when pg_ripple is unavailable.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# SPARQL — find all (s, p, o, confidence) for a given functional predicate
_TRIPLES_FOR_PREDICATE_SPARQL = """\
SELECT ?s ?o WHERE {{
  GRAPH <{graph}> {{
    ?s <{predicate}> ?o .
  }}
}} ORDER BY ?s ?o
"""

_CONFIDENCE_IRI = "http://riverbank.example/pgc/confidence"
_CONFIDENCE_SPARQL = """\
SELECT ?confidence WHERE {{
  GRAPH <{graph}> {{
    <{subject}> <{predicate}> {object_term} .
    OPTIONAL {{ <{subject}> <{confidence_iri}> ?confidence . }}
  }}
}}
"""

# Confidence penalty for conflicting triples (30% reduction)
_CONFLICT_PENALTY = 0.30


def _sparql_term(value: str) -> str:
    """Format a value as a SPARQL term (IRI or literal)."""
    if value.startswith(("http://", "https://", "urn:", "ex:")):
        return f"<{value}>"
    escaped = value.replace('"', '\\"').replace("\\", "\\\\")
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConflictRecord:
    """A detected contradiction for a functional predicate.

    Attributes
    ----------
    subject:
        The subject IRI involved in the conflict.
    predicate:
        The functional predicate that triggered the conflict.
    conflicting_objects:
        All distinct object values found for ``(subject, predicate)``.
    confidence_before:
        Confidence scores before the penalty.
    confidence_after:
        Confidence scores after the 30% penalty.
    demoted_objects:
        Object values whose confidence dropped below the trusted threshold.
    detected_at:
        ISO-8601 timestamp of detection.
    """

    subject: str
    predicate: str
    conflicting_objects: list[str]
    confidence_before: dict[str, float] = field(default_factory=dict)
    confidence_after: dict[str, float] = field(default_factory=dict)
    demoted_objects: list[str] = field(default_factory=list)
    detected_at: str = ""


@dataclass
class ContradictionResult:
    """Summary of a contradiction-detection run."""

    functional_predicates_checked: int = 0
    conflicts_found: int = 0
    triples_penalised: int = 0
    triples_demoted: int = 0
    conflict_records: list[ConflictRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ContradictionDetector:
    """Detect and demote triples that conflict on functional predicates.

    Args:
        trusted_threshold: Confidence at or above which triples are kept in
            the trusted graph.  Triples that drop below this after the 30%
            penalty are demoted.  Default 0.75.
        confidence_penalty: Fraction by which conflicting triple confidence is
            reduced.  Default 0.30 (30%).
    """

    def __init__(
        self,
        trusted_threshold: float = 0.75,
        confidence_penalty: float = _CONFLICT_PENALTY,
    ) -> None:
        self._trusted_threshold = trusted_threshold
        self._confidence_penalty = confidence_penalty

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        conn: Any,
        profile: Any,
        named_graph: str,
        tentative_graph: str | None = None,
        dry_run: bool = False,
    ) -> ContradictionResult:
        """Run contradiction detection against *named_graph*.

        Args:
            conn: Active SQLAlchemy connection.
            profile: :class:`~riverbank.pipeline.CompilerProfile` providing
                ``predicate_constraints`` annotations.
            named_graph: IRI of the trusted graph to inspect.
            tentative_graph: IRI of the tentative graph where demoted triples
                are moved.  Defaults to the profile's ``tentative_graph`` if
                available, else ``http://riverbank.example/graph/tentative``.
            dry_run: When ``True``, detect conflicts but do not apply penalties
                or move triples.

        Returns:
            :class:`ContradictionResult` with conflict details.
        """
        result = ContradictionResult()

        if tentative_graph is None:
            tentative_graph = getattr(
                profile,
                "tentative_graph",
                "http://riverbank.example/graph/tentative",
            )

        constraints: dict = getattr(profile, "predicate_constraints", {})
        functional_predicates = [
            pred
            for pred, opts in constraints.items()
            if isinstance(opts, dict) and opts.get("max_cardinality") == 1
        ]

        if not functional_predicates:
            logger.info(
                "contradiction_detector: no functional predicates defined in profile"
            )
            return result

        result.functional_predicates_checked = len(functional_predicates)
        now_iso = datetime.now(timezone.utc).isoformat()

        for predicate in functional_predicates:
            conflicts = self._find_conflicts(conn, named_graph, predicate)
            for subject, objects in conflicts.items():
                if len(objects) < 2:
                    continue
                cr = ConflictRecord(
                    subject=subject,
                    predicate=predicate,
                    conflicting_objects=list(objects),
                    detected_at=now_iso,
                )
                result.conflicts_found += 1

                # Apply confidence penalty to each conflicting triple
                for obj in objects:
                    before = self._get_confidence(conn, named_graph, subject, predicate, obj)
                    after = max(0.0, before * (1.0 - self._confidence_penalty))
                    cr.confidence_before[obj] = before
                    cr.confidence_after[obj] = after
                    result.triples_penalised += 1

                    if after < self._trusted_threshold:
                        cr.demoted_objects.append(obj)
                        result.triples_demoted += 1
                        if not dry_run:
                            self._demote_triple(
                                conn,
                                named_graph,
                                tentative_graph,
                                subject,
                                predicate,
                                obj,
                                after,
                            )
                    elif not dry_run:
                        self._update_confidence(
                            conn, named_graph, subject, predicate, obj, after
                        )

                result.conflict_records.append(cr)

                if not dry_run:
                    self._write_conflict_record(conn, cr)

        if not dry_run and result.conflicts_found > 0:
            logger.info(
                "contradiction_detector: %d conflicts, %d triples penalised, %d demoted",
                result.conflicts_found,
                result.triples_penalised,
                result.triples_demoted,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_conflicts(
        self, conn: Any, named_graph: str, predicate: str
    ) -> dict[str, list[str]]:
        """Return ``{subject: [obj1, obj2, ...]}`` for subjects with >1 objects."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = _TRIPLES_FOR_PREDICATE_SPARQL.format(
            graph=named_graph, predicate=predicate
        )
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "contradiction_detector: SPARQL query failed for <%s>: %s",
                predicate,
                exc,
            )
            return {}

        groups: dict[str, list[str]] = {}
        for row in rows:
            s = str(row.get("s", "")).strip()
            o = str(row.get("o", "")).strip()
            if s:
                groups.setdefault(s, [])
                if o not in groups[s]:
                    groups[s].append(o)

        return {s: objs for s, objs in groups.items() if len(objs) >= 2}

    def _get_confidence(
        self,
        conn: Any,
        named_graph: str,
        subject: str,
        predicate: str,
        obj: str,
    ) -> float:
        """Return the stored confidence for a triple, defaulting to 0.5."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = _CONFIDENCE_SPARQL.format(
            graph=named_graph,
            subject=subject,
            predicate=predicate,
            object_term=_sparql_term(obj),
            confidence_iri=_CONFIDENCE_IRI,
        )
        try:
            rows = sparql_query(conn, sparql)
            if rows:
                raw = str(rows[0].get("confidence", "0.5"))
                return float(raw.split("^^")[0].strip('"').strip("'"))
        except Exception:  # noqa: BLE001
            pass
        return 0.5

    def _update_confidence(
        self,
        conn: Any,
        named_graph: str,
        subject: str,
        predicate: str,
        obj: str,
        new_confidence: float,
    ) -> None:
        """Update the confidence annotation for a triple."""
        from sqlalchemy import text  # noqa: PLC0415

        try:
            # Remove old confidence annotation and insert the new one
            del_sparql = (
                f"DELETE {{ GRAPH <{named_graph}> {{ "
                f"<{subject}> <{_CONFIDENCE_IRI}> ?c . "
                f"}} }} WHERE {{ GRAPH <{named_graph}> {{ "
                f"<{subject}> <{_CONFIDENCE_IRI}> ?c . }} }}"
            )
            ins_sparql = (
                f'INSERT DATA {{ GRAPH <{named_graph}> {{ '
                f'<{subject}> <{_CONFIDENCE_IRI}> "{new_confidence:.4f}"^^<http://www.w3.org/2001/XMLSchema#float> . '
                f'}} }}'
            )
            conn.execute(text("SELECT sparql_update(cast(:q as text))"), {"q": del_sparql})
            conn.execute(text("SELECT sparql_update(cast(:q as text))"), {"q": ins_sparql})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "contradiction_detector: confidence update failed (%s %s): %s",
                subject,
                predicate,
                exc,
            )

    def _demote_triple(
        self,
        conn: Any,
        named_graph: str,
        tentative_graph: str,
        subject: str,
        predicate: str,
        obj: str,
        new_confidence: float,
    ) -> None:
        """Move a conflicting triple from the trusted graph to the tentative graph."""
        from sqlalchemy import text  # noqa: PLC0415

        obj_term = _sparql_term(obj)
        pred_term = f"<{predicate}>"
        try:
            # Copy to tentative graph
            copy_sparql = (
                f"INSERT {{ GRAPH <{tentative_graph}> {{ "
                f"<{subject}> {pred_term} {obj_term} . "
                f"}} }} WHERE {{ GRAPH <{named_graph}> {{ "
                f"<{subject}> {pred_term} {obj_term} . }} }}"
            )
            # Delete from trusted graph
            del_sparql = (
                f"DELETE {{ GRAPH <{named_graph}> {{ "
                f"<{subject}> {pred_term} {obj_term} . "
                f"}} }} WHERE {{ GRAPH <{named_graph}> {{ "
                f"<{subject}> {pred_term} {obj_term} . }} }}"
            )
            conn.execute(text("SELECT sparql_update(cast(:q as text))"), {"q": copy_sparql})
            conn.execute(text("SELECT sparql_update(cast(:q as text))"), {"q": del_sparql})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "contradiction_detector: demotion failed (%s %s %s): %s",
                subject,
                predicate,
                obj,
                exc,
            )

    def _write_conflict_record(self, conn: Any, cr: ConflictRecord) -> None:
        """Write a ``pgc:ConflictRecord`` to the audit log."""
        try:
            from sqlalchemy import text  # noqa: PLC0415

            conn.execute(
                text(
                    "INSERT INTO _riverbank.log (event_type, payload, occurred_at) "
                    "VALUES ('pgc:ConflictRecord', cast(:payload as jsonb), now())"
                ),
                {
                    "payload": json.dumps(
                        {
                            "subject": cr.subject,
                            "predicate": cr.predicate,
                            "conflicting_objects": cr.conflicting_objects,
                            "confidence_before": cr.confidence_before,
                            "confidence_after": cr.confidence_after,
                            "demoted_objects": cr.demoted_objects,
                            "detected_at": cr.detected_at,
                        }
                    )
                },
            )
        except Exception:  # noqa: BLE001
            pass  # audit log is best-effort
