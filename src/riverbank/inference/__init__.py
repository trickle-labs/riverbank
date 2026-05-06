"""SPARQL CONSTRUCT inference rules (v0.14.0).

**Problem:** Knowledge graphs often contain implied facts that are not
explicitly represented — e.g. if X isPartOf Y and Y isPartOf Z, then X
isPartOf Z.  Hand-coding these in the extraction prompt is fragile;
profile-specific rules are more maintainable.

**Approach:** Allow profiles to declare SPARQL CONSTRUCT queries.  After
ingest, each query is executed against the named graph and the resulting
triples are written to the ``<graph/inferred>`` named graph.  Inferred
triples are transparent (audit trail) and never contaminate the asserted
evidence base.

Profile YAML::

    construct_rules:
      - |
        CONSTRUCT { ?x ex:transitivePart ?z }
        WHERE {
          ?x ex:isPartOf ?y .
          ?y ex:isPartOf ?z .
        }
      - |
        CONSTRUCT { ?x rdf:type ex:SystemComponent }
        WHERE {
          ?x ex:isPartOf ex:MainSystem .
        }

CLI::

    riverbank run-construct-rules --profile docs-policy-v1 --graph <iri>
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# IRI of the graph where inferred triples are written
_INFERRED_GRAPH = "http://riverbank.example/graph/inferred"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConstructRuleResult:
    """Result of running all CONSTRUCT rules for a profile."""

    rules_executed: int = 0
    triples_inferred: int = 0
    rules_failed: int = 0
    inferred_graph: str = _INFERRED_GRAPH


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ConstructRulesEngine:
    """Execute SPARQL CONSTRUCT rules and write results to the inferred graph.

    Args:
        inferred_graph: IRI of the named graph where inferred triples are
            written (default ``http://riverbank.example/graph/inferred``).
    """

    def __init__(self, inferred_graph: str = _INFERRED_GRAPH) -> None:
        self._inferred_graph = inferred_graph

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        conn: Any,
        named_graph: str,
        rules: list[str],
        dry_run: bool = False,
    ) -> ConstructRuleResult:
        """Execute *rules* against *named_graph* and write inferred triples.

        Each rule must be a SPARQL CONSTRUCT query string.  The WHERE clause
        is evaluated against *named_graph*; inferred triples are written to
        the :attr:`inferred_graph`.

        Args:
            conn: SQLAlchemy connection.
            named_graph: IRI of the source (asserted) graph to query.
            rules: List of SPARQL CONSTRUCT query strings.
            dry_run: When ``True``, execute queries but do not write triples.

        Returns:
            :class:`ConstructRuleResult` with counts.
        """
        result = ConstructRuleResult(inferred_graph=self._inferred_graph)

        if not rules:
            return result

        for rule_idx, rule in enumerate(rules):
            rule = rule.strip()
            if not rule:
                continue
            try:
                triples = self._execute_construct(conn, named_graph, rule)
                result.rules_executed += 1

                if triples and not dry_run:
                    written = self._write_inferred(conn, triples)
                    result.triples_inferred += written
                    logger.info(
                        "construct_rules: rule %d → %d inferred triple(s)",
                        rule_idx,
                        written,
                    )
                elif triples:
                    result.triples_inferred += len(triples)
                    logger.info(
                        "construct_rules: dry-run rule %d → %d inferred triple(s)",
                        rule_idx,
                        len(triples),
                    )

            except Exception as exc:  # noqa: BLE001
                result.rules_failed += 1
                logger.warning(
                    "construct_rules: rule %d failed — %s", rule_idx, exc
                )

        logger.info(
            "construct_rules: executed=%d  inferred=%d  failed=%d  graph=<%s>",
            result.rules_executed,
            result.triples_inferred,
            result.rules_failed,
            self._inferred_graph,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _execute_construct(
        self,
        conn: Any,
        named_graph: str,
        rule: str,
    ) -> list[tuple[str, str, str]]:
        """Execute a SPARQL CONSTRUCT query and return (s, p, o) tuples.

        Wraps the query so the WHERE clause is scoped to *named_graph* if no
        explicit GRAPH pattern is present.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        # Normalise: if the query doesn't have a GRAPH clause, wrap the WHERE body
        query_upper = rule.upper()
        if "GRAPH" not in query_upper:
            rule = self._scope_to_graph(rule, named_graph)

        # Convert CONSTRUCT to SELECT for pg_ripple compatibility:
        # pg_ripple supports SPARQL SELECT; we execute SELECT and reconstruct
        select_query, template = self._construct_to_select(rule)

        try:
            rows = sparql_query(conn, select_query)
        except Exception as exc:  # noqa: BLE001
            logger.debug("construct_rules: SPARQL execute failed — %s", exc)
            raise

        return self._apply_template(rows, template)

    def _scope_to_graph(self, rule: str, named_graph: str) -> str:
        """Wrap the WHERE clause of *rule* in a GRAPH <named_graph> { } block.

        If the WHERE clause already contains a GRAPH keyword, the rule is
        returned unchanged (no double-wrapping).
        """
        upper = rule.upper()
        where_pos = upper.find("WHERE")
        if where_pos == -1:
            return rule
        # If the WHERE body already references a GRAPH, don't re-scope
        where_body = rule[where_pos:]
        if "GRAPH" in where_body.upper():
            return rule
        # Find the opening brace after WHERE
        brace_start = rule.find("{", where_pos)
        if brace_start == -1:
            return rule
        # Find the matching closing brace
        depth = 0
        brace_end = -1
        for i in range(brace_start, len(rule)):
            if rule[i] == "{":
                depth += 1
            elif rule[i] == "}":
                depth -= 1
            if depth == 0:
                brace_end = i
                break
        if brace_end == -1:
            return rule
        inner = rule[brace_start + 1 : brace_end]
        return (
            rule[:brace_start + 1]
            + f" GRAPH <{named_graph}> {{{inner}}}"
            + rule[brace_end:]
        )

    def _construct_to_select(self, rule: str) -> tuple[str, list[str]]:
        """Convert a SPARQL CONSTRUCT query to a SELECT query.

        Returns (select_query, template_variables) where template_variables is
        a list of ``["?s", "?p", "?o"]`` or explicit variable names from the
        CONSTRUCT template.
        """
        upper = rule.upper()
        construct_pos = upper.find("CONSTRUCT")
        where_pos = upper.find("WHERE")

        if construct_pos == -1 or where_pos == -1:
            raise ValueError("Not a valid SPARQL CONSTRUCT query")

        # Extract the template between CONSTRUCT { ... }
        template_start = rule.find("{", construct_pos)
        template_end = rule.find("}", template_start) if template_start != -1 else -1

        if template_start == -1 or template_end == -1:
            raise ValueError("Could not parse CONSTRUCT template")

        template_body = rule[template_start + 1 : template_end].strip()
        where_body = rule[where_pos:]

        # Parse simple triple patterns from the template: ?s ?p ?o or <iri> ?p ?o
        template_triples: list[tuple[str, str, str]] = []
        for triple_text in template_body.split("."):
            parts = triple_text.strip().split()
            if len(parts) >= 3:
                template_triples.append((parts[0], parts[1], parts[2]))

        if not template_triples:
            raise ValueError("No triple patterns in CONSTRUCT template")

        # Collect all variables (starting with ?) from template
        all_vars: list[str] = []
        seen_vars: set[str] = set()
        for s, p, o in template_triples:
            for term in (s, p, o):
                if term.startswith("?") and term not in seen_vars:
                    all_vars.append(term)
                    seen_vars.add(term)

        var_list = " ".join(all_vars) if all_vars else "*"
        select_query = f"SELECT {var_list} {where_body}"

        return select_query, [t for triple in template_triples for t in triple]

    def _apply_template(
        self,
        rows: list[dict],
        template: list[str],
    ) -> list[tuple[str, str, str]]:
        """Instantiate template patterns with variable bindings from *rows*."""
        if not rows or not template:
            return []

        # Rebuild template triples list
        if len(template) % 3 != 0:
            return []

        template_triples: list[tuple[str, str, str]] = [
            (template[i], template[i + 1], template[i + 2])
            for i in range(0, len(template), 3)
        ]

        results: list[tuple[str, str, str]] = []
        for row in rows:
            for s_tmpl, p_tmpl, o_tmpl in template_triples:
                s = row.get(s_tmpl.lstrip("?"), s_tmpl) if s_tmpl.startswith("?") else s_tmpl
                p = row.get(p_tmpl.lstrip("?"), p_tmpl) if p_tmpl.startswith("?") else p_tmpl
                o = row.get(o_tmpl.lstrip("?"), o_tmpl) if o_tmpl.startswith("?") else o_tmpl
                if s and p and o:
                    results.append((str(s), str(p), str(o)))

        return results

    def _write_inferred(
        self,
        conn: Any,
        triples: list[tuple[str, str, str]],
    ) -> int:
        """Write inferred triples to the inferred graph.

        Uses INSERT DATA SPARQL via the pg_ripple catalog layer.
        Returns the number of triples successfully written.
        """
        from riverbank.postprocessors.dedup import _SameAsTriple  # noqa: PLC0415
        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415

        triple_objs = []
        for s, p, o in triples:
            triple_objs.append(
                _SameAsTriple(
                    subject=s,
                    predicate=p,
                    object_value=o,
                    confidence=1.0,  # inferred triples are treated as certain
                )
            )

        try:
            written = load_triples_with_confidence(conn, triple_objs, self._inferred_graph)
            conn.commit()
            return written
        except Exception as exc:  # noqa: BLE001
            logger.warning("construct_rules: could not write inferred triples — %s", exc)
            return 0
