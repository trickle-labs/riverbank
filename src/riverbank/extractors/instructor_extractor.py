from __future__ import annotations

import logging
import re
from typing import Any, ClassVar, Optional

from rapidfuzz import fuzz as _fuzz

from opentelemetry import trace as otel_trace

from riverbank.extractors.noop import ExtractionResult
from riverbank.prov import EvidenceSpan, ExtractedTriple

logger = logging.getLogger(__name__)

# Minimum rapidfuzz partial_ratio score (0–100) for an excerpt to be considered
# grounded in the source text.  partial_ratio finds the best matching window of
# the same length in the longer string, so it tolerates minor LLM reformatting
# (decimal spacing artefacts, stripped markdown, em-dash variants) while still
# rejecting outright fabrications.
# Set to 75: documents with Markdown table/bullet syntax score 75–81% on valid
# facts because partial_ratio must align bullet markers ("| * ") that the LLM
# omits in excerpts.  75 rescues borderline cases while still blocking hallucinations.
_CITATION_SIMILARITY_THRESHOLD: int = 75


_DEFAULT_PROMPT = """\
# INSTRUCTION: OUTPUT ONLY VALID JSON ARRAY
You are a knowledge graph compiler. Extract factual claims from the technical document as RDF triples.

**OUTPUT FORMAT:** Respond with ONLY a valid JSON array. Do NOT include any explanatory text before or after the JSON. The JSON must be parseable by Python json.loads().

## JSON Schema (Example)
```json
[
  {
    "subject": "ex:Subject_Entity",
    "predicate": "ex:relatedTo",
    "object_value": "ex:Object_Entity",
    "confidence": 0.95,
    "evidence": {
      "char_start": 0,
      "char_end": 42,
      "excerpt": "Subject Entity is related to Object Entity",
      "page_number": null
    }
  }
]
```

## Extraction Rules
For each claim, provide:
1. **subject**: prefixed IRI for named entities (e.g. ex:Solar_System, ex:Oxygen, ex:Contract_Act_1990)
2. **predicate**: ALWAYS use the ex: prefix — write ex:relatedTo NOT relatedTo
   (e.g. ex:relatedTo, ex:hasProperty, ex:partOf, ex:definedIn)
3. **object_value**: prefixed IRI for named entities; plain literal for everything else
   - Named entity (person, place, org, concept, award) → use ex: prefix with underscores
     e.g. ex:Pierre_Curie, ex:University_of_Paris, ex:Nobel_Prize_in_Physics, ex:Polonium
   - Scalar value, description, date, measure → plain string
     e.g. "1934-07-04", "physicist", "66 years old"
   - RULE: if you would capitalise it as a proper noun, use ex:. If it is a value or description, use a plain string.
4. **confidence**: float 0.0–1.0 reflecting how clearly the text supports the claim
5. **evidence**: exact character offsets (char_start, char_end) and verbatim excerpt

## Critical Constraints
- Only extract claims directly supported by the text.
- Do NOT fabricate evidence — the excerpt MUST appear verbatim in the source.
- Always return a JSON array, even if empty: []
- SAFETY: If a subject or object_value is a pronoun (She, He, They, It, Who, Her, His, etc.), SKIP that triple entirely.
- EXCERPT FORMAT: Write plain text in the excerpt field. If the source text contains markdown links like [text](url "title"), write just the plain text (e.g. "text") — do NOT copy the markdown syntax into the excerpt.
- OBJECT RULES: The object_value must be the TARGET of the relationship, never a relationship name itself.
  BAD:  subject=ex:Marie_Curie, predicate=ex:relationship, object_value="married_to"   ← object is a predicate name
  GOOD: subject=ex:Marie_Curie, predicate=ex:married, object_value=ex:Pierre_Curie
- ENTITY CAPITALISATION: Always write entity names with proper capitalisation in the ex: prefix.
  BAD:  ex:mobile_radiography_units, ex:radium_metal, ex:radioactivity
  GOOD: ex:Mobile_Radiography_Units, ex:Radium_Metal, ex:Radioactivity
  Rule: if a concept is a named thing (not a plain description), capitalise each content word.
"""

_PERMISSIVE_TIER_GUIDANCE = """\
Extract ALL factual claims using the following confidence tiers:
  EXPLICIT  (0.90–1.00): claim is stated verbatim or nearly verbatim
  STRONG    (0.70–0.89): claim is clearly implied with strong textual support
  IMPLIED   (0.50–0.69): claim is a reasonable inference from the text
  WEAK      (0.35–0.49): claim is plausible but not directly stated

Use the confidence score as a ROUTING SIGNAL: even 0.35 triples are valuable
for discovery. Extract broadly within the ontology constraints — do NOT skip
claims just because they are implied rather than explicit.
"""

_HIGH_PRECISION_GUIDANCE = """\
EXTRACTION FOCUS — HIGH PRECISION:
Extract ONLY claims that are explicitly and unambiguously stated in the text.
Do NOT infer, imply, or interpret. Assign confidence 0.90–1.00 only.
Skip any claim that requires reading between the lines.
"""

_FACTS_ONLY_GUIDANCE = """\
EXTRACTION FOCUS — FACTS ONLY:
Extract only explicitly stated factual assertions. Exclude:
- Opinions, estimates, or hedged language ("might", "could", "arguably")
- Metadata about the document structure itself
- Contextual or background framing that is not a standalone fact
Assign confidence strictly based on how directly the text states the claim.
"""

_CQ_OBJECTIVES_PREFIX = "EXTRACTION OBJECTIVES (derived from competency questions):\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Small "function words" that don't disqualify a phrase from being a proper-noun
# entity even when they appear in lower-case inside a multi-word name.
# Includes common English prepositions/articles AND generic nouns that routinely
# follow a proper name ("Curie unit", "Nobel Prize", "Radium Institute").
_STOPWORDS = frozenset({
    "a", "an", "and", "at", "by", "de", "del", "der", "des", "du", "in",
    "of", "on", "or", "the", "to", "van", "von", "for", "with",
    # generic nouns commonly trailing a proper-noun head
    "unit", "units", "metal", "element", "compound", "substance",
    "institute", "institution", "centre", "center", "service",
    "award", "medal", "prize", "fund", "foundation", "society",
    "process", "method", "technique", "theory", "effect",
})


