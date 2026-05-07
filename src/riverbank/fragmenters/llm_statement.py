"""LLM-driven statement fragmenter (v0.16.0).

**Approach:** Send the full document to the LLM once and ask it to split the
text into atomic, self-contained factual statements.  Each statement becomes a
``DocumentFragment`` that is independently extractable and hash-cacheable.

**Why this works better than heading-based splitting for some documents:**
- Works for documents with no headings (prose, reports, articles)
- The LLM decides what is semantically atomic, not structural markers
- Statements tend to map cleanly to individual triples

**Cost:** One LLM call per document (same amortisation as preprocessing).
Incremental compilation is preserved: each statement has a stable
``fragment_key = f"stmt_{idx}"`` and a content hash, so unchanged statements
are skipped on re-ingest.

**Fallback:** Falls back to HeadingFragmenter when the LLM call fails or when
``instructor``/``openai`` are not installed. This ensures that even without
a working LLM, documents are still fragmentable and processable.

Profile YAML::

    fragmenter: llm_statement
    llm_statement_fragmentation:
      max_statements: 200       # hard cap on statements returned
      max_doc_chars: 20000      # truncate docs longer than this before sending
      # prompt: |               # optional custom system prompt override
      #   Split the document ...

Entry point::

    riverbank.fragmenters = llm_statement = riverbank.fragmenters.llm_statement:LLMStatementFragmenter
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar, Iterator

import xxhash

from riverbank.fragmenters.heading import DocumentFragment

logger = logging.getLogger(__name__)

_DEFAULT_MAX_STATEMENTS = 200
_DEFAULT_MAX_DOC_CHARS = 20000

_DEFAULT_SYSTEM_PROMPT = """\
You are a document analysis assistant. Split the following document into \
atomic, self-contained factual statements. Each statement should:
- Express a single fact, claim, or assertion
- Be understandable without needing to read surrounding statements
- Be verbatim or lightly paraphrased from the source text

Return a JSON object with a single key "statements" containing an array of \
statement strings. Do not include empty or duplicate statements.\
"""

_ESSENTIAL_SYSTEM_PROMPT = """\
Extract ONLY the bare essential facts from this document. Include only:
- WHO the person/entity is (profession, nationality, core identity)
- WHAT they discovered/invented/accomplished (major contributions)
- WHERE/WHEN only if essential to understanding

Exclude:
- Family details unless critical to core identity
- Education unless it led to discoveries
- Specific dates unless the achievement is unknown without it
- Secondary/contextual information
- Death or end of service (not core achievement)

Return a JSON object with a single key "statements" containing a minimal list \
of essential facts. Each should be 1-2 sentences maximum.\
"""

_MINIMAL_SYSTEM_PROMPT = """\
Extract ONLY what the entity achieved, discovered, or accomplished.
Ignore all biographical details, dates, family, education, death.
Focus ONLY on: discoveries, inventions, awards, institutions founded, \
scientific contributions, or other major achievements.

