"""SHACL shape validation for named graphs (v0.14.0).

**Problem:** Triples written to the named graph may violate the pgc: ontology
constraints — missing mandatory properties, wrong datatypes, or cardinality
violations.  Detecting these violations post-hoc is costly; an automated
validation pass surfaces them as structured diagnostics.

**Approach:** After ingest, load the named graph as an rdflib Graph, run
pyshacl against a shapes file (default: ``ontology/pgc-shapes.ttl``), and
return a structured ``ShapeValidationReport`` with each violation as a
``ShapeViolation``.  Optionally reduce the confidence of violating triples.

The validator degrades gracefully when pyshacl or rdflib is not installed —
it logs a warning and returns an empty report rather than crashing.

Profile YAML::

    shacl_validation:
      enabled: true
      shapes_path: ontology/pgc-shapes.ttl   # path to shapes graph
      reduce_confidence: true                 # reduce conf of violating triples
      confidence_penalty: 0.15               # subtract this from violating triples

CLI::

    riverbank validate-shapes --profile docs-policy-v1 --graph <iri>
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default shapes file bundled with the package
_DEFAULT_SHAPES_PATH = Path(__file__).parent.parent.parent.parent / "ontology" / "pgc-shapes.ttl"

# IRI of the inferred/validated triples graph
_INFERRED_GRAPH = "http://riverbank.example/graph/inferred"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ShapeViolation:
    """A single SHACL constraint violation."""

    focus_node: str        # IRI of the violating node
    result_path: str       # predicate path that caused the violation (may be empty)
    message: str           # human-readable violation message
    severity: str          # sh:Violation | sh:Warning | sh:Info
    source_shape: str      # IRI of the sh:NodeShape or sh:PropertyShape


@dataclass
class ShapeValidationReport:
    """Result of a SHACL validation pass."""

    conforms: bool = True
    violations: list[ShapeViolation] = field(default_factory=list)
    warnings: int = 0
    triples_penalised: int = 0
    shapes_path: str = ""
    graph_iri: str = ""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ShaclValidator:
    """Validate a named graph against SHACL shapes.

    Args:
        shapes_path: Path to the shapes graph Turtle file.  Defaults to the
            bundled ``ontology/pgc-shapes.ttl``.
        reduce_confidence: When ``True``, reduce the confidence of triples whose
            subject nodes appear in violation reports.
        confidence_penalty: Amount to subtract from the confidence of violating
            triples (clamped to [0, 1]).
    """

    def __init__(
        self,
        shapes_path: str | Path | None = None,
        reduce_confidence: bool = False,
        confidence_penalty: float = 0.15,
    ) -> None:
        self._shapes_path = Path(shapes_path) if shapes_path else _DEFAULT_SHAPES_PATH
        self._reduce_confidence = reduce_confidence
        self._confidence_penalty = confidence_penalty

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any) -> "ShaclValidator":
        """Create a ``ShaclValidator`` from a ``CompilerProfile``."""
        cfg: dict = getattr(profile, "shacl_validation", {})
        shapes_path = cfg.get("shapes_path", None)
        return cls(
            shapes_path=shapes_path,
            reduce_confidence=cfg.get("reduce_confidence", False),
            confidence_penalty=float(cfg.get("confidence_penalty", 0.15)),
        )

    def validate(
        self,
        conn: Any,
        named_graph: str,
        dry_run: bool = False,
    ) -> ShapeValidationReport:
        """Validate *named_graph* against the shapes graph.

        Fetches all triples from the named graph, constructs an in-memory rdflib
        Graph, runs pyshacl validation, and returns a structured report.

        Args:
            conn: SQLAlchemy connection (used to fetch triples from pg_ripple).
            named_graph: IRI of the named graph to validate.
            dry_run: When ``True``, compute violations but do not write any
                confidence updates to the graph.

        Returns:
            :class:`ShapeValidationReport` — empty report if pyshacl/rdflib are
            not installed or if the shapes file does not exist.
        """
        report = ShapeValidationReport(
            graph_iri=named_graph,
            shapes_path=str(self._shapes_path),
        )

        if not self._shapes_path.exists():
            logger.warning(
                "shacl_validator: shapes file not found at %s — skipping validation",
                self._shapes_path,
            )
            return report

        try:
            import rdflib  # noqa: PLC0415
            import pyshacl  # noqa: PLC0415
        except ImportError as exc:
            logger.warning(
                "shacl_validator: pyshacl/rdflib not installed — skipping. "
                "Install with: pip install 'riverbank[reasoning]'  (%s)",
                exc,
            )
            return report

        # Build in-memory data graph from the named graph
        data_graph = self._fetch_graph(conn, named_graph, rdflib)
        if data_graph is None:
            return report

        # Load shapes graph
        try:
            shapes_graph = rdflib.Graph()
            shapes_graph.parse(str(self._shapes_path), format="turtle")
        except Exception as exc:  # noqa: BLE001
            logger.warning("shacl_validator: could not parse shapes file — %s", exc)
            return report

        # Run SHACL validation
        try:
            conforms, results_graph, results_text = pyshacl.validate(
                data_graph,
                shacl_graph=shapes_graph,
                inference="none",
                abort_on_first=False,
                meta_shacl=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("shacl_validator: pyshacl validation failed — %s", exc)
            return report

        report.conforms = bool(conforms)

        if not conforms:
            violations = self._parse_violations(results_graph, rdflib)
            report.violations = violations
            report.warnings = sum(
                1 for v in violations if v.severity != "sh:Violation"
            )

            logger.info(
                "shacl_validator: %d violation(s) found in <%s>",
                len(violations),
                named_graph,
            )

            # Optionally reduce confidence of nodes with violations
            if self._reduce_confidence and not dry_run and violations:
                penalised = self._penalise_violations(conn, violations, named_graph)
                report.triples_penalised = penalised

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_graph(
        self,
        conn: Any,
        named_graph: str,
        rdflib: Any,
    ) -> Any | None:
        """Fetch all triples from *named_graph* and build an rdflib Graph."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = f"""\
