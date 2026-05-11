"""Vocabulary normalisation pass for riverbank (v0.15.3).

Post-extraction pass that converts the ad-hoc predicate/object vocabulary
produced by open-vocabulary extraction into a tighter, semantically consistent
schema.  The pass is fully **domain-agnostic** — it operates on the triple
buffer and has no knowledge of the subject domain.

Four normalisations are applied in order:

1. **Categorical literal promotion** — repeated string-valued objects that
   represent a bounded category (``"Director"``, ``"Approved"``, ``"Mammal"``)
   are promoted to ``vocab:*`` IRI resources.

2. **Predicate vocabulary collapse** — clusters of predicates with a shared
   semantic root (``ex:is_director`` / ``ex:is_ceo`` / ``ex:is_chair``) are
   collapsed to a single canonical predicate using either an edit-distance
   (deterministic) or LLM-guided backend.

3. **Fact-stuffed predicate decomposition** — predicates whose local name
   embeds a qualifier (year, date, ordinal) are decomposed into a base
   predicate triple plus a separate qualifier triple.

4. **Entity URI canonicalisation** — after entity resolution writes
   ``owl:sameAs`` links, non-canonical subject URIs are rewritten to the
   single canonical URI chosen by the resolution pass.

Pipeline position::

    extract → entity_resolution → [vocabulary_normalisation] → write

The pass reads from the in-memory triple buffer — no database round-trip
is needed.

Profile YAML::

    vocabulary_normalisation:
      enabled: true
      categorical_threshold: 2
      collapse_predicates: true
      predicate_collapse_backend: "deterministic"   # deterministic | llm
      decompose_stuffed_predicates: true
      rewrite_canonical_uris: false
      vocabulary_namespace: "http://riverbank.example/vocab/"

Stats emitted::

    vocab_literals_promoted      int  Literals replaced by vocab:* IRIs
    vocab_predicates_collapsed   int  Predicate rewrites from cluster collapse
    vocab_facts_decomposed       int  Predicates whose qualifiers were stripped
    vocab_uris_rewritten         int  Subject/object URI rewrites
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

__all__ = [
    "NormalisationConfig",
    "NormalisationResult",
    "CategoricalDetector",
    "PredicateCollapser",
    "FactDecomposer",
    "URICanonicaliser",
    "VocabularyNormalisationPass",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class NormalisationConfig:
    """Configuration for the vocabulary normalisation pass."""

    enabled: bool = True
    categorical_threshold: int = 2
    collapse_predicates: bool = True
    predicate_collapse_backend: str = "deterministic"  # deterministic | llm
    decompose_stuffed_predicates: bool = True
    rewrite_canonical_uris: bool = False
    vocabulary_namespace: str = "http://riverbank.example/vocab/"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class NormalisationResult:
    """Result returned by :meth:`VocabularyNormalisationPass.run`."""

    triples: list
    vocab_literals_promoted: int = 0
    vocab_predicates_collapsed: int = 0
    vocab_facts_decomposed: int = 0
    vocab_uris_rewritten: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Matches values that are IRIs rather than plain string literals.
# Covers:  http://...  https://...  <...>  prefix:local  (but NOT bare words)
_IRI_PATTERN = re.compile(
    r"^(?:https?://|<|[a-zA-Z_][a-zA-Z0-9_+\-.]*:[a-zA-Z_/<])"
)

# Matches bare unicode escapes that should have been real Unicode characters.
# Pattern: u followed by exactly 4 hex digits, e.g. "u2013" for U+2013 (en-dash).
# This happens when Python string repr leaks into a literal instead of the char.
_UNICODE_ESCAPE_RE = re.compile(r"u([0-9a-fA-F]{4})")


def _is_iri(value: str) -> bool:
    """Return ``True`` if *value* looks like an IRI rather than a plain literal."""
    return bool(_IRI_PATTERN.match(value.strip()))


def _normalize_literal_unicode(value: str) -> str:
    """Decode bare unicode escape sequences in a string literal.

    Converts ``u2013`` → ``–`` (en-dash), ``u2014`` → ``—`` (em-dash), etc.
    Only applied to non-IRI object values.

    Example::

        "1972u201373"  →  "1972–73"
    """
    return _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), value)


def _to_camel_case(s: str) -> str:
    """Convert a string to CamelCase for use as an IRI local name.

    Examples::

        "Director"           → "Director"
        "Chief Executive Officer" → "ChiefExecutiveOfficer"
        "head_coach"         → "HeadCoach"
    """
    parts = re.split(r"[\s_\-/]+", s.strip())
    return "".join(p.capitalize() for p in parts if p)


def _local_name(predicate: str) -> str:
    """Extract the local name from a predicate IRI or CURIE.

    Examples::

        "http://example.org/vocab#holds_role"  → "holds_role"
        "ex:is_director"                       → "is_director"
        "holds_role"                           → "holds_role"
    """
    s = predicate.strip("<>").rstrip("/")
    for sep in ("#", "/", ":"):
        if sep in s:
            return s.rsplit(sep, 1)[-1]
    return s


def _predicate_namespace(predicate: str) -> str:
    """Extract the namespace prefix of a predicate (everything before the local name).

    Examples::

        "ex:is_director" → "ex:"
        "http://example.org/vocab/holds_role" → "http://example.org/vocab/"
    """
    s = predicate.strip("<>").rstrip("/")
    for sep in ("#", "/", ":"):
        if sep in s:
            return s.rsplit(sep, 1)[0] + sep
    return ""


# ---------------------------------------------------------------------------
# 1. CategoricalDetector
# ---------------------------------------------------------------------------


class CategoricalDetector:
    """Detect string literals that represent a bounded category.

    A literal is **categorical** when the same ``(predicate, object_value)``
    pair appears in ≥ *threshold* triples.  All such literals are promoted to
    IRI resources in the vocabulary namespace.

    Example::

        ex:Alice  ex:is  "Director"   ┐
        ex:Bob    ex:is  "Director"   ┘ threshold=2 → vocab:Director
    """

    def __init__(
        self,
        threshold: int = 2,
        vocab_namespace: str = "http://riverbank.example/vocab/",
    ) -> None:
        self.threshold = threshold
        self.vocab_namespace = vocab_namespace

    def detect(self, triples: list) -> dict[tuple[str, str], str]:
        """Identify categorical literals.

        :returns: Mapping ``{(predicate, literal_value): new_iri}``.
        """
        counts: Counter = Counter()
        for t in triples:
            if not _is_iri(t.object_value):
                counts[(t.predicate, t.object_value)] += 1
        return {
            (pred, val): self.vocab_namespace + _to_camel_case(val)
            for (pred, val), cnt in counts.items()
            if cnt >= self.threshold
        }

    def promote(
        self, triples: list, categorical_map: dict[tuple[str, str], str]
    ) -> tuple[list, int]:
        """Rewrite object literals using *categorical_map*.

        :returns: ``(new_triples, n_promoted)``
        """
        result = []
        n = 0
        for t in triples:
            key = (t.predicate, t.object_value)
            if key in categorical_map:
                result.append(t.model_copy(update={"object_value": categorical_map[key]}))
                n += 1
            else:
                result.append(t)
        return result, n


# ---------------------------------------------------------------------------
# 2. PredicateCollapser
# ---------------------------------------------------------------------------


class PredicateCollapser:
    """Detect clusters of semantically equivalent predicates and collapse them
    to a single canonical form.

    Two backends are supported:

    * **deterministic** — edit-distance similarity on local predicate names
      using :class:`difflib.SequenceMatcher`.
    * **llm** — single LLM prompt asking for groupings (callable injected at
      call time so the class remains pure Python with no LLM dependency).

    The *canonical* predicate within each cluster is the most frequently
    occurring one in the triple buffer.
    """

    def __init__(
        self,
        backend: str = "deterministic",
        similarity_threshold: float = 0.6,
    ) -> None:
        self.backend = backend
        self.similarity_threshold = similarity_threshold

    def find_clusters(
        self,
        triples: list,
        llm_client: Optional[Callable[[list[str]], list[list[str]]]] = None,
    ) -> dict[str, str]:
        """Return ``{non_canonical_predicate: canonical_predicate}``.

        When *backend* is ``"llm"``, *llm_client* must be a callable that
        accepts a list of predicate strings and returns a list of groups
        (each group is a list of semantically equivalent predicate strings).
        """
        preds = list({t.predicate for t in triples})
        if len(preds) < 2:
            return {}
        if self.backend == "llm" and llm_client is not None:
            return self._llm_clusters(preds, triples, llm_client)
        return self._deterministic_clusters(preds, triples)

    def _deterministic_clusters(
        self, preds: list[str], triples: list
    ) -> dict[str, str]:
        local_names = {p: _local_name(p) for p in preds}
        freq: Counter = Counter(t.predicate for t in triples)
        clusters: list[list[str]] = []
        assigned: set[str] = set()

        for p in sorted(preds, key=lambda x: (-freq[x], x)):  # most frequent first
            if p in assigned:
                continue
            cluster = [p]
            assigned.add(p)
            for q in sorted(preds, key=lambda x: (-freq[x], x)):
                if q in assigned:
                    continue
                ratio = SequenceMatcher(
                    None, local_names[p], local_names[q]
                ).ratio()
                if ratio >= self.similarity_threshold:
                    cluster.append(q)
                    assigned.add(q)
            clusters.append(cluster)

        collapse_map: dict[str, str] = {}
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            canonical = max(cluster, key=lambda x: freq[x])
            for p in cluster:
                if p != canonical:
                    collapse_map[p] = canonical
        return collapse_map

    def _llm_clusters(
        self,
        preds: list[str],
        triples: list,
        llm_client: Callable[[list[str]], list[list[str]]],
    ) -> dict[str, str]:
        freq: Counter = Counter(t.predicate for t in triples)
        groups: list[list[str]] = llm_client(preds)
        collapse_map: dict[str, str] = {}
        for group in groups:
            if len(group) < 2:
                continue
            canonical = max(group, key=lambda x: freq.get(x, 0))
            for p in group:
                if p != canonical:
                    collapse_map[p] = canonical
        return collapse_map

    def collapse(
        self, triples: list, collapse_map: dict[str, str]
    ) -> tuple[list, int]:
        """Apply *collapse_map* to every triple's predicate.

        :returns: ``(new_triples, n_collapsed)``
        """
        result = []
        n = 0
        for t in triples:
            if t.predicate in collapse_map:
                result.append(t.model_copy(update={"predicate": collapse_map[t.predicate]}))
                n += 1
            else:
                result.append(t)
        return result, n


# ---------------------------------------------------------------------------
# 3. FactDecomposer
# ---------------------------------------------------------------------------

# Qualifier patterns: (compiled_regex, qualifier_predicate_name)
# Each regex must capture the qualifier value in group 1.
# Patterns are tried in order; first match wins.
# End-anchored patterns (with $) are listed first so they take priority over
# mid-word variants, which match the same tokens anywhere in the local name.
_QUALIFIER_PATTERNS: list[tuple[re.Pattern, str]] = [
    # _in_YYYY  or  _YYYY at end
    (re.compile(r"_in_(\d{4})$", re.IGNORECASE), "ex:year"),
    (re.compile(r"_(\d{4})$"), "ex:year"),
    # _on_DATE (e.g. _on_15_march, _on_march_15) at end
    (re.compile(r"_on_(\d{1,2}_\w+|\w+_\d{1,2})$", re.IGNORECASE), "ex:date"),
    # Ordinals at end: _first, _second, …, _tenth
    (
        re.compile(
            r"_(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)$",
            re.IGNORECASE,
        ),
        "ex:ordinal",
    ),
    # Numeric ordinals at end: _1st, _2nd, _3rd, _4th, …
    (re.compile(r"_(\d+(?:st|nd|rd|th))$", re.IGNORECASE), "ex:ordinal"),
    # Mid-word ordinals: _first_, _second_, … (predicate continues after ordinal)
    # e.g. won_first_FA_Cup → won_FA_Cup  +  ex:ordinal "first"
    (
        re.compile(
            r"_(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)_",
            re.IGNORECASE,
        ),
        "ex:ordinal",
    ),
    # Mid-word numeric ordinals: _1st_, _2nd_, …
    (re.compile(r"_(\d+(?:st|nd|rd|th))_", re.IGNORECASE), "ex:ordinal"),
    # Number words at mid-word position: _two_, _three_, …, _ten_
    # e.g. won_two_further_European_Cups → won_further_European_Cups + count "two"
    (
        re.compile(
            r"_(two|three|four|five|six|seven|eight|nine|ten)_",
            re.IGNORECASE,
        ),
        "ex:count",
    ),
]


class FactDecomposer:
    """Detect predicates that encode a qualifier in their local name and
    decompose them into a base predicate triple plus a separate qualifier
    triple on the same subject.

    Supported qualifier patterns:

    * Year: ``_in_YYYY`` or ``_YYYY`` → ``ex:year "YYYY"``
    * Date: ``_on_<date>`` → ``ex:date "<date>"``
    * Ordinal: ``_first``, ``_second``, ``_Nth``, ``_3rd`` → ``ex:ordinal "…"``

    Example::

        ex:subject  ex:acquired_company_in_2022  ex:Acme
        → ex:subject  ex:acquired_company  ex:Acme
        → ex:subject  ex:year              "2022"
    """

    def decompose(self, triples: list) -> tuple[list, int]:
        """Expand each fact-stuffed triple into two triples.

        Handles both end-of-string qualifiers (``founded_in_2019``) and
        mid-word qualifiers (``won_first_FA_Cup`` → ``won_FA_Cup``).

        :returns: ``(expanded_triple_list, n_decomposed)``
        """
        result: list = []
        n = 0
        for t in triples:
            local = _local_name(t.predicate)
            ns = _predicate_namespace(t.predicate)
            decomposed = False
            for pattern, qual_pred in _QUALIFIER_PATTERNS:
                m = pattern.search(local)
                if m:
                    before = local[: m.start()]
                    after = local[m.end() :]
                    # Rejoin the fragments around the qualifier, adding a
                    # connecting underscore only when both halves are non-empty.
                    if before and after:
                        base_local = before + "_" + after
                    elif before:
                        base_local = before
                    elif after:
                        base_local = after.lstrip("_")
                    else:
                        base_local = "predicate"
                    qualifier_value = m.group(1).replace("_", " ")
                    base_predicate = (ns + base_local) if ns else base_local
                    result.append(t.model_copy(update={"predicate": base_predicate}))
                    result.append(
                        t.model_copy(update={"predicate": qual_pred, "object_value": qualifier_value})
                    )
                    n += 1
                    decomposed = True
                    break
            if not decomposed:
                result.append(t)
        return result, n


# ---------------------------------------------------------------------------
# 4. URICanonicaliser
# ---------------------------------------------------------------------------


class URICanonicaliser:
    """Rewrite non-canonical subject/object URIs using ``owl:sameAs`` links
    present in the triple buffer.

    After entity resolution writes ``owl:sameAs`` triples, this pass:

    1. Builds equivalence classes from all ``owl:sameAs`` pairs.
    2. Chooses the **canonical** URI for each class — the one that appears
       most frequently as a subject in non-``owl:sameAs`` triples.
    3. Rewrites every occurrence of a non-canonical URI (as subject or
       object) to the canonical form.

    Example::

        # owl:sameAs chain written by entity_resolution
        ex:Marie_Curie  owl:sameAs  ex:Maria_Sklodowska_Curie
        ex:M_Curie      owl:sameAs  ex:Marie_Curie

        # URICanonicaliser rewrites all triples to the canonical URI
        ex:M_Curie              ex:discovered  ex:Polonium
        ex:Maria_Sklodowska_Curie  ex:born_in  "Warsaw"
        →  ex:Marie_Curie  ex:discovered  ex:Polonium
        →  ex:Marie_Curie  ex:born_in     "Warsaw"
    """

    _SAME_AS_PREDICATES = frozenset(
        {
            "owl:sameAs",
            "http://www.w3.org/2002/07/owl#sameAs",
        }
    )

    def _is_same_as(self, predicate: str) -> bool:
        return (
            predicate in self._SAME_AS_PREDICATES
            or predicate.endswith("#sameAs")
            or predicate.endswith("/sameAs")
        )

    def canonicalise(self, triples: list) -> tuple[list, int]:
        """Rewrite non-canonical URIs.

        :returns: ``(rewritten_triples, n_rewritten)``
        """
        # ------------------------------------------------------------------
        # Step 1: build union-find from owl:sameAs edges
        # ------------------------------------------------------------------
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            root = x
            while parent.get(root, root) != root:
                root = parent[root]
            # Path compression
            node = x
            while parent.get(node, node) != node:
                nxt = parent[node]
                parent[node] = root
                node = nxt
            return root

        def union(a: str, b: str) -> None:
            pa, pb = find(a), find(b)
            if pa != pb:
                parent[pb] = pa

        for t in triples:
            if self._is_same_as(t.predicate):
                union(t.subject, t.object_value)

        # ------------------------------------------------------------------
        # Step 2: count subject frequencies per equivalence class
        # ------------------------------------------------------------------
        freq: Counter = Counter()
        for t in triples:
            if not self._is_same_as(t.predicate):
                freq[t.subject] += 1

        # ------------------------------------------------------------------
        # Step 3: choose canonical URI for each class
        # ------------------------------------------------------------------
        class_members: dict[str, set[str]] = defaultdict(set)
        for t in triples:
            for uri in (t.subject, t.object_value if _is_iri(t.object_value) else None):
                if uri:
                    class_members[find(uri)].add(uri)

        canonical: dict[str, str] = {}
        for root, members in class_members.items():
            if len(members) < 2:
                continue
            canon = max(members, key=lambda x: (freq.get(x, 0), x))
            for m in members:
                if m != canon:
                    canonical[m] = canon

        if not canonical:
            return triples, 0

        # ------------------------------------------------------------------
        # Step 4: rewrite
        # ------------------------------------------------------------------
        result = []
        n = 0
        for t in triples:
            new_subj = canonical.get(t.subject, t.subject)
            new_obj = canonical.get(t.object_value, t.object_value)
            if new_subj != t.subject or new_obj != t.object_value:
                updates: dict = {}
                if new_subj != t.subject:
                    updates["subject"] = new_subj
                if new_obj != t.object_value:
                    updates["object_value"] = new_obj
                result.append(t.model_copy(update=updates))
                n += 1
            else:
                result.append(t)
        return result, n


# ---------------------------------------------------------------------------
# LLM predicate collapse client factory
# ---------------------------------------------------------------------------

_PREDICATE_COLLAPSE_PROMPT = """\
You are a knowledge graph schema curator.

