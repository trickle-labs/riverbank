"""OWL 2 RL forward-chaining via owlrl (v0.14.0).

**Problem:** Many facts implied by OWL axioms are not explicitly asserted —
e.g. if A rdfs:subClassOf B and X rdf:type A, then X rdf:type B is implied.
Without deductive closure, SPARQL queries that search for instances of B miss
those instances.

**Approach:** After ingest, load the named graph into an rdflib Graph, apply
owlrl's OWL 2 RL forward-chaining rules (``owl:inverseOf``,
``rdfs:subClassOf`` transitivity, domain/range type assertions,
``owl:TransitiveProperty``), then write newly derived triples to the
``<graph/inferred>`` named graph.  The asserted evidence base is never
contaminated — inferred triples exist only in ``<graph/inferred>``.

The engine degrades gracefully when owlrl or rdflib is not installed — it logs
a warning and returns an empty result rather than crashing.

Profile YAML::

    owl_rl:
      enabled: true
      max_triples: 5000   # cap on inferred triples (0 = unlimited)

CLI::

    riverbank run-owl-rl --profile docs-policy-v1 --graph <iri>
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# IRI of the graph where inferred triples are written
_INFERRED_GRAPH = "http://riverbank.example/graph/inferred"

# Default max inferred triples per run (safety cap)
_DEFAULT_MAX_TRIPLES = 5000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OwlRlResult:
    """Result of an OWL 2 RL forward-chaining run."""

    triples_before: int = 0
    triples_after: int = 0
    triples_inferred: int = 0
    triples_written: int = 0
    triples_capped: int = 0
    inferred_graph: str = _INFERRED_GRAPH


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class OwlRlEngine:
    """Apply OWL 2 RL forward-chaining rules to a named graph.

    Uses owlrl for lightweight deductive closure.  Derives only the rules
    supported by OWL 2 RL: ``owl:inverseOf``, ``rdfs:subClassOf``
    transitivity, domain/range type assertions, and
    ``owl:TransitiveProperty`` closures.

    Args:
        inferred_graph: IRI where inferred triples are written.
        max_triples: Maximum number of inferred triples to write (0 = unlimited).
    """

    def __init__(
        self,
        inferred_graph: str = _INFERRED_GRAPH,
        max_triples: int = _DEFAULT_MAX_TRIPLES,
    ) -> None:
        self._inferred_graph = inferred_graph
        self._max_triples = max_triples

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any) -> "OwlRlEngine":
        """Create an ``OwlRlEngine`` from a ``CompilerProfile``."""
        cfg: dict = getattr(profile, "owl_rl", {})
        return cls(
            max_triples=int(cfg.get("max_triples", _DEFAULT_MAX_TRIPLES)),
        )

    def is_enabled(self, profile: Any) -> bool:
        """Return True when ``owl_rl.enabled: true`` in the profile."""
        cfg: dict = getattr(profile, "owl_rl", {})
        return bool(cfg.get("enabled", False))

    def run(
        self,
        conn: Any,
        named_graph: str,
        dry_run: bool = False,
    ) -> OwlRlResult:
        """Apply OWL 2 RL rules and write inferred triples to *inferred_graph*.

        Args:
            conn: SQLAlchemy connection.
            named_graph: IRI of the named graph to reason over.
            dry_run: Compute the closure but do not write to the graph.

        Returns:
            :class:`OwlRlResult` with counts.
        """
        result = OwlRlResult(inferred_graph=self._inferred_graph)

        try:
            import rdflib  # noqa: PLC0415
            import owlrl   # noqa: PLC0415
        except ImportError as exc:
            logger.warning(
                "owl_rl: owlrl/rdflib not installed — skipping. "
                "Install with: pip install 'riverbank[reasoning]'  (%s)",
                exc,
            )
            return result

        # Fetch asserted triples
        g = self._fetch_graph(conn, named_graph, rdflib)
        if g is None:
            return result

        result.triples_before = len(g)

        # Apply OWL 2 RL forward-chaining
        try:
            owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
        except Exception as exc:  # noqa: BLE001
            logger.warning("owl_rl: deductive closure failed — %s", exc)
            return result

        result.triples_after = len(g)
        result.triples_inferred = result.triples_after - result.triples_before

        if result.triples_inferred <= 0:
            logger.info("owl_rl: no new triples inferred from <%s>", named_graph)
            return result

        logger.info(
            "owl_rl: inferred %d new triple(s) from <%s>",
            result.triples_inferred,
            named_graph,
        )

        if not dry_run:
            # Extract only the *new* triples (those not in the original fetch)
            original_triples = set(self._fetch_triple_keys(conn, named_graph))
            new_triples: list[tuple[str, str, str]] = []

            for s, p, o in g:
                key = (str(s), str(p), str(o))
                if key not in original_triples:
                    new_triples.append(key)

            # Apply safety cap
            if self._max_triples > 0 and len(new_triples) > self._max_triples:
                result.triples_capped = len(new_triples) - self._max_triples
                new_triples = new_triples[: self._max_triples]
                logger.warning(
                    "owl_rl: capped inferred triples at %d (skipped %d)",
                    self._max_triples,
                    result.triples_capped,
                )

            written = self._write_inferred(conn, new_triples)
            result.triples_written = written

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_graph(
        self,
        conn: Any,
        named_graph: str,
        rdflib: Any,
    ) -> Any | None:
        """Fetch triples from *named_graph* and load into an rdflib Graph."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = f"""\
