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
        """Use spaCy coreferee/neuralcoref for coreference resolution."""
        try:
            import spacy  # noqa: PLC0415
            nlp = spacy.load("en_core_web_sm")
            # Try coreferee first
            try:
                import coreferee  # noqa: PLC0415, F401
                nlp.add_pipe("coreferee")
                doc = nlp(text)
                resolved_tokens: list[str] = []
                for token in doc:
                    coref = doc._.coref_chains.resolve(token)
                    if coref:
                        resolved_tokens.append(coref[0].text)
                    else:
                        resolved_tokens.append(token.text_with_ws)
                return "".join(resolved_tokens)
            except (ImportError, Exception):
                pass
            # Fall through if coreferee unavailable
        except ImportError:
            pass
        logger.debug("spaCy coreference libraries not available — resolution skipped")
        return text
