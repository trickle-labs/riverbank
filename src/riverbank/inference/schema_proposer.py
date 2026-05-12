"""Predicate inference — LLM-driven RDF schema discovery (v0.18.0).

**Problem:** When ingesting documents from new domains, it's hard to know
upfront which RDF predicates are actually relevant. Manual schema design
requires domain expertise; constraints that are too strict miss facts,
too permissive create noise.

**Solution:** Run a lightweight LLM pass before extraction to *propose*
domain-appropriate predicates from the document text. The proposer analyzes
the document and suggests a vocabulary, which can be reviewed and then used
to constrain the main extraction pass.

**Profile YAML**::

    predicate_inference:
      enabled: true
      confidence_threshold: "medium"  # Confidence levels: all|high|medium|low
      seed_predicates: []  # Optional: constrain to namespace
      use_for_extraction: true  # Merge proposed predicates into allowed_predicates
      max_predicates: 50

Confidence thresholds (per LLM proposal confidence levels: high, medium, exploratory)::

    "all"     → Accept all proposals (high + medium + exploratory)
    "high"    → Accept only high confidence proposals (strictest)
    "medium"  → Accept high and medium confidence (recommended)
    "low"     → Accept all proposals: high + medium + exploratory (same as "all")

CLI (future)::

    riverbank infer-schema --doc article.md --profile docs-policy-v1 \\
      --output predicates.yaml
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SchemaProposer:
    """Propose RDF predicates and classes for a document using an LLM."""

    _INFERENCE_PROMPT = """\
You are an RDF schema designer. Output ONLY valid JSON with NO explanation.

TASK: Analyze this document and propose 3-5 domain-specific RDF predicates.

JSON OUTPUT RULES:
- Use DOUBLE QUOTES for all strings
- NO single quotes, NO trailing commas
- NO newlines inside strings (replace with single space)
- NO unescaped backslashes in strings
- NO special characters except ., :, -, _
- Output ONLY the JSON object, nothing else

RESPONSE (valid JSON only):

{
  "predicates": [
    {
      "name": "ex:founded",
      "category": "Temporal",
      "domain": "Organization",
      "range": "Literal",
      "confidence": "high",
      "rationale": "Document mentions when organization was founded."
    }
  ]
}

CONSTRAINTS:
- Propose only predicates that appear 2+ times in the document
- Use lowercase names: ex:predicate_name
- For category use: Temporal, Relationship, Attribute, Achievement, or Role
- For confidence use: high, medium, or exploratory (lowercase)
- For rationale: max 60 characters, one sentence, NO quotes or newlines

