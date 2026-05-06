"""Knowledge-prefix adapter — KNOWN GRAPH CONTEXT injection (v0.13.1).

**Problem:** When extracting triples from a new fragment the LLM has no
awareness of entities and relationships already stored in the graph.  This
leads to inconsistent IRI naming, synonym proliferation, and contradictory
triples that could have been avoided by anchoring the LLM to the existing
knowledge base.

**Approach:** At extraction time, query the local neighbourhood of entities
whose names appear in the fragment text.  Inject the resulting subgraph as a
structured ``KNOWN GRAPH CONTEXT`` block at the beginning of the extraction
prompt, capped at ``max_graph_context_tokens`` (default 200 tokens, counted
as whitespace-separated words) to prevent prompt explosion.

This feature requires the v0.12.0 token budget manager; the graph context
block is applied *before* the token budget cap so that the budget manager can
trim it correctly.

Profile YAML::

    knowledge_prefix:
      enabled: true
      max_graph_context_tokens: 200   # cap on injected context (word count proxy)
      top_entities: 10                # max number of entities to look up
      min_entity_label_length: 3      # ignore tokens shorter than this

Usage (internal — called by InstructorExtractor)::

    from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter

    adapter = KnowledgePrefixAdapter.from_profile(profile)
    context_block = adapter.build_context(conn, named_graph, fragment_text)
    if context_block:
        prompt_text = context_block + "\\n\\n" + prompt_text
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default caps
_DEFAULT_MAX_TOKENS = 200
_DEFAULT_TOP_ENTITIES = 10
_DEFAULT_MIN_LABEL_LEN = 3

# Stop words excluded when scanning fragment text for entity mentions
_STOP_WORDS = frozenset(
    "the a an in of to for with on at by from is are was were be been being "
    "have has had do does did will would could should may might can this that "
    "these those and or not but if then else so also as well its it its its".split()
)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeContextResult:
    """Output of KnowledgePrefixAdapter.build_context()."""

    context_block: str = ""          # the ``KNOWN GRAPH CONTEXT`` prompt block
    entities_found: int = 0          # number of entities retrieved from the graph
    triples_injected: int = 0        # number of triple lines in the block
    tokens_used: int = 0             # word-count proxy for tokens consumed


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class KnowledgePrefixAdapter:
    """Build a ``KNOWN GRAPH CONTEXT`` prompt prefix from the existing graph.

    Queries the pg_ripple SPARQL endpoint for entities whose labels appear in
    the fragment text, retrieves their immediate properties, and formats them
    as a concise RDF-like block that the extraction LLM can use to anchor its
    output to existing IRIs.

    Args:
        max_graph_context_tokens: Maximum word count for the injected block.
        top_entities: Maximum number of entities to retrieve.
        min_entity_label_length: Minimum length of a token to be considered
            an entity mention.
    """

    def __init__(
        self,
        max_graph_context_tokens: int = _DEFAULT_MAX_TOKENS,
        top_entities: int = _DEFAULT_TOP_ENTITIES,
        min_entity_label_length: int = _DEFAULT_MIN_LABEL_LEN,
    ) -> None:
        self._max_tokens = max_graph_context_tokens
        self._top_entities = top_entities
        self._min_label_len = min_entity_label_length

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any) -> "KnowledgePrefixAdapter":
        """Create a ``KnowledgePrefixAdapter`` from a ``CompilerProfile``.

        Returns a disabled adapter (``enabled=False``) when ``knowledge_prefix``
        is absent or disabled in the profile.
        """
        cfg: dict = getattr(profile, "knowledge_prefix", {})
        if not cfg.get("enabled", False):
            return _DisabledAdapter()  # type: ignore[return-value]
        return cls(
            max_graph_context_tokens=int(
                cfg.get("max_graph_context_tokens", _DEFAULT_MAX_TOKENS)
            ),
            top_entities=int(cfg.get("top_entities", _DEFAULT_TOP_ENTITIES)),
            min_entity_label_length=int(
                cfg.get("min_entity_label_length", _DEFAULT_MIN_LABEL_LEN)
            ),
        )

    def build_context(
        self,
        conn: Any,
        named_graph: str,
        fragment_text: str,
    ) -> KnowledgeContextResult:
        """Query the graph for entities mentioned in *fragment_text* and build
        a structured ``KNOWN GRAPH CONTEXT`` block.

        Args:
            conn: SQLAlchemy connection.
            named_graph: IRI of the trusted/asserted named graph to query.
            fragment_text: The source fragment text to scan for entity mentions.

        Returns:
            :class:`KnowledgeContextResult` — when no entities are found or
            when the graph cannot be queried, the ``context_block`` is empty.
        """
        result = KnowledgeContextResult()

        candidate_tokens = self._extract_candidate_tokens(fragment_text)
        if not candidate_tokens:
            return result

        entity_rows = self._query_entities(conn, named_graph, candidate_tokens)
        if not entity_rows:
            return result

        result.entities_found = len(entity_rows)

        # Build context lines
        lines: list[str] = ["KNOWN GRAPH CONTEXT (use these exact IRIs for matching entities):"]
        triple_count = 0
        word_count = len(lines[0].split())

        for row in entity_rows:
            iri = row.get("entity", "")
            label = row.get("label", "")
            prop = row.get("property", "")
            value = row.get("value", "")

            if not iri:
                continue

            line = f"  <{iri}>"
            if label:
                line += f'  rdfs:label  "{label}"'
            if prop and value:
                # Add one key property line
                local_prop = prop.split("/")[-1].split("#")[-1]
                line += f"  ;  {local_prop}  \"{value[:60]}\""

            line_words = len(line.split())
            if word_count + line_words > self._max_tokens:
                break

            lines.append(line)
            word_count += line_words
            triple_count += 1

        if triple_count == 0:
            return result

        result.context_block = "\n".join(lines)
        result.triples_injected = triple_count
        result.tokens_used = word_count
        logger.debug(
            "knowledge_prefix: injected %d entities (%d words) for fragment",
            triple_count,
            word_count,
        )
        return result

    def is_enabled(self) -> bool:
        """Return True — real adapter is always enabled."""
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_candidate_tokens(self, text: str) -> list[str]:
        """Extract candidate entity mention tokens from *text*.

        Strips punctuation, lowercases, filters stop words and short tokens.
        Returns the top tokens by length (longer tokens are more likely entity names).
        """
        raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]*", text)
        candidates = [
            t.lower()
            for t in raw_tokens
            if len(t) >= self._min_label_len and t.lower() not in _STOP_WORDS
        ]
        # Deduplicate preserving order
        seen: set[str] = set()
        unique = []
        for t in candidates:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        # Prefer longer tokens (more specific) — return top N
        unique.sort(key=len, reverse=True)
        return unique[: self._top_entities * 3]

    def _query_entities(
        self,
        conn: Any,
        named_graph: str,
        tokens: list[str],
    ) -> list[dict]:
        """Query the graph for entities whose labels match any of *tokens*.

        Returns a list of dicts with keys: ``entity``, ``label``, ``property``,
        ``value``.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        # Build FILTER clause for label matching
        label_filters = " || ".join(
            f'CONTAINS(LCASE(STR(?label)), "{tok}")'
            for tok in tokens[:self._top_entities]
        )
        if not label_filters:
            return []

        sparql = f"""\
SELECT DISTINCT ?entity ?label ?property ?value WHERE {{
  GRAPH <{named_graph}> {{
    ?entity <http://www.w3.org/2000/01/rdf-schema#label> ?label .
    OPTIONAL {{
      ?entity ?property ?value .
      FILTER(?property != <http://www.w3.org/2000/01/rdf-schema#label>)
      FILTER(isLiteral(?value))
    }}
    FILTER({label_filters})
  }}
}}
LIMIT {self._top_entities * 2}
"""
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.debug("knowledge_prefix: SPARQL query failed — %s", exc)
            return []

        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "entity": str(row.get("entity", "")),
                    "label": str(row.get("label", "")),
                    "property": str(row.get("property", "")),
                    "value": str(row.get("value", "")),
                }
            )
        return results


class _DisabledAdapter(KnowledgePrefixAdapter):
    """No-op adapter used when ``knowledge_prefix.enabled`` is false."""

    def is_enabled(self) -> bool:
        return False

    def build_context(
        self,
        conn: Any,
        named_graph: str,
        fragment_text: str,
    ) -> KnowledgeContextResult:
        return KnowledgeContextResult()
