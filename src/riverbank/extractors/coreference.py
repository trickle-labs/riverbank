"""Coreference resolution preprocessing pass (v0.12.0).

Runs before fragmentation to replace pronouns and anaphoric references with
their resolved entity names, preventing phantom entities like ``ex:_it`` from
entering the knowledge graph.

Two resolution modes:

* ``llm`` — single LLM call per document.  Asks the model to replace all
  pronouns and anaphoric references with the entity they refer to and return
  the full resolved text.  Only high-confidence resolutions applied.
* ``spacy`` — uses spaCy ``coreferee`` or ``neuralcoref`` (if installed).
  Falls back to identity (no change) if neither is available.
* ``disabled`` (default) — returns the text unchanged.

Configuration (inside the ``preprocessing`` block of a compiler profile)::

    preprocessing:
      enabled: true
      coreference: llm          # llm | spacy | disabled

Usage::

    resolver = CoreferenceResolver(settings)
    resolved_text = resolver.resolve(text, profile)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_COREF_PROMPT = """\
Replace all pronouns and anaphoric references in the following text with the \
entity they refer to. Return the full resolved text only — do not add \
explanations, only change pronouns and anaphoric references that you are \
CONFIDENT about. Leave ambiguous references unchanged.

Text:
{text}
"""


class CoreferenceResolver:
    """Resolve coreferences in a document text before fragmentation.

    Parameters
    ----------
    settings:
        riverbank ``Settings`` object (used to access the LLM configuration
        when the ``llm`` mode is selected).
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    def resolve(self, text: str, profile: Any) -> str:
        """Return coreference-resolved text.

        Reads ``preprocessing.coreference`` from the profile dict.
        Silently returns the original text on any error so that coreference
        resolution never blocks the pipeline.
        """
        preprocessing_cfg: dict = getattr(profile, "preprocessing", {})
        mode: str = preprocessing_cfg.get("coreference", "disabled")

        if mode == "disabled" or not mode:
            return text

        try:
            if mode == "llm":
                return self._resolve_llm(text, profile)
            elif mode == "spacy":
                return self._resolve_spacy(text)
            else:
                logger.warning("Unknown coreference mode %r — skipping", mode)
                return text
        except Exception as exc:  # noqa: BLE001
            logger.debug("Coreference resolution failed (%s): %s", mode, exc)
            return text

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_llm(self, text: str, profile: Any) -> str:
        """Send a single LLM call to replace pronouns with entity names."""
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError:
            logger.debug("openai not installed — coreference resolution skipped")
            return text

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415
            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434/v1")
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(llm, "model", getattr(profile, "model_name", "llama3.2"))

        client = OpenAI(base_url=api_base, api_key=api_key)
        prompt = _COREF_PROMPT.format(text=text)

        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=len(text.split()) * 2 + 200,  # generous budget
            **({"extra_body": {"keep_alive": "5m"}} if provider == "ollama" else {}),
        )
        resolved = response.choices[0].message.content
        if resolved and resolved.strip():
            return resolved.strip()
        return text

    def _resolve_spacy(self, text: str) -> str:
        """Use spaCy + coreferee for pronoun coreference resolution.

        Prefers the larger ``en_core_web_lg`` model for higher accuracy
        (coreferee accuracy: lg > md > sm).  Falls back gracefully when
        spaCy, coreferee, or any English model is unavailable.
        """
        try:
            import spacy  # noqa: PLC0415
        except ImportError:
            logger.debug("spaCy not installed — coreference resolution skipped")
            return text

        try:
            import coreferee  # noqa: PLC0415, F401
        except ImportError:
            logger.debug("coreferee not installed — coreference resolution skipped")
            return text

        # Prefer larger models; coreferee accuracy scales with model size
        nlp = None
        for model_candidate in ("en_core_web_lg", "en_core_web_md", "en_core_web_sm"):
            try:
                nlp = spacy.load(model_candidate)
                break
            except OSError:
                continue

        if nlp is None:
            logger.debug("No spaCy English model found — coreference resolution skipped")
            return text

        try:
            if "coreferee" not in nlp.pipe_names:
                nlp.add_pipe("coreferee")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not add coreferee pipe: %s", exc)
            return text

        try:
            doc = nlp(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("spaCy processing failed: %s", exc)
            return text

        tokens: list[str] = []
        for token in doc:
            # Only replace pronouns — resolve anaphors to their most specific mention
            if token.pos_ == "PRON":
                resolved = doc._.coref_chains.resolve(token)
                if resolved:
                    # Join all tokens in the resolved mention, e.g. ["Marie", "Curie"]
                    resolved_text = " ".join(t.text for t in resolved)
                    tokens.append(resolved_text + token.whitespace_)
                    continue
            tokens.append(token.text_with_ws)
        return "".join(tokens)
