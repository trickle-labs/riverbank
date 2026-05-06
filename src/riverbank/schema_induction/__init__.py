"""Schema induction — cold-start OWL ontology proposal from graph statistics (v0.13.0).

**Problem:** New users must write an ontology before they can get quality
extraction results.  Most lack ontology expertise, so they skip the step,
leading to unconstrained extraction and poor precision.

**Approach:**

1. After an initial unconstrained extraction pass, collect all unique
   predicates and entity types from the graph.
2. Compute frequency statistics (how often each predicate and type appears).
3. Send the statistics to an LLM with a prompt requesting a minimal OWL
   ontology: class hierarchy, domain/range declarations, and cardinality
   constraints.
4. The LLM response is parsed and presented to the user for review.
5. On confirmation, write the induced ontology to ``ontology/induced.ttl`` and
   update the profile YAML with ``allowed_predicates`` and ``allowed_classes``.

A second extraction pass with the induced ontology as constraints produces
significantly better precision because the LLM is guided to use canonical
IRIs and the ontology filter rejects off-ontology triples.

CLI::

    riverbank induce-schema \\
        --graph http://riverbank.example/graph/trusted \\
        --output ontology/induced.ttl \\
        [--profile docs-policy-v1]

Usage::

    from riverbank.schema_induction import SchemaInducer

    inducer = SchemaInducer(settings)
    proposal = inducer.propose(conn, named_graph)
    print(proposal.ttl_text)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# SPARQL — unique predicates with frequency
_PREDICATES_SPARQL = """\
SELECT ?p (COUNT(*) AS ?freq) WHERE {{
  GRAPH <{graph}> {{ ?s ?p ?o . }}
  FILTER(!isLiteral(?p))
}} GROUP BY ?p ORDER BY DESC(?freq) LIMIT {limit}
"""

# SPARQL — unique entity types with frequency
_TYPES_SPARQL = """\
SELECT ?type (COUNT(*) AS ?freq) WHERE {{
  GRAPH <{graph}> {{
    ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?type .
  }}
}} GROUP BY ?type ORDER BY DESC(?freq) LIMIT {limit}
"""

# LLM system prompt for schema induction
_SYSTEM_PROMPT = """\
You are an ontology engineer.  Given predicate and entity type usage statistics
from a knowledge graph, propose a minimal OWL ontology in Turtle syntax.

Requirements:
- Use the prefix `ex: <http://riverbank.example/entity/>` for application IRIs.
- Declare owl:Class for the top-5 most frequent entity types.
- Declare owl:ObjectProperty or owl:DatatypeProperty for the top-20 most
  frequent predicates.
- Add rdfs:domain and rdfs:range declarations where the statistics support them.
- Add owl:FunctionalProperty for predicates that logically take a single value.
- Add rdfs:subClassOf for obvious class hierarchies.
- Keep the ontology minimal — do NOT invent classes or predicates not
  supported by the statistics.