SELECT ?s ?p ?o WHERE {{
  GRAPH <{named_graph}> {{
    ?s ?p ?o .
    FILTER(isIRI(?s) && isIRI(?p))
  }}
}}
LIMIT 20000
"""
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning("owl_rl: could not fetch graph triples — %s", exc)
            return None

        g = rdflib.Graph()
        for row in rows:
            s_raw = str(row.get("s", ""))
            p_raw = str(row.get("p", ""))
            o_raw = str(row.get("o", ""))
            if not (s_raw and p_raw and o_raw):
                continue
            try:
                s = rdflib.URIRef(s_raw)
                p = rdflib.URIRef(p_raw)
                o = rdflib.URIRef(o_raw) if o_raw.startswith("http") else rdflib.Literal(o_raw)
                g.add((s, p, o))
            except Exception:  # noqa: BLE001
                continue

        logger.debug("owl_rl: loaded %d triples for reasoning", len(g))
        return g

    def _fetch_triple_keys(
        self,
        conn: Any,
        named_graph: str,
    ) -> set[tuple[str, str, str]]:
        """Return a set of (s, p, o) string tuples already in *named_graph*."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = f"""\
SELECT ?s ?p ?o WHERE {{
  GRAPH <{named_graph}> {{
    ?s ?p ?o .
  }}
}}
LIMIT 20000
"""
        try:
            rows = sparql_query(conn, sparql)
            return {(str(r.get("s", "")), str(r.get("p", "")), str(r.get("o", ""))) for r in rows}
        except Exception:  # noqa: BLE001
            return set()

    def _write_inferred(
        self,
        conn: Any,
        triples: list[tuple[str, str, str]],
    ) -> int:
        """Write inferred (s, p, o) triples to the inferred graph."""
        from riverbank.postprocessors.dedup import _SameAsTriple  # noqa: PLC0415
        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415

        triple_objs = [
            _SameAsTriple(subject=s, predicate=p, object_value=o, confidence=1.0)
            for s, p, o in triples
        ]
        try:
            written = load_triples_with_confidence(conn, triple_objs, self._inferred_graph)
            conn.commit()
            return written
        except Exception as exc:  # noqa: BLE001
            logger.warning("owl_rl: could not write inferred triples — %s", exc)
            return 0