def _maybe_entity_iri(obj: str) -> str:
    """Return ``ex:Obj`` when *obj* looks like a proper-noun entity, else *obj* unchanged.

    Two surface forms are recognised:

    1. **Title Case phrases** — every word is capitalised or a stop-word:
       ``"Pierre Curie"`` → ``ex:Pierre Curie``  (spaces normalised by graph writer)
       ``"Nobel Prize in Physics"`` → ``ex:Nobel Prize in Physics``

    2. **snake_case tokens** — underscores used as word separators, with at least
       one capitalised component word:
       ``"woman_to_win_a_Nobel_Prize"`` → ``ex:woman_to_win_a_Nobel_Prize``
       ``"first_person_to_win_Nobel_Prize_twice"`` → same treatment
       Pure lower-case snake strings like ``"mobile_radiography_units"`` stay as
       literals because no component is capitalised.

    Scalars are always rejected: strings starting with a digit, ISO-like strings
    containing a colon (``"10:30"``), or strings longer than 120 characters.
    """
    if not obj or len(obj) > 120:
        return obj
    # Reject obvious scalars: starts with digit, contains colon (dates/times)
    if obj[0].isdigit() or ":" in obj:
        return obj

    # Boolean values: the LLM sometimes outputs True/False as object values for
    # flag-style predicates (e.g. was_first_woman_to_win_nobel_prize → True).
    # Emit as a typed xsd:boolean literal rather than the IRI ex:True.
    if obj.lower() in {"true", "false"}:
        return f'"{obj.lower()}"^^xsd:boolean'

    # Strip trailing disambiguation parentheticals before any further checks.
    # "curie (unit)" → "curie", "Nobel Prize in Physics (1903)" → "Nobel Prize in Physics"
    stripped = re.sub(r"\s*\([^)]+\)\s*$", "", obj).strip()
    if not stripped:
        return obj
    obj = stripped

    # --- snake_case branch ---
    if "_" in obj and " " not in obj:
        components = obj.split("_")
        # At least one component must be capitalised to qualify as an entity
        if any(c and c[0].isupper() for c in components):
            return f"ex:{obj}"
        return obj

    # --- Title Case phrase branch ---
    # Single-word, purely-alphabetic objects: capitalise first letter so that
    # concept names the LLM lowercased ("radioactivity", "curie") are promoted
    # to IRIs. Multi-word strings are left unchanged — the Title Case check
    # below already requires each content word to be capitalised.
    words = obj.split()
    if len(words) == 1 and obj.isalpha():
        obj = obj[0].upper() + obj[1:]
        words = [obj]

    if not words:
        return obj
    # Every word must be capitalised (first letter upper) OR be a stop-word
    if not all(w[0].isupper() or w.lower() in _STOPWORDS for w in words if w):
        return obj
    # At least one content word must be capitalised
    if not any(w[0].isupper() for w in words if w.lower() not in _STOPWORDS):
        return obj
    return f"ex:{obj}"


def _build_extraction_focus_prompt(base_prompt: str, extraction_focus: str) -> str:
    """Inject extraction focus guidance based on the profile's extraction_focus setting."""
    if extraction_focus == "high_precision":
        return f"{_HIGH_PRECISION_GUIDANCE}\n\n{base_prompt}"
    if extraction_focus == "facts_only":
        return f"{_FACTS_ONLY_GUIDANCE}\n\n{base_prompt}"
    return base_prompt  # "comprehensive" = no additional constraint


def _build_permissive_prompt(base_prompt: str, extraction_strategy: dict) -> str:
    """Inject permissive-mode tiered guidance into the base prompt."""
    if extraction_strategy.get("mode") == "permissive":
        return f"{_PERMISSIVE_TIER_GUIDANCE}\n\n{base_prompt}"
    return base_prompt


def _build_extraction_target_prompt(base_prompt: str, extraction_strategy: dict) -> str:
    """Inject a quantitative extraction target into the prompt.

    When ``extraction_strategy.extraction_target`` is configured, a directive
    is prepended to tell the LLM how many triples it should aim for.  Without
    this, most LLMs stop after ~10-20 "representative" examples instead of
    scanning every sentence exhaustively.

    Config example (profile YAML)::

        extraction_strategy:
          extraction_target:
            min_triples: 50
            max_triples: 150  # optional cap (also sets max_triples_per_fragment)
    """
    target: dict = extraction_strategy.get("extraction_target", {})
    if not target:
        return base_prompt
    min_t: int = int(target.get("min_triples", 0))
    max_t: int = int(target.get("max_triples", 0))
    if min_t <= 0 and max_t <= 0:
        return base_prompt
    parts = ["EXTRACTION VOLUME REQUIREMENT:"]
    if min_t > 0 and max_t > 0:
        parts.append(
            f"You MUST extract between {min_t} and {max_t} triples. "
            "Scan every sentence, every clause, every listed fact. "
            "Do NOT stop early — keep extracting until you reach the minimum."
        )
    elif min_t > 0:
        parts.append(
            f"You MUST extract at least {min_t} triples. "
            "Scan every sentence, every clause, every listed fact. "
            "Do NOT stop early — keep extracting until you reach the minimum."
        )
    else:
        parts.append(f"Extract no more than {max_t} triples, choosing the highest-confidence ones.")
    parts.append(
        "This is a dense, information-rich document. "
        "Every named entity, date, award, relationship, discovery, and biographical fact "
        "is a candidate triple."
    )
    block = "\n".join(parts)
    return f"{block}\n\n{base_prompt}"