Return a JSON object with a single key "statements" containing the achievements \
and discoveries. One achievement per statement.\
"""

_DISTILLATION_LEVELS = {
    "default": _DEFAULT_SYSTEM_PROMPT,
    "essential": _ESSENTIAL_SYSTEM_PROMPT,
    "minimal": _MINIMAL_SYSTEM_PROMPT,
}


def _make_fragment(idx: int, source_iri: str, text: str) -> DocumentFragment:
    content_hash = xxhash.xxh3_128(text.encode()).digest()
    fragment_key = f"stmt_{idx}"
    return DocumentFragment(
        fragment_key=fragment_key,
        source_iri=source_iri,
        content_hash=content_hash,
        heading_path=[fragment_key],
        text=text,
        char_start=0,
        char_end=len(text),
        heading_depth=0,
    )


class LLMStatementFragmenter:
    """Fragment a document into LLM-identified atomic statements.

    Sends the full document text to the LLM in a single call, asking it to
    decompose the document into atomic, self-contained factual statements.
    Each statement becomes a ``DocumentFragment``.

    Falls back to a single ``root`` fragment when:
    - ``instructor`` or ``openai`` are not installed
    - The LLM call fails
    - The document is empty

    Args:
        settings: riverbank settings object (passed from the pipeline).
        max_statements: Hard cap on the number of statements returned.
        max_doc_chars: Documents longer than this are truncated before sending.
        system_prompt: Custom system prompt override.
        distillation_level: Preset level ("default", "essential", "minimal").
            Ignored if system_prompt is provided.
    """

    name: ClassVar[str] = "llm_statement"

    def __init__(
        self,
        settings: Any = None,
        max_statements: int = _DEFAULT_MAX_STATEMENTS,
        max_doc_chars: int = _DEFAULT_MAX_DOC_CHARS,
        system_prompt: str | None = None,
        distillation_level: str = "default",
    ) -> None:
        self._settings = settings
        self._max_statements = max_statements
        self._max_doc_chars = max_doc_chars
        
        # Use custom prompt if provided, otherwise use distillation level
        if system_prompt:
            self._system_prompt = system_prompt
        else:
            self._system_prompt = _DISTILLATION_LEVELS.get(
                distillation_level, _DEFAULT_SYSTEM_PROMPT
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(cls, profile: Any, settings: Any = None) -> "LLMStatementFragmenter":
        """Construct from a ``CompilerProfile``."""
        cfg: dict = getattr(profile, "llm_statement_fragmentation", {}) or {}
        return cls(
            settings=settings,
            max_statements=int(cfg.get("max_statements", _DEFAULT_MAX_STATEMENTS)),
            max_doc_chars=int(cfg.get("max_doc_chars", _DEFAULT_MAX_DOC_CHARS)),
            system_prompt=cfg.get("prompt"),
            distillation_level=cfg.get("distillation_level", "default"),
        )

    def fragment(self, doc: object, **_kwargs: Any) -> Iterator[DocumentFragment]:
        """Yield one ``DocumentFragment`` per LLM-identified statement.

        Sends the full document text to the LLM and parses the returned list
        of statements.  Falls back to HeadingFragmenter when the LLM call fails
        or returns no statements.
        """
        source_iri: str = getattr(doc, "source_iri", "")
        raw_text: str = getattr(doc, "raw_text", "")

        if not raw_text.strip():
            return

        statements = self._call_llm(raw_text)
        if not statements:
            logger.debug(
                "LLMStatementFragmenter: LLM call failed for %s — "
                "falling back to HeadingFragmenter",
                source_iri,
            )
            from riverbank.fragmenters.heading import HeadingFragmenter  # noqa: PLC0415

            fallback = HeadingFragmenter()
            yield from fallback.fragment(doc)
            return

        logger.debug(
            "LLMStatementFragmenter: %d statements from %s",
            len(statements),
            source_iri,
        )
        for idx, stmt in enumerate(statements[: self._max_statements]):
            if stmt.strip():
                yield _make_fragment(idx, source_iri, stmt.strip())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(self, raw_text: str) -> list[str] | None:
        """Call the LLM to split *raw_text* into statements.

        Returns a list of statement strings, or ``None`` on failure.
        """
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
            from pydantic import BaseModel  # noqa: PLC0415
        except ImportError:
            logger.debug(
                "LLMStatementFragmenter: instructor/openai/pydantic not available"
            )
            return None

        class _StatementsOut(BaseModel):
            statements: list[str]

        try:
            client, model_name, provider = self._get_llm_client()
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLMStatementFragmenter: could not build LLM client: %s", exc)
            return None

        doc_text = raw_text[: self._max_doc_chars]

        try:
            extra_kwargs: dict = (
                {"extra_body": {"keep_alive": "5m"}} if provider == "ollama" else {}
            )
            result = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": doc_text},
                ],
                response_model=_StatementsOut,
                **extra_kwargs,
            )
            return result.statements
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLMStatementFragmenter: LLM call failed: %s", str(exc)[:200]
            )
            return None

    def _get_llm_client(self) -> tuple[Any, str, str]:
        """Return an ``(instructor_client, model_name, provider)`` triple."""
        import instructor  # noqa: PLC0415
        from openai import OpenAI  # noqa: PLC0415

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415

            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434")
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(llm, "model", "llama3.2")

        # Ensure api_base has /v1 for OpenAI-compatible endpoints (Ollama, etc.)
        if provider in ("ollama", "vllm") and not api_base.endswith("/v1"):
            api_base = api_base.rstrip("/") + "/v1"

        if provider == "copilot":
            mode = instructor.Mode.JSON
            client = instructor.from_openai(
                OpenAI(
                    base_url="https://models.inference.ai.azure.com",
                    api_key=api_key,
                ),
                mode=mode,
            )
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

        return client, model_name, provider