Return ONLY valid Turtle syntax, starting with @prefix declarations.
No prose, no markdown fences.
"""

# Default base prefix
_DEFAULT_PREFIX = "ex: <http://riverbank.example/entity/>"


@dataclass
class GraphStatistics:
    """Predicate and entity type statistics from the knowledge graph."""

    predicates: list[tuple[str, int]]    # (predicate_iri, frequency) sorted desc
    types: list[tuple[str, int]]         # (type_iri, frequency) sorted desc
    named_graph: str = ""


@dataclass
class SchemaProposal:
    """The LLM-proposed OWL ontology plus associated metadata."""

    ttl_text: str                                  # Turtle-formatted ontology
    predicates_addressed: list[str] = field(default_factory=list)
    types_addressed: list[str] = field(default_factory=list)
    allowed_predicates: list[str] = field(default_factory=list)
    allowed_classes: list[str] = field(default_factory=list)
    predicate_constraints: dict = field(default_factory=dict)
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SchemaInducer:
    """Collect graph statistics and propose an OWL ontology via an LLM.

    Args:
        settings: Application settings (provides model configuration).
        model_name: Override the model for schema induction.  If not given,
            uses ``settings.model_name`` if available, else ``"llama3.2"``.
        top_predicates: Maximum number of predicates to include in the prompt.
        top_types: Maximum number of entity types to include in the prompt.
    """

    def __init__(
        self,
        settings: Any = None,
        model_name: str | None = None,
        top_predicates: int = 20,
        top_types: int = 10,
    ) -> None:
        self._settings = settings
        self._model_name = model_name or (
            getattr(settings, "model_name", None) or "llama3.2"
        )
        self._top_predicates = top_predicates
        self._top_types = top_types

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_statistics(
        self,
        conn: Any,
        named_graph: str,
        limit: int = 50,
    ) -> GraphStatistics:
        """Query the graph and return frequency statistics.

        Returns an empty :class:`GraphStatistics` when pg_ripple is unavailable.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        stats = GraphStatistics(predicates=[], types=[], named_graph=named_graph)

        # Predicates
        sparql_p = _PREDICATES_SPARQL.format(graph=named_graph, limit=limit)
        try:
            rows = sparql_query(conn, sparql_p)
            for row in rows:
                p = str(row.get("p", "")).strip()
                freq_raw = row.get("freq", 1)
                try:
                    freq = int(float(str(freq_raw)))
                except (ValueError, TypeError):
                    freq = 1
                if p:
                    stats.predicates.append((p, freq))
        except Exception as exc:  # noqa: BLE001
            logger.warning("schema_inducer: predicate query failed — %s", exc)

        # Types
        sparql_t = _TYPES_SPARQL.format(graph=named_graph, limit=limit)
        try:
            rows = sparql_query(conn, sparql_t)
            for row in rows:
                t = str(row.get("type", "")).strip()
                freq_raw = row.get("freq", 1)
                try:
                    freq = int(float(str(freq_raw)))
                except (ValueError, TypeError):
                    freq = 1
                if t:
                    stats.types.append((t, freq))
        except Exception as exc:  # noqa: BLE001
            logger.warning("schema_inducer: type query failed — %s", exc)

        return stats

    def propose(
        self,
        stats: GraphStatistics,
    ) -> SchemaProposal:
        """Ask the LLM to propose an OWL ontology from *stats*.

        Falls back to a stub proposal when no LLM is available.
        """
        if not stats.predicates and not stats.types:
            return SchemaProposal(
                ttl_text=_stub_ttl(),
                model_used="stub",
            )

        # Build user message
        user_msg = self._build_prompt(stats)

        # Call LLM
        try:
            ttl_text, prompt_tokens, completion_tokens = self._call_llm(user_msg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("schema_inducer: LLM call failed — %s", exc)
            ttl_text = _stub_ttl()
            prompt_tokens = 0
            completion_tokens = 0

        # Derive allowed_predicates / allowed_classes from the statistics
        allowed_predicates = [p for p, _ in stats.predicates[: self._top_predicates]]
        allowed_classes = [t for t, _ in stats.types[: self._top_types]]

        # Derive predicate_constraints: mark high-frequency predicates that
        # appear to be functional (heuristic: appears with at most 1 distinct object
        # per subject in the stats)
        predicate_constraints: dict = {}
        for p, _ in stats.predicates[:20]:
            # Heuristic: single-valued predicates often have "name", "title",
            # "version", "id" in their local name
            local = p.split("/")[-1].split("#")[-1].split(":")[-1].lower()
            if any(kw in local for kw in ("name", "title", "version", "id", "date", "label")):
                predicate_constraints[p] = {"max_cardinality": 1}

        return SchemaProposal(
            ttl_text=ttl_text,
            predicates_addressed=[p for p, _ in stats.predicates[: self._top_predicates]],
            types_addressed=[t for t, _ in stats.types[: self._top_types]],
            allowed_predicates=allowed_predicates,
            allowed_classes=allowed_classes,
            predicate_constraints=predicate_constraints,
            model_used=self._model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, stats: GraphStatistics) -> str:
        """Build the user message summarising graph statistics."""
        lines: list[str] = [
            f"Named graph: <{stats.named_graph}>",
            "",
            f"TOP PREDICATES (showing top {min(self._top_predicates, len(stats.predicates))}):",
        ]
        for pred, freq in stats.predicates[: self._top_predicates]:
            label = pred.split("/")[-1].split("#")[-1]
            lines.append(f"  {pred}  ({freq} occurrences)  [{label}]")

        lines.append("")
        lines.append(f"TOP ENTITY TYPES (showing top {min(self._top_types, len(stats.types))}):")
        for typ, freq in stats.types[: self._top_types]:
            label = typ.split("/")[-1].split("#")[-1]
            lines.append(f"  {typ}  ({freq} occurrences)  [{label}]")

        lines.append("")
        lines.append("Propose a minimal OWL ontology in Turtle syntax.")
        return "\n".join(lines)

    def _call_llm(self, user_message: str) -> tuple[str, int, int]:
        """Call the configured LLM and return (ttl_text, prompt_tokens, completion_tokens)."""
        try:
            import openai  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("openai package not installed") from None

        base_url: str | None = None
        api_key: str = "ollama"
        if self._settings is not None:
            base_url = getattr(self._settings, "base_url", None) or getattr(
                getattr(self._settings, "llm", None), "base_url", None
            )
            api_key = getattr(self._settings, "api_key", "ollama") or "ollama"

        client = openai.OpenAI(
            base_url=base_url or "http://localhost:11434/v1",
            api_key=api_key,
        )

        response = client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
        )

        ttl_text: str = response.choices[0].message.content or ""
        # Strip markdown fences if the LLM wrapped the output
        ttl_text = ttl_text.strip()
        if ttl_text.startswith("```"):
            ttl_text = "\n".join(ttl_text.split("\n")[1:])
        if ttl_text.endswith("```"):
            ttl_text = "\n".join(ttl_text.split("\n")[:-1])

        prompt_tokens = getattr(
            getattr(response, "usage", None), "prompt_tokens", 0
        ) or 0
        completion_tokens = getattr(
            getattr(response, "usage", None), "completion_tokens", 0
        ) or 0

        return ttl_text, prompt_tokens, completion_tokens


def _stub_ttl() -> str:
    """Return a stub Turtle ontology when no LLM is available."""
    return """\
@prefix ex: <http://riverbank.example/entity/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# Induced ontology stub — run riverbank induce-schema with a populated graph
# to get a real ontology proposal.

<http://riverbank.example/ontology/induced> a owl:Ontology ;
    rdfs:label "Induced ontology (stub)" .
"""