def _build_cq_objectives(competency_questions: list[str]) -> str:
    """Transform CQs into EXTRACTION OBJECTIVES block."""
    if not competency_questions:
        return ""
    lines = [_CQ_OBJECTIVES_PREFIX]
    for i, cq in enumerate(competency_questions, 1):
        lines.append(f"  {i}. {cq}")
    lines.append(
        "\nFocus extraction on facts that help answer these questions.\n"
    )
    return "\n".join(lines)


def _build_ontology_constraint(allowed_predicates: list[str], allowed_classes: list[str]) -> str:
    """Build an ontology constraint block to inject into the prompt."""
    parts: list[str] = []
    if allowed_predicates:
        pred_list = ", ".join(allowed_predicates)
        parts.append(
            f"ONTOLOGY CONSTRAINT — use ONLY these predicates: {pred_list}\n"
            "If a relationship does not fit any of the above predicates, SKIP IT."
        )
    if allowed_classes:
        class_list = ", ".join(allowed_classes)
        parts.append(
            f"ONTOLOGY CONSTRAINT — use ONLY these classes for subject/object types: {class_list}"
        )
    return "\n".join(parts)


def _build_functional_predicate_hints(predicate_constraints: dict) -> str:
    """v0.12.1: Build functional predicate hint block.

    For predicates annotated with ``max_cardinality: 1`` in the
    ``predicate_constraints`` profile block, the extraction prompt is told
    to "pick the most specific value only" for that predicate.  This prevents
    the LLM from producing multiple conflicting values for a functional property.

    Example profile config::

        predicate_constraints:
          ex:hasOwner:
            max_cardinality: 1
          ex:hasVersion:
            max_cardinality: 1

    Returns an empty string when ``predicate_constraints`` is empty.
    """
    if not predicate_constraints:
        return ""

    functional: list[str] = [
        pred
        for pred, constraints in predicate_constraints.items()
        if isinstance(constraints, dict) and constraints.get("max_cardinality") == 1
    ]
    if not functional:
        return ""

    pred_list = ", ".join(functional)
    return (
        f"FUNCTIONAL PREDICATES — these predicates are single-valued (max 1 object per subject): "
        f"{pred_list}\n"
        "For each functional predicate, extract ONLY the most specific/definitive value. "
        "Do NOT produce multiple triples with the same functional predicate for the same subject."
    )