Below is a list of predicate IRIs extracted from a single document.
Group the predicates that are **semantically equivalent** — i.e. they express
the same relationship between subject and object, just worded differently.

Rules:
- Only group predicates whose meaning is clearly the same.
- Do NOT group predicates that have meaningfully different semantics.
- Return ONLY a JSON object with key "groups", containing an array of arrays.
  Each inner array lists the equivalent predicate strings.
  Predicates that have no equivalent can be omitted or listed alone.
- Do not include any explanation outside the JSON.

Predicates:
{predicates}
"""


def build_llm_predicate_collapser(
    settings: Any,
    profile: Any,
) -> "Optional[Callable[[list[str]], list[list[str]]]]":
    """Return an LLM callable for predicate grouping, or ``None`` on failure.

    The callable accepts a list of predicate IRI strings and returns a list
    of equivalence groups (each group is a list of semantically equivalent
    predicate strings).  Used by :class:`PredicateCollapser` in ``llm`` mode.

    Falls back to ``None`` (caller uses deterministic mode) when the openai
    package is unavailable or the LLM call is not configured.
    """
    try:
        import json  # noqa: PLC0415

        from openai import OpenAI  # noqa: PLC0415

        model_provider = getattr(profile, "model_provider", "ollama")
        model_name = getattr(profile, "model_name", "llama3.2")

        api_base = getattr(settings.llm, "api_base", "http://localhost:11434/v1")
        api_key = getattr(settings.llm, "api_key", "ollama" if model_provider == "ollama" else "")
        # api_base is already normalised by LLMSettings._normalise_api_base validator

        client = OpenAI(api_key=api_key, base_url=api_base)

        def _llm_grouper(predicates: list[str]) -> list[list[str]]:
            prompt = _PREDICATE_COLLAPSE_PROMPT.format(
                predicates="\n".join(predicates)
            )
            try:
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=1024,
                )
                raw = resp.choices[0].message.content or "{}"
                # Strip markdown code fences if present
                raw = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.MULTILINE)
                raw = re.sub(r"```$", "", raw.strip())
                data = json.loads(raw)
                groups: list[list[str]] = data.get("groups", [])
                # Validate: only keep groups whose members are in our predicate set
                pred_set = set(predicates)
                return [
                    [p for p in g if p in pred_set]
                    for g in groups
                    if len([p for p in g if p in pred_set]) >= 2
                ]
            except Exception as _e:  # noqa: BLE001
                import logging as _log  # noqa: PLC0415
                _log.getLogger(__name__).warning(
                    "LLM predicate collapse call failed, falling back to deterministic: %s", _e
                )
                return []

        return _llm_grouper
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# VocabularyNormalisationPass (orchestrator)
# ---------------------------------------------------------------------------


class VocabularyNormalisationPass:
    """Orchestrate all four vocabulary normalisation sub-passes.

    Usage::

        pass_ = VocabularyNormalisationPass.from_profile(profile)
        result = pass_.run(triple_buffer)
        # result.triples  — normalised triple list
        # result.vocab_literals_promoted, .vocab_predicates_collapsed, …

    The pass is idempotent: running it twice on the same buffer produces the
    same result as running it once (assuming no new categorical clusters
    emerge after the first pass).
    """

    def __init__(self, config: NormalisationConfig) -> None:
        self.config = config
        self._categorical = CategoricalDetector(
            threshold=config.categorical_threshold,
            vocab_namespace=config.vocabulary_namespace,
        )
        self._collapser = PredicateCollapser(
            backend=config.predicate_collapse_backend,
        )
        self._decomposer = FactDecomposer()
        self._canonicaliser = URICanonicaliser()

    @classmethod
    def from_profile(cls, profile: Any) -> "VocabularyNormalisationPass":
        """Construct from a :class:`~riverbank.pipeline.CompilerProfile`."""
        cfg: dict = getattr(profile, "vocabulary_normalisation", {})
        config = NormalisationConfig(
            enabled=cfg.get("enabled", True),
            categorical_threshold=cfg.get("categorical_threshold", 2),
            collapse_predicates=cfg.get("collapse_predicates", True),
            predicate_collapse_backend=cfg.get(
                "predicate_collapse_backend", "deterministic"
            ),
            decompose_stuffed_predicates=cfg.get("decompose_stuffed_predicates", True),
            rewrite_canonical_uris=cfg.get("rewrite_canonical_uris", False),
            vocabulary_namespace=cfg.get(
                "vocabulary_namespace", "http://riverbank.example/vocab/"
            ),
        )
        return cls(config)

    def run(
        self,
        triples: list,
        llm_client: Optional[Callable[[list[str]], list[list[str]]]] = None,
    ) -> NormalisationResult:
        """Apply all enabled sub-passes to *triples* and return a result.

        :param triples: List of
            :class:`~riverbank.prov.ExtractedTriple` objects.
        :param llm_client: Optional callable for LLM-guided predicate
            collapsing.  Must accept ``list[str]`` of predicate IRIs and
            return ``list[list[str]]`` of equivalence groups.  Only used
            when ``predicate_collapse_backend: "llm"`` is configured.
        :returns: :class:`NormalisationResult` with normalised triples and
            per-normalisation counts.
        """
        result = list(triples)
        n_promoted = n_collapsed = n_decomposed = n_rewritten = 0

        # 0. Unicode normalization — decode bare unicode escapes in literals
        #    e.g. "1972u201373" → "1972–73"  (leaked \uXXXX without backslash)
        result = [
            t.model_copy(update={"object_value": _normalize_literal_unicode(t.object_value)})
            if not _is_iri(t.object_value) and _UNICODE_ESCAPE_RE.search(t.object_value)
            else t
            for t in result
        ]

        # 1. Categorical literal → IRI
        cat_map = self._categorical.detect(result)
        if cat_map:
            result, n_promoted = self._categorical.promote(result, cat_map)

        # 2. Predicate cluster collapse
        if self.config.collapse_predicates:
            collapse_map = self._collapser.find_clusters(result, llm_client)
            if collapse_map:
                result, n_collapsed = self._collapser.collapse(result, collapse_map)

        # 3. Fact-stuffed predicate decomposition
        if self.config.decompose_stuffed_predicates:
            result, n_decomposed = self._decomposer.decompose(result)

        # 4. Entity URI canonicalisation
        if self.config.rewrite_canonical_uris:
            result, n_rewritten = self._canonicaliser.canonicalise(result)

        # 5. Deduplication — after URI rewriting, previously distinct triples
        #    may now share the same (subject, predicate, object_value) key.
        #    Keep the one with the highest confidence.
        seen: dict[tuple[str, str, str], Any] = {}
        for t in result:
            key = (t.subject, t.predicate, t.object_value)
            if key not in seen or t.confidence > seen[key].confidence:
                seen[key] = t
        result = list(seen.values())

        return NormalisationResult(
            triples=result,
            vocab_literals_promoted=n_promoted,
            vocab_predicates_collapsed=n_collapsed,
            vocab_facts_decomposed=n_decomposed,
            vocab_uris_rewritten=n_rewritten,
        )