ACTION: Output ONLY JSON starting with { and ending with }.
"""

    def __init__(self, settings: Any = None) -> None:
        """Initialize the schema proposer with optional settings override."""
        self._settings = settings

    def propose(
        self,
        document_text: str,
        profile: Any,
    ) -> dict[str, Any]:
        """Propose predicates for a document using the configured LLM.

        Args:
            document_text: Full document text to analyze
            profile: CompilerProfile instance

        Returns:
            Dict with keys:
            - 'allowed_predicates': list of proposed predicate IRIs
            - 'allowed_classes': list of proposed class IRIs (if extraction_focus includes class inference)
            - 'diagnostics': dict with 'prompt_tokens', 'completion_tokens', 'model', etc.
            - 'raw_reasoning': full structured response from LLM (optional)
        """
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "openai is required for predicate inference. "
                "Install with: pip install 'riverbank[ingest]'"
            ) from exc

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

        # Prepare document summary or truncation if too long
        max_chars = 8000
        if len(document_text) > max_chars:
            # Take first N chars and add ellipsis
            doc_sample = document_text[:max_chars] + f"\n[...document truncated, original length: {len(document_text)} chars...]"
        else:
            doc_sample = document_text

        # Build the user message
        user_message = f"Analyze this document:\n\n{doc_sample}"

        # Create OpenAI-compatible client
        try:
            client = OpenAI(
                base_url=api_base,
                api_key=api_key,
            )

            logger.info(
                "Proposing predicates for document (%d chars) using %s",
                len(document_text),
                model_name,
            )

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": self._INFERENCE_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,  # Lower temp for more consistent schema proposals
                max_tokens=2000,
            )

            content = response.choices[0].message.content or ""
            usage = response.usage

            logger.debug("Predicate inference response: %s", content[:500])

            # Parse JSON from the response with aggressive error recovery
            parsed = {}
            try:
                # Strip markdown code fences if present
                import re  # noqa: PLC0415
                content_stripped = content.strip()
                
                # Try multiple patterns for markdown fences (json, code, or no fence)
                patterns = [
                    r"```(?:json)?\s*\n([\s\S]*?)\n```",  # With newlines
                    r"```(?:json)?\s*([\s\S]*?)\s*```",    # Without newlines
                    r"```([\s\S]*?)```",                    # Any fence
                ]
                
                match_found = False
                for pattern in patterns:
                    match = re.search(pattern, content_stripped)
                    if match:
                        content_stripped = match.group(1).strip()
                        match_found = True
                        break
                
                # If no regex match, try manual fallback: strip leading/trailing backticks
                if not match_found and content_stripped.startswith("```"):
                    # Manually strip code fences as last resort
                    lines = content_stripped.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    content_stripped = "\n".join(lines).strip()
                
                # First attempt: direct JSON parse
                try:
                    parsed = json.loads(content_stripped)
                except json.JSONDecodeError as e1:
                    # Second attempt: extract JSON object and repair common issues
                    json_match = re.search(r"\{[\s\S]*\}", content_stripped)
                    if json_match:
                        json_str = json_match.group(0)
                        try:
                            # Try parsing the extracted JSON
                            parsed = json.loads(json_str)
                        except json.JSONDecodeError:
                            # Third attempt: replace unescaped newlines with spaces
                            json_str = re.sub(r'([^\\])\n', r'\1 ', json_str)
                            try:
                                parsed = json.loads(json_str)
                            except json.JSONDecodeError as e2:
                                # Fourth attempt: try to salvage predicates using regex
                                logger.debug(
                                    "JSON parse failed twice: %s, %s. Attempting regex extraction.",
                                    e1, e2
                                )
                                # Extract individual predicate objects using regex
                                pred_pattern = r'"name"\s*:\s*"([^"]*)"[^}]*?"confidence"\s*:\s*"(high|medium|exploratory)"'
                                matches = re.findall(pred_pattern, content_stripped, re.DOTALL)
                                if matches:
                                    parsed = {
                                        "predicates": [
                                            {
                                                "name": name,
                                                "confidence": conf,
                                            }
                                            for name, conf in matches
                                        ]
                                    }
                                    logger.info(
                                        "Salvaged %d predicates from malformed JSON via regex",
                                        len(matches),
                                    )
                                else:
                                    raise
                    else:
                        raise
                        
            except (json.JSONDecodeError, ValueError) as json_err:
                logger.debug(
                    "Failed to parse predicate inference response: %s (predicate inference is optional, ingest continues)",
                    json_err,
                )
                parsed = {}

            # Extract predicates and confidence filtering
            predicates = []
            classes = []
            raw_reasoning = parsed

            if isinstance(parsed, dict) and "predicates" in parsed:
                pred_list = parsed["predicates"]
                if isinstance(pred_list, list):
                    confidence_threshold = (
                        getattr(profile, "predicate_inference", {}).get(
                            "confidence_threshold", "high"
                        )
                    )
                    for pred_item in pred_list:
                        if isinstance(pred_item, dict):
                            name = pred_item.get("name", "")
                            conf = pred_item.get("confidence", "medium")
                            # Filter by confidence threshold
                            if confidence_threshold == "all":
                                # Accept all confidence levels
                                predicates.append(name)
                            elif confidence_threshold == "high":
                                # Accept only high confidence
                                if conf == "high":
                                    predicates.append(name)
                            elif confidence_threshold == "medium":
                                # Accept high and medium confidence
                                if conf in ("high", "medium"):
                                    predicates.append(name)
                            elif confidence_threshold == "low":
                                # Accept high, medium, and exploratory (all levels)
                                if conf in ("high", "medium", "exploratory"):
                                    predicates.append(name)
                            if name in predicates:
                                logger.debug("Proposed predicate: %s (confidence=%s)", name, conf)

            # Optional: extract classes if present in response
            if isinstance(parsed, dict) and "classes" in parsed:
                class_list = parsed["classes"]
                if isinstance(class_list, list):
                    for class_item in class_list:
                        if isinstance(class_item, dict):
                            name = class_item.get("name", "")
                            classes.append(name)

            # Cap at max_predicates
            max_preds = getattr(profile, "predicate_inference", {}).get("max_predicates", 50)
            if len(predicates) > max_preds:
                logger.warning(
                    "Capping proposed predicates from %d to %d",
                    len(predicates),
                    max_preds,
                )
                predicates = predicates[:max_preds]

            # v0.15.4: Build suggested_predicates — the full proposal list with
            # confidence tiers, regardless of confidence_threshold filtering.
            # Used to inject PREDICATE HINTS into the extraction prompt when
            # use_for_extraction: false.
            suggested_predicates: dict[str, list[str]] = {
                "high": [],
                "medium": [],
                "exploratory": [],
            }
            if isinstance(parsed, dict) and "predicates" in parsed:
                for pred_item in parsed.get("predicates", []):
                    if isinstance(pred_item, dict):
                        name = pred_item.get("name", "").strip()
                        conf = pred_item.get("confidence", "medium")
                        if name and conf in suggested_predicates:
                            suggested_predicates[conf].append(name)

            diagnostics = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "model": model_name,
                "predicates_proposed": len(predicates),
            }

            result = {
                "allowed_predicates": predicates,
                "allowed_classes": classes,
                "suggested_predicates": suggested_predicates,
                "diagnostics": diagnostics,
                "raw_reasoning": raw_reasoning,
            }

            logger.info(
                "Predicate inference complete: %d predicates, %d classes proposed (tokens: %d+%d)",
                len(predicates),
                len(classes),
                usage.prompt_tokens,
                usage.completion_tokens,
            )

            return result

        except Exception as exc:  # noqa: BLE001
            logger.error("Predicate inference failed: %s", exc)
            return {
                "allowed_predicates": [],
                "allowed_classes": [],
                "suggested_predicates": {"high": [], "medium": [], "exploratory": []},
                "diagnostics": {"error": str(exc)},
                "raw_reasoning": {},
            }


def propose_predicates(
    document_text: str,
    profile: Any,
    settings: Any = None,
) -> dict[str, Any]:
    """Convenience function to propose predicates for a document.

    Args:
        document_text: Full document text
        profile: CompilerProfile instance
        settings: Optional settings override

    Returns:
        Dict with 'allowed_predicates', 'allowed_classes', 'diagnostics'
    """
    proposer = SchemaProposer(settings=settings)
    return proposer.propose(document_text, profile)