def _estimate_tokens(text: str) -> int:
    """Fast token estimate: byte length / 4 (safe for both tiktoken and Ollama)."""
    return max(1, len(text.encode("utf-8")) // 4)


# Valid single-character JSON escape sequences (after the backslash)
_VALID_JSON_ESCAPES = frozenset('"\\' + r'\/bfnrt')


def _fix_json_escapes(s: str) -> str:
    """Remove or neutralise invalid JSON escape sequences such as \\( or \\'.

    Models like gemma4 embed markdown links (e.g. ``[text](./Foo_(bar) "Foo
    \\(bar\\)")``) inside excerpt strings and escape the parentheses as ``\\(``,
    which is not a legal JSON escape.  This function strips the backslash from
    any ``\\X`` where X is not a recognised JSON escape character, converting it
    to just ``X``.  Valid sequences (``\\n``, ``\\"``, ``\\\\``, ``\\uXXXX``,
    …) are left untouched.
    """
    result: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _VALID_JSON_ESCAPES:
                result.append(ch)
                result.append(nxt)
                i += 2
                # Consume the four hex digits of \\uXXXX so we don't
                # accidentally strip a backslash from inside them.
                if nxt == "u":
                    result.append(s[i : i + 4])
                    i += 4
            else:
                # Invalid escape — drop the backslash, keep the character.
                result.append(nxt)
                i += 2
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _extract_json_from_content(content: str) -> list[Any]:
    """Extract and parse a list of triples from an LLM response string.

    Handles two common failure modes from local models:

    1. **Markdown-wrapped JSON** — response contains ````json … ```` fences.
    2. **Object-wrapped array** — the model wraps the array in an object such as
       ``{"tasks": [...]}`` or ``{"triples": [...]}`` instead of returning a
       bare array.

    After unwrapping, passes the raw JSON string through :func:`_fix_json_escapes`
    before calling ``json.loads`` so that models that emit ``\\(`` or ``\\'``
    do not cause an ``Invalid JSON`` validation error.
    """
    import json as _json  # noqa: PLC0415
    import re  # noqa: PLC0415

    text = (content or "").strip()

    # 1. Strip markdown code fences if present.
    md = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if md:
        text = md.group(1).strip()

    # 2. Fix invalid escape sequences before parsing.
    text = _fix_json_escapes(text)

    # 3. Parse — if it fails, try stripping markdown link syntax from string
    # values.  Models that include [text](url "title") in excerpts produce
    # unescaped double-quotes that break JSON parsing.  We normalise all
    # markdown links inside JSON string values to just their display text.
    def _strip_md_links(raw: str) -> str:
        """Replace [display](url "title") → display inside JSON strings.

        The URL in a markdown link can itself contain parentheses (e.g.
        ``./Curie_(Paris)``).  The inner pattern handles one level of nesting.

        IMPORTANT: The display text pattern ``[^"\\]\\n]*`` excludes quotes and
        newlines.  This prevents the regex from accidentally treating the opening
        ``[`` of the JSON array itself as the start of a markdown link (which
        would greedily consume the entire JSON structure up to the first ``]``).
        """
        return re.sub(
            r'\[([^"\]\n]*)\]\((?:[^()]|\([^()]*\))*\)',
            r'\1',
            raw,
        )

    parse_error: Exception | None = None
    for attempt_text in (text, _strip_md_links(text)):
        try:
            # Use raw_decode so that trailing content after the root value
            # (e.g. a leftover markdown fence ```) is silently ignored instead
            # of raising "Extra data".
            parsed, _ = _json.JSONDecoder().raw_decode(attempt_text)
            break
        except Exception as exc:  # noqa: BLE001
            parse_error = exc
            parsed = None

    if parsed is None:
        # Both JSON parsing attempts failed.  Fall back to field-by-field regex
        # extraction that ignores the evidence field entirely.  This handles
        # evidence strings containing markdown links with unescaped quotes that
        # even _strip_md_links can't fix (e.g. nested/malformed link structures).
        # Evidence is set to a blank object; char_start/char_end remain 0.
        field_pat = re.compile(
            r'"subject"\s*:\s*"([^"]+)"\s*,'
            r'\s*"predicate"\s*:\s*"([^"]+)"\s*,'
            r'\s*"object_value"\s*:\s*"([^"]+)"\s*,'
            r'\s*"confidence"\s*:\s*([0-9.]+)',
            re.DOTALL,
        )
        parsed = [
            {
                "subject": m.group(1),
                "predicate": m.group(2),
                "object_value": m.group(3),
                "confidence": float(m.group(4)),
                "evidence": {"char_start": 0, "char_end": 0, "excerpt": "", "page_number": None},
            }
            for m in field_pat.finditer(text)
        ]
        if not parsed:
            raise ValueError(
                f"Could not parse LLM JSON response: {parse_error}"
            ) from parse_error
        logger.debug(
            "instructor_extractor: JSON parse failed, fell back to field-by-field "
            "extraction (%d triples recovered)",
            len(parsed),
        )

    # 4. Unwrap object envelope if the model wrapped the array.
    if isinstance(parsed, dict):
        for key in ("tasks", "triples", "items", "data", "results", "extractions"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break

    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected a JSON array of triples, got {type(parsed).__name__}"
        )

    return parsed


def _apply_token_budget(
    system_prompt: str,
    fragment_text: str,
    max_tokens: int,
) -> str:
    """Trim the system prompt when the assembled prompt exceeds *max_tokens*.

    Trimming priority (never truncates fragment_text):
    1. few-shot examples (lines after "EXAMPLES:" marker)
    2. corpus context (lines before "DOCUMENT SUMMARY:" marker)
    3. entity catalog (lines between "ENTITY CATALOG:" and the next section)
    4. document summary (lines after "DOCUMENT SUMMARY:" up to the next section)

    Returns the (possibly trimmed) system prompt.
    """
    fragment_tokens = _estimate_tokens(fragment_text)
    system_tokens = _estimate_tokens(system_prompt)
    budget_remaining = max_tokens - fragment_tokens

    if system_tokens <= budget_remaining:
        return system_prompt

    lines = system_prompt.splitlines()

    def _remove_section(lines: list[str], marker: str) -> list[str]:
        in_section = False
        result: list[str] = []
        for line in lines:
            if marker in line:
                in_section = True
            if in_section and line.strip() == "" and result and result[-1].strip() == "":
                in_section = False
            if not in_section:
                result.append(line)
        return result

    for marker in ("EXAMPLES:", "CORPUS CONTEXT:", "ENTITY CATALOG:", "DOCUMENT SUMMARY:"):
        if _estimate_tokens("\n".join(lines)) <= budget_remaining:
            break
        lines = _remove_section(lines, marker)

    # Last resort: hard-truncate system prompt
    trimmed = "\n".join(lines)
    while _estimate_tokens(trimmed) > budget_remaining and len(trimmed) > 200:
        trimmed = trimmed[: int(len(trimmed) * 0.9)]

    return trimmed


class InstructorExtractor:
    """LLM-based extractor using the ``instructor`` library for structured output.

    Uses any OpenAI-compatible endpoint (Ollama for local/CI, OpenAI for prod).
    Applies Pydantic validation for every triple and validates that evidence
    excerpts are present in the source text (citation grounding).

    Requires::

        pip install 'riverbank[ingest]'

    Entry point::

        riverbank.extractors = instructor = riverbank.extractors.instructor_extractor:InstructorExtractor
    """

    name: ClassVar[str] = "instructor"

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    def extract(self, fragment: object, profile: object, trace: object) -> ExtractionResult:
        """Extract triples from a ``DocumentFragment`` using the configured LLM.

        OTel spans are emitted for the full extraction and for each LLM call.
        Token counts and model name are recorded in the span attributes and
        returned in ``ExtractionResult.diagnostics``.
        """
        tracer = otel_trace.get_tracer(__name__)
        with tracer.start_as_current_span("instructor_extractor.extract") as span:
            try:
                return self._extract_with_llm(fragment, profile, span)
            except Exception as exc:  # noqa: BLE001
                logger.warning("instructor extraction failed: %s", exc)
                span.set_status(otel_trace.StatusCode.ERROR, str(exc))
                return ExtractionResult(
                    triples=[],
                    diagnostics={"error": str(exc)},
                )

    def extract_batch(
        self, fragments: list[object], profile: object, trace: object
    ) -> dict[str, ExtractionResult]:
        """Extract triples from multiple fragments in a single LLM call.

        Combines fragment texts and extracts triples for all of them together,
        reducing the number of LLM calls needed. Returns a mapping from fragment
        key to ExtractionResult.

        Args:
            fragments: List of DocumentFragment objects to extract from
            profile: CompilerProfile object
            trace: OTel trace object (unused)

        Returns:
            Dict mapping fragment_key → ExtractionResult
        """
        if not fragments:
            return {}

        tracer = otel_trace.get_tracer(__name__)
        with tracer.start_as_current_span("instructor_extractor.extract_batch") as span:
            try:
                return self._extract_batch_with_llm(fragments, profile, span)
            except Exception as exc:  # noqa: BLE001
                logger.warning("instructor batch extraction failed: %s", exc)
                span.set_status(otel_trace.StatusCode.ERROR, str(exc))
                # Return error result for each fragment
                return {
                    getattr(f, "fragment_key", str(i)): ExtractionResult(
                        triples=[],
                        diagnostics={"error": str(exc)},
                    )
                    for i, f in enumerate(fragments)
                }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_with_llm(
        self,
        fragment: object,
        profile: object,
        span: Any,
    ) -> ExtractionResult:
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "instructor and openai are required for the InstructorExtractor. "
                "Install with: pip install 'riverbank[ingest]'"
            ) from exc

        from pydantic import BaseModel  # noqa: PLC0415

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415

            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434/v1")
        
        # For Ollama, ensure the api_base has /v1 suffix for OpenAI compatibility
        if provider == "ollama" and api_base and not api_base.endswith("/v1"):
            api_base = api_base.rstrip("/") + "/v1"
        
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(
            llm,
            "model",
            getattr(profile, "model_name", "llama3.2"),
        )
        prompt_text: str = getattr(profile, "prompt_text", _DEFAULT_PROMPT)

        # v0.12.0: read profile configuration blocks
        extraction_strategy: dict = getattr(profile, "extraction_strategy", {})
        token_optimization: dict = getattr(profile, "token_optimization", {})
        allowed_predicates: list = getattr(profile, "allowed_predicates", [])
        allowed_classes: list = getattr(profile, "allowed_classes", [])
        competency_questions: list = getattr(profile, "competency_questions", [])
        predicate_constraints: dict = getattr(profile, "predicate_constraints", {})

        # v0.12.0: permissive mode — inject tiered confidence guidance
        prompt_text = _build_permissive_prompt(prompt_text, extraction_strategy)

        # v0.16.0: extraction target — inject quantitative triple-count directive
        prompt_text = _build_extraction_target_prompt(prompt_text, extraction_strategy)

        # v0.17.0: extraction focus — precision vs recall trade-off
        extraction_focus: str = getattr(profile, "extraction_focus", "comprehensive")
        prompt_text = _build_extraction_focus_prompt(prompt_text, extraction_focus)

        # v0.12.0: CQ-guided extraction — prepend EXTRACTION OBJECTIVES
        cq_block = _build_cq_objectives(competency_questions)
        if cq_block:
            prompt_text = cq_block + "\n" + prompt_text

        # v0.12.0: ontology constraint injection
        ontology_block = _build_ontology_constraint(allowed_predicates, allowed_classes)
        if ontology_block:
            prompt_text = ontology_block + "\n\n" + prompt_text

        # v0.12.1: functional predicate hints
        functional_block = _build_functional_predicate_hints(predicate_constraints)
        if functional_block:
            prompt_text = functional_block + "\n\n" + prompt_text

        source_iri: str = getattr(fragment, "source_iri", "")
        text: str = getattr(fragment, "text", "")

        # v0.12.0: token budget manager — trim system prompt before sending
        max_input_tokens: int = token_optimization.get("max_input_tokens_per_fragment", 0)
        if max_input_tokens > 0:
            prompt_text = _apply_token_budget(prompt_text, text, max_input_tokens)

        # v0.12.0: compact output schema
        use_compact: bool = token_optimization.get("compact_output_schema", False)

        # --- define Pydantic schemas local to this call ---
        if use_compact:
            # Short keys save ~20 output tokens per triple
            class _EvidenceSpanIn(BaseModel):
                cs: int   # char_start
                ce: int   # char_end
                e: str    # excerpt
                page_number: Optional[int] = None

            class _TripleIn(BaseModel):
                s: str    # subject
                p: str    # predicate
                o: str    # object_value
                c: float  # confidence
                ev: _EvidenceSpanIn  # evidence

            def _unpack(t: Any) -> tuple[str, str, str, float, Any]:
                return t.s, t.p, t.o, t.c, t.ev

            def _unpack_ev(ev: Any) -> tuple[int, int, str, Optional[int]]:
                return ev.cs, ev.ce, ev.e, ev.page_number
        else:
            class _EvidenceSpanIn(BaseModel):  # type: ignore[no-redef]
                char_start: int
                char_end: int
                excerpt: str
                page_number: Optional[int] = None

            class _TripleIn(BaseModel):  # type: ignore[no-redef]
                subject: str
                predicate: str
                object_value: str
                confidence: float
                evidence: _EvidenceSpanIn

            def _unpack(t: Any) -> tuple[str, str, str, float, Any]:
                return t.subject, t.predicate, t.object_value, t.confidence, t.evidence

            def _unpack_ev(ev: Any) -> tuple[int, int, str, Optional[int]]:
                return ev.char_start, ev.char_end, ev.excerpt, ev.page_number

        # --- build provider-specific instructor client ---
        # v0.14.0: constrained decoding — for Ollama backends, use the `format`
        # parameter to pass a JSON Schema directly to the model, forcing grammar-
        # constrained decode-time conformance.  This eliminates JSON parse errors
        # at the source rather than in post-processing.
        constrained_decoding: bool = (
            provider == "ollama"
            and getattr(profile, "constrained_decoding", False)
        )

        if provider == "anthropic":
            try:
                import anthropic as anthropic_sdk  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "anthropic package is required for the anthropic provider. "
                    "Install with: pip install anthropic"
                ) from exc
            client = instructor.from_anthropic(anthropic_sdk.Anthropic(api_key=api_key))
            mode_kwargs: dict = {}
        elif provider == "copilot":
            # GitHub Models API — OpenAI-compatible, authenticates with a GitHub PAT.
            mode = instructor.Mode.JSON
            client = instructor.from_openai(
                OpenAI(
                    base_url="https://models.inference.ai.azure.com",
                    api_key=api_key,
                ),
                mode=mode,
            )
            mode_kwargs = {}
        else:
            # ollama, openai, vllm, azure-openai — all OpenAI-compatible
            if constrained_decoding:
                # v0.14.0: Ollama structured output mode — pass JSON schema via
                # extra_body["format"]. This forces grammar-constrained decoding
                # at the model level, eliminating JSON parse failures entirely.
                # Use JSON mode so instructor respects the format parameter.
                mode = instructor.Mode.JSON
            else:
                mode = (
                    instructor.Mode.MD_JSON
                    if provider in ("ollama", "vllm")
                    else instructor.Mode.JSON
                )
            client = instructor.from_openai(
                OpenAI(base_url=api_base, api_key=api_key),
                mode=mode,
            )
            mode_kwargs = {}

        # Build extra_body for Ollama (keep-alive + optional JSON schema format)
        # v0.16.0: bump num_predict when an extraction_target is set — default
        # Ollama num_predict (2048) caps output to ~15 triples; for a min_triples
        # target of 50 we need ~8000 tokens, for 150 we need ~24000.
        if provider == "ollama":
            _et = extraction_strategy.get("extraction_target", {})
            _min_t = int(_et.get("min_triples", 0))
            _max_t = int(_et.get("max_triples", 0))
            _target_t = _max_t if _max_t > 0 else _min_t
            # ~160 output tokens per triple (subject+predicate+object+confidence+evidence JSON)
            _tokens_per_triple = 160
            _num_predict = max(4096, _target_t * _tokens_per_triple + 512) if _target_t > 0 else 4096
            ollama_extra: dict = {"keep_alive": "5m", "num_predict": _num_predict}
            if _target_t > 0:
                logger.debug(
                    "instructor_extractor: num_predict set to %d for extraction_target min=%d max=%d",
                    _num_predict, _min_t, _max_t,
                )
            if constrained_decoding:
                # Build JSON Schema for the list-of-triples response type.
                # Ollama >= 0.5 accepts a JSON Schema object in the `format` field.
                try:
                    import json as _json  # noqa: PLC0415
                    triple_schema = _TripleIn.model_json_schema()
                    list_schema = {
                        "type": "array",
                        "items": triple_schema,
                        "title": "ExtractedTriples",
                    }
                    ollama_extra["format"] = list_schema
                    logger.debug(
                        "instructor_extractor: constrained decoding enabled "
                        "(Ollama JSON schema: %d chars)",
                        len(_json.dumps(list_schema)),
                    )
                except Exception as _cd_exc:  # noqa: BLE001
                    logger.debug(
                        "instructor_extractor: could not build JSON schema for "
                        "constrained decoding — falling back to MD_JSON (%s)", _cd_exc
                    )
            extra_body_kwargs: dict = {"extra_body": ollama_extra}
        else:
            extra_body_kwargs = {}

        # v0.14.1: Add explicit JSON-forcing prefix to user message
        # This reinforces to local LLMs like Gemma4 that JSON output is required
        user_message = (
            "RESPOND WITH ONLY VALID JSON. NO EXPLANATIONS OR TEXT OUTSIDE JSON.\n\n"
            "Analyze this document and extract RDF triples:\n\n"
            f"{text}"
        )

        # For Ollama/VLLM with MD_JSON mode: bypass instructor's JSON parser and
        # handle extraction ourselves.  This lets us fix two systematic failure
        # modes that cause every retry attempt to fail:
        #   1. Models wrapping the array in {"tasks": [...]} or similar objects.
        #   2. Invalid JSON escape sequences such as \( inside excerpt strings.
        # instructor retries make both problems worse (prompt grows 2-4x per try).
        use_manual_parse = provider in ("ollama", "vllm") and not constrained_decoding
        if use_manual_parse:
            from openai import OpenAI as _OpenAI  # noqa: PLC0415
            raw_client = _OpenAI(base_url=api_base, api_key=api_key)
            completion = raw_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": user_message},
                ],
                **extra_body_kwargs,
            )
            raw_content = completion.choices[0].message.content or ""
            logger.debug(
                "instructor_extractor: raw completion (%d chars), parsing manually",
                len(raw_content),
            )
            # Dump raw content for debugging when RIVERBANK_DEBUG_LLM is set
            import os as _os  # noqa: PLC0415
            if _os.environ.get("RIVERBANK_DEBUG_LLM"):
                debug_path = _os.environ["RIVERBANK_DEBUG_LLM"]
                with open(debug_path, "w", encoding="utf-8") as _f:
                    _f.write(raw_content)
                logger.info("instructor_extractor: raw LLM output written to %s", debug_path)
            raw_items = _extract_json_from_content(raw_content)
            # Normalize evidence field: models vary in their output format:
            # - Some return evidence as a plain string (coerce to excerpt object)
            # - Some use short keys like "start"/"end" instead of "char_start"/"char_end"
            # - Some omit the excerpt field entirely
            normalized: list[Any] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                ev = item.get("evidence")
                if isinstance(ev, str):
                    item = {**item, "evidence": {
                        "char_start": 0,
                        "char_end": len(ev),
                        "excerpt": ev,
                        "page_number": None,
                    }}
                elif isinstance(ev, dict):
                    # Remap short field names to canonical names
                    if "start" in ev and "char_start" not in ev:
                        ev = {**ev, "char_start": ev.pop("start")}
                    if "end" in ev and "char_end" not in ev:
                        ev = {**ev, "char_end": ev.pop("end")}
                    if "excerpt" not in ev:
                        ev = {**ev, "excerpt": ""}
                    item = {**item, "evidence": ev}
                elif ev is None:
                    item = {**item, "evidence": {
                        "char_start": 0, "char_end": 0,
                        "excerpt": "", "page_number": None,
                    }}
                normalized.append(item)
            response = []
            for item in normalized:
                try:
                    response.append(_TripleIn.model_validate(item))
                except Exception as _val_exc:  # noqa: BLE001
                    logger.debug(
                        "Skipping item that failed _TripleIn validation: %s — %s",
                        {k: str(v)[:60] for k, v in item.items() if k in ("subject", "predicate", "object_value")},
                        _val_exc,
                    )
        else:
            response, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": user_message},
                ],
                response_model=list[_TripleIn],
                **extra_body_kwargs,
                **mode_kwargs,
            )

        # v0.12.0: safety cap — keep top-N by confidence, log warning if exceeded
        # v0.16.0: also honour extraction_target.max_triples as the cap
        _et_max = extraction_strategy.get("extraction_target", {}).get("max_triples", 0)
        max_triples: int = extraction_strategy.get("max_triples_per_fragment", 0) or int(_et_max)
        triples_capped = 0
        if max_triples > 0 and len(response) > max_triples:
            triples_capped = len(response) - max_triples
            response = sorted(response, key=lambda t: _unpack(t)[3], reverse=True)[:max_triples]
            logger.warning(
                "Safety cap: capped %d triples to %d for fragment %s",
                triples_capped,
                max_triples,
                source_iri,
            )

        # --- validate and filter triples ---
        triples_extracted = len(response)
        triples_citation_rejected = 0
        triples_invalid = 0
        validated: list[ExtractedTriple] = []
        for t in response:
            subj, pred, obj, conf, ev_in = _unpack(t)
            cs, ce, excerpt, page_number = _unpack_ev(ev_in)
            # Auto-expand bare predicates: if the LLM omits the ex: prefix
            # (e.g. "createdBy" instead of "ex:createdBy"), add it so that
            # _to_ntriples_term() produces a proper IRI instead of a string literal.
            if pred and ":" not in pred and not pred.startswith("<"):
                pred = f"ex:{pred}"
            # Auto-expand bare subjects (same logic as predicates above).
            if subj and ":" not in subj and not subj.startswith("<"):
                subj = f"ex:{subj}"
            # Auto-expand bare object values that look like named entities to IRIs.
            # The LLM is instructed to use ex:, but falls back to bare strings.
            # Heuristic: a proper noun phrase is one where every significant word is
            # capitalised — e.g. "Pierre Curie", "Nobel Prize in Physics", "Polonium".
            # Small function words (in, of, the, a, an, and, de, van, …) are ignored.
            if obj and ":" not in obj and not obj.startswith("<"):
                obj = _maybe_entity_iri(obj)
            # Citation grounding: reject fabricated excerpts.
            # rapidfuzz.partial_ratio finds the best-matching same-length window
            # in the source text, tolerating minor LLM reformatting (decimal
            # spacing, stripped markdown, em-dash variants) while still catching
            # hallucinated excerpts that share no real overlap with the source.
            if not excerpt or not excerpt.strip():
                # LLM omitted the excerpt entirely — cannot ground this triple.
                triples_citation_rejected += 1
                logger.warning(
                    "Rejecting triple — no excerpt provided: %s %s %s",
                    subj, pred, obj,
                )
                continue
            sim = _fuzz.partial_ratio(excerpt, text)
            # round() so the comparison matches what %.0f displays: a score
            # of 77.6 displays as "78%" and should compare as 78, not 77.6.
            if round(sim) < _CITATION_SIMILARITY_THRESHOLD:
                triples_citation_rejected += 1
                logger.warning(
                    "Rejecting triple — excerpt similarity %.0f%% < %d%%: "
                    "%s %s %s | excerpt: %r",
                    sim,
                    _CITATION_SIMILARITY_THRESHOLD,
                    subj,
                    pred,
                    obj,
                    excerpt[:80],
                )
                continue
            logger.debug(
                "Citation OK %.0f%%: %s %s %s | excerpt: %r",
                sim,
                subj,
                pred,
                obj,
                excerpt[:60],
            )
            try:
                # Coerce degenerate offsets: the LLM sometimes returns char_end=0
                # (or char_end <= char_start) when it doesn't know the position.
                # Use excerpt length as a best-effort span rather than discarding
                # an otherwise valid triple solely for missing position metadata.
                if ce <= cs:
                    ce = cs + max(1, len(excerpt))
                evidence = EvidenceSpan(
                    source_iri=source_iri,
                    char_start=cs,
                    char_end=ce,
                    excerpt=excerpt,
                    page_number=page_number,
                )
                validated.append(
                    ExtractedTriple(
                        subject=subj,
                        predicate=pred,
                        object_value=obj,
                        confidence=conf,
                        evidence=evidence,
                    )
                )
                logger.debug(
                    "Triple accepted (conf=%.2f): %s %s %s",
                    conf,
                    subj,
                    pred,
                    obj,
                )
            except Exception as exc:  # noqa: BLE001
                triples_invalid += 1
                logger.warning("Skipping invalid triple (%s %s %s): %s", subj, pred, obj, exc)

        usage = completion.usage if completion else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        span.set_attribute("extraction.triples_extracted", triples_extracted)
        span.set_attribute("extraction.triples_citation_rejected", triples_citation_rejected)
        span.set_attribute("extraction.triples_invalid", triples_invalid)
        span.set_attribute("extraction.triple_count", len(validated))
        span.set_attribute("extraction.prompt_tokens", prompt_tokens)
        span.set_attribute("extraction.completion_tokens", completion_tokens)
        span.set_attribute("extraction.model", model_name)
        span.set_attribute("extraction.triples_capped", triples_capped)

        logger.info(
            "Extraction complete: %d extracted → %d passed citation "
            "(%d citation-rejected, %d capped, %d invalid)",
            triples_extracted,
            len(validated),
            triples_citation_rejected,
            triples_capped,
            triples_invalid,
        )

        return ExtractionResult(
            triples=validated,
            diagnostics={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "model": model_name,
                "llm_calls": 1,
                "triples_capped": triples_capped,
                "triples_extracted": triples_extracted,
                "triples_citation_rejected": triples_citation_rejected,
                "triples_invalid": triples_invalid,
            },
        )

    def _extract_batch_with_llm(
        self,
        fragments: list[object],
        profile: object,
        span: Any,
    ) -> dict[str, ExtractionResult]:
        """Extract triples from multiple fragments in one LLM call.

        Combines fragment texts with separators, sends to LLM, then parses
        and maps results back to original fragments.
        """
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "instructor and openai are required for batching. "
                "Install with: pip install 'riverbank[ingest]'"
            ) from exc

        from pydantic import BaseModel, Field  # noqa: PLC0415

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415

            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434/v1")

        if provider == "ollama" and api_base and not api_base.endswith("/v1"):
            api_base = api_base.rstrip("/") + "/v1"

        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(
            llm,
            "model",
            getattr(profile, "model_name", "llama3.2"),
        )
        prompt_text: str = getattr(profile, "prompt_text", _DEFAULT_PROMPT)
        extraction_strategy: dict = getattr(profile, "extraction_strategy", {})

        prompt_text = _build_permissive_prompt(prompt_text, extraction_strategy)

        # Combine fragments with clear separators
        combined_text = "\n\n---\n\n".join(
            f"[Fragment {i}]\n{getattr(f, 'text', '')}"
            for i, f in enumerate(fragments)
        )

        # Batch extraction schema — NOTE: fragment_id must be included by LLM
        # If LLM fails to include it, we fall back to per-fragment extraction
        class _BatchTriple(BaseModel):
            fragment_id: int = Field(default=-1, description="Index of the fragment (0-based)")
            subject: str
            predicate: str
            object_value: str
            confidence: float
            evidence: dict = Field(default_factory=dict)

        class _BatchExtractionResult(BaseModel):
            triples: list[_BatchTriple] = Field(description="List of extracted triples")

        client = instructor.patch(
            OpenAI(
                api_key=api_key,
                base_url=api_base,
            )
        )

        try:
            response = client.chat.completions.create(
                model=model_name,
                temperature=0,
                messages=[
                    {"role": "system", "content": prompt_text},
                    {
                        "role": "user",
                        "content": f"Extract triples from these fragments:\n\n{combined_text}",
                    },
                ],
                response_model=_BatchExtractionResult,
            )
        except Exception as exc:
            logger.warning("Batch extraction LLM call failed: %s", exc)
            # Return empty results — batch mode not supported in v0.15.1
            return {
                getattr(f, "fragment_key", str(i)): ExtractionResult(
                    triples=[],
                    diagnostics={"error": "batch_extraction_not_supported"},
                )
                for i, f in enumerate(fragments)
            }

        # Group triples by fragment
        results: dict[str, ExtractionResult] = {}
        triple_counts: dict[int, int] = {}
        total_triples = 0

        for triple in response.triples:
            frag_idx = triple.fragment_id
            
            # If LLM didn't include fragment_id, infer it from evidence/excerpt
            if frag_idx < 0:
                excerpt = triple.evidence.get("excerpt", "")
                if excerpt:
                    # Find which fragment contains this excerpt
                    for i, frag in enumerate(fragments):
                        frag_text = getattr(frag, "text", "")
                        if excerpt in frag_text:
                            frag_idx = i
                            break
                
                # If still not found, try fuzzy matching on excerpt
                if frag_idx < 0 and excerpt:
                    best_match_idx = 0
                    best_match_score = 0
                    for i, frag in enumerate(fragments):
                        frag_text = getattr(frag, "text", "")
                        score = _fuzz.partial_ratio(excerpt, frag_text)
                        if score > best_match_score:
                            best_match_score = score
                            best_match_idx = i
                    if best_match_score >= 50:  # Reasonable confidence threshold
                        frag_idx = best_match_idx
                
                # Final fallback: assume first fragment
                if frag_idx < 0:
                    frag_idx = 0
            
            if frag_idx < 0 or frag_idx >= len(fragments):
                logger.warning("Batch extraction: could not determine fragment for triple: %s", triple)
                continue

            fragment = fragments[frag_idx]
            frag_key = getattr(fragment, "fragment_key", str(frag_idx))
            source_iri = getattr(fragment, "source_iri", "")
            text = getattr(fragment, "text", "")

            # Validate triple
            subj, pred, obj = triple.subject, triple.predicate, triple.object_value
            conf = triple.confidence

            # Auto-expand bare predicates/subjects
            if pred and ":" not in pred and not pred.startswith("<"):
                pred = f"ex:{pred}"
            if subj and ":" not in subj and not subj.startswith("<"):
                subj = f"ex:{subj}"

            # Citation grounding check
            excerpt = triple.evidence.get("excerpt", "")
            if excerpt and round(_fuzz.partial_ratio(excerpt, text)) < _CITATION_SIMILARITY_THRESHOLD:
                logger.warning(
                    "Batch extraction: rejecting triple — similarity too low: %r",
                    excerpt[:80],
                )
                continue

            try:
                cs = triple.evidence.get("char_start", 0)
                ce = triple.evidence.get("char_end", 0)
                if ce <= cs:
                    ce = cs + max(1, len(excerpt))
                evidence = EvidenceSpan(
                    source_iri=source_iri,
                    char_start=cs,
                    char_end=ce,
                    excerpt=excerpt,
                    page_number=triple.evidence.get("page_number"),
                )
                et = ExtractedTriple(
                    subject=subj,
                    predicate=pred,
                    object_value=obj,
                    confidence=conf,
                    evidence=[evidence],
                )
                if frag_key not in results:
                    results[frag_key] = ExtractionResult(triples=[])
                results[frag_key].triples.append(et)
                triple_counts[frag_idx] = triple_counts.get(frag_idx, 0) + 1
                total_triples += 1
            except Exception as e:
                logger.warning("Batch extraction: error creating triple: %s", e)
                continue

        # Ensure all fragments have results
        for i, fragment in enumerate(fragments):
            frag_key = getattr(fragment, "fragment_key", str(i))
            if frag_key not in results:
                results[frag_key] = ExtractionResult(triples=[])

        span.set_attribute("batch.fragment_count", len(fragments))
        span.set_attribute("batch.total_triples", total_triples)
        span.set_attribute("batch.model", model_name)

        # Aggregate diagnostics
        for frag_key in results:
            results[frag_key].diagnostics = {
                "batch_mode": True,
                "batch_size": len(fragments),
                "model": model_name,
                "llm_calls": 1,
            }

        return results