SELECT ?s ?p ?o WHERE {{
  GRAPH <{named_graph}> {{
    ?s ?p ?o .
  }}
}}
LIMIT 10000
"""
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning("shacl_validator: could not fetch triples — %s", exc)
            return None

        g = rdflib.Graph()
        for row in rows:
            s_raw = str(row.get("s", ""))
            p_raw = str(row.get("p", ""))
            o_raw = str(row.get("o", ""))
            if not (s_raw and p_raw and o_raw):
                continue
            try:
                s = rdflib.URIRef(s_raw) if s_raw.startswith("http") else rdflib.BNode(s_raw)
                p = rdflib.URIRef(p_raw)
                # Try to distinguish literals from URIs
                if o_raw.startswith("http") or o_raw.startswith("_:"):
                    o: Any = rdflib.URIRef(o_raw)
                else:
                    # Try to detect datatype annotations e.g. "1.0"^^xsd:decimal
                    if "^^" in o_raw:
                        val, dtype = o_raw.rsplit("^^", 1)
                        val = val.strip('"')
                        o = rdflib.Literal(val, datatype=rdflib.URIRef(dtype))
                    elif o_raw.startswith('"') or not o_raw.startswith("<"):
                        o = rdflib.Literal(o_raw.strip('"'))
                    else:
                        o = rdflib.URIRef(o_raw.strip("<>"))
                g.add((s, p, o))
            except Exception:  # noqa: BLE001
                continue

        logger.debug("shacl_validator: loaded %d triples from <%s>", len(g), named_graph)
        return g

    def _parse_violations(self, results_graph: Any, rdflib: Any) -> list[ShapeViolation]:
        """Parse pyshacl results graph into :class:`ShapeViolation` instances."""
        SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
        violations: list[ShapeViolation] = []

        for result in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
            focus = str(results_graph.value(result, SH.focusNode) or "")
            path = str(results_graph.value(result, SH.resultPath) or "")
            msg_node = results_graph.value(result, SH.resultMessage)
            msg = str(msg_node) if msg_node else ""
            severity_node = results_graph.value(result, SH.resultSeverity)
            severity = str(severity_node).split("#")[-1] if severity_node else "Violation"
            shape_node = results_graph.value(result, SH.sourceShape)
            shape = str(shape_node) if shape_node else ""

            violations.append(
                ShapeViolation(
                    focus_node=focus,
                    result_path=path,
                    message=msg,
                    severity=f"sh:{severity}",
                    source_shape=shape,
                )
            )
        return violations

    def _penalise_violations(
        self,
        conn: Any,
        violations: list[ShapeViolation],
        named_graph: str,
    ) -> int:
        """Reduce confidence of triples whose subject nodes have violations.

        Returns the number of triples updated.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        penalised = 0
        focus_iris = {v.focus_node for v in violations if v.focus_node.startswith("http")}

        for focus_iri in focus_iris:
            # Fetch current confidence
            sparql = f"""\
SELECT ?s ?p ?o ?confidence WHERE {{
  GRAPH <{named_graph}> {{
    <{focus_iri}> ?p ?o .
    BIND(<{focus_iri}> AS ?s)
    <{focus_iri}> <http://riverbank.example/pgc/confidence> ?confidence .
  }}
}}
"""
            try:
                rows = sparql_query(conn, sparql)
                for row in rows:
                    conf = float(row.get("confidence", 0.5))
                    new_conf = max(0.0, conf - self._confidence_penalty)
                    if new_conf != conf:
                        # Write reduced confidence
                        from riverbank.postprocessors.dedup import _SameAsTriple  # noqa: PLC0415
                        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415
                        updated = _SameAsTriple(
                            subject=str(row.get("s", "")),
                            predicate=str(row.get("p", "")),
                            object_value=str(row.get("o", "")),
                            confidence=new_conf,
                        )
                        load_triples_with_confidence(conn, [updated], named_graph)
                        penalised += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "shacl_validator: could not penalise violations for <%s> — %s",
                    focus_iri,
                    exc,
                )
        return penalised
