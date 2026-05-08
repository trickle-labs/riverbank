from __future__ import annotations

import logging
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
# rejecting outright fabrications.  82 gives ~1 character tolerance per 6 chars,
# which handles paraphrased but accurate evidence without accepting hallucinations.
_CITATION_SIMILARITY_THRESHOLD: int = 82


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
   (e.g. "1.0", "active", "metric tonnes")
4. **confidence**: float 0.0–1.0 reflecting how clearly the text supports the claim
5. **evidence**: exact character offsets (char_start, char_end) and verbatim excerpt

## Critical Constraints
- Only extract claims directly supported by the text.
- Do NOT fabricate evidence — the excerpt MUST appear verbatim in the source.
- Always return a JSON array, even if empty: []
- SAFETY: If a subject or object_value is a pronoun (She, He, They, It, Who, Her, His, etc.), SKIP that triple entirely.
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

_CQ_OBJECTIVES_PREFIX = "EXTRACTION OBJECTIVES (derived from competency questions):\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_permissive_prompt(base_prompt: str, extraction_strategy: dict) -> str:
    """Inject permissive-mode tiered guidance into the base prompt."""
    if extraction_strategy.get("mode") == "permissive":
        return f"{_PERMISSIVE_TIER_GUIDANCE}\n\n{base_prompt}"
    return base_prompt


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
        if provider == "ollama":
            ollama_extra: dict = {"keep_alive": "5m"}
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
        max_triples: int = extraction_strategy.get("max_triples_per_fragment", 0)
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
            # Citation grounding: reject fabricated excerpts.
            # rapidfuzz.partial_ratio finds the best-matching same-length window
            # in the source text, tolerating minor LLM reformatting (decimal
            # spacing, stripped markdown, em-dash variants) while still catching
            # hallucinated excerpts that share no real overlap with the source.
            if excerpt and _fuzz.partial_ratio(excerpt, text) < _CITATION_SIMILARITY_THRESHOLD:
                logger.warning(
                    "Rejecting triple — excerpt similarity %.0f%% < %d%% threshold: %r",
                    _fuzz.partial_ratio(excerpt, text),
                    _CITATION_SIMILARITY_THRESHOLD,
                    excerpt[:80],
                )
                continue
            try:
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping invalid triple: %s", exc)

        usage = completion.usage if completion else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        span.set_attribute("extraction.triple_count", len(validated))
        span.set_attribute("extraction.prompt_tokens", prompt_tokens)
        span.set_attribute("extraction.completion_tokens", completion_tokens)
        span.set_attribute("extraction.model", model_name)
        span.set_attribute("extraction.triples_capped", triples_capped)

        return ExtractionResult(
            triples=validated,
            diagnostics={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "model": model_name,
                "llm_calls": 1,
                "triples_capped": triples_capped,
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
            if excerpt and _fuzz.partial_ratio(excerpt, text) < _CITATION_SIMILARITY_THRESHOLD:
                logger.warning(
                    "Batch extraction: rejecting triple — similarity too low: %r",
                    excerpt[:80],
                )
                continue

            try:
                evidence = EvidenceSpan(
                    source_iri=source_iri,
                    char_start=triple.evidence.get("char_start", 0),
                    char_end=triple.evidence.get("char_end", 0),
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
