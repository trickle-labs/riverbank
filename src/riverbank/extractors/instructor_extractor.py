from __future__ import annotations

import logging
from typing import Any, ClassVar, Optional

from opentelemetry import trace as otel_trace

from riverbank.extractors.noop import ExtractionResult
from riverbank.prov import EvidenceSpan, ExtractedTriple

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = """\
You are a knowledge graph compiler.  Extract factual claims from the following
technical document section as RDF triples.

For each claim provide:
- subject: IRI or prefixed name (e.g. ex:EntityName)
- predicate: IRI or prefixed name (e.g. ex:hasProperty)
- object_value: IRI, prefixed name, or literal value
- confidence: float 0.0–1.0 reflecting how clearly the text supports the claim
- evidence: exact character offsets (char_start, char_end) and a verbatim
  excerpt copied from the source text

Only extract claims directly supported by the text.
Do NOT fabricate evidence — the excerpt must appear verbatim in the source.
"""


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
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(
            llm,
            "model",
            getattr(profile, "model_name", "llama3.2"),
        )
        prompt_text: str = getattr(profile, "prompt_text", _DEFAULT_PROMPT)

        source_iri: str = getattr(fragment, "source_iri", "")
        text: str = getattr(fragment, "text", "")

        # --- define Pydantic schemas local to this call ---

        class _EvidenceSpanIn(BaseModel):
            char_start: int
            char_end: int
            excerpt: str
            page_number: Optional[int] = None

        class _TripleIn(BaseModel):
            subject: str
            predicate: str
            object_value: str
            confidence: float
            evidence: _EvidenceSpanIn

        # --- build provider-specific instructor client ---
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
            # Available models: gpt-4o, gpt-4o-mini, claude-3.5-sonnet, etc.
            # https://github.com/marketplace/models
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
            # Use MD_JSON for local models (ollama/vllm), JSON_SCHEMA for hosted
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

        response, completion = client.chat.completions.create_with_completion(
            model=model_name,
            messages=[
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": text},
            ],
            response_model=list[_TripleIn],
            **mode_kwargs,
        )

        # --- validate and filter triples ---
        validated: list[ExtractedTriple] = []
        for t in response:
            ev = t.evidence
            # Citation grounding: reject fabricated excerpts
            if ev.excerpt and ev.excerpt not in text:
                logger.warning(
                    "Rejecting triple — excerpt not found in source text: %r",
                    ev.excerpt[:80],
                )
                continue
            try:
                evidence = EvidenceSpan(
                    source_iri=source_iri,
                    char_start=ev.char_start,
                    char_end=ev.char_end,
                    excerpt=ev.excerpt,
                    page_number=ev.page_number,
                )
                validated.append(
                    ExtractedTriple(
                        subject=t.subject,
                        predicate=t.predicate,
                        object_value=t.object_value,
                        confidence=t.confidence,
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

        return ExtractionResult(
            triples=validated,
            diagnostics={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "model": model_name,
                "llm_calls": 1,
            },
        )
