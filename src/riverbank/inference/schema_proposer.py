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
      confidence_threshold: "high"  # Filter by confidence: high|medium|all
      seed_predicates: []  # Optional: constrain to namespace
      use_for_extraction: true  # Merge proposed predicates into allowed_predicates
      max_predicates: 50

CLI (future)::

    riverbank infer-schema --doc article.md --profile docs-policy-v1 \\
      --output predicates.yaml
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class SchemaProposer:
    """Propose RDF predicates and classes for a document using an LLM."""

    _INFERENCE_PROMPT = """\
You are an RDF schema designer. Analyze this document and propose domain-specific
RDF predicates and classes for extracting facts as triples.

CONSTRAINTS:
- Propose 20–50 predicates (reusable across similar documents, not one-off facts)
- Use prefixed IRIs: ex:predicate_name (lowercase, underscores, descriptive)
- Avoid generic predicates: ex:hasProperty, ex:relatedTo, ex:hasValue
- Avoid document-specific predicates: ex:mentioned_in_section_2
- Each predicate should appear in 2+ triples in this document
- Group predicates by semantic category (Identity, Temporal, Relationship, etc.)

RESPONSE FORMAT:
Output valid YAML with this structure:

predicates:
  - name: ex:predicate_name
    category: Identity|Temporal|Attribute|Relationship|Achievement|Role
    domain: subject type (e.g., Person, Organization, Event)
    range: object type (e.g., Literal, Date, IRI)
    confidence: high|medium|exploratory
    rationale: brief explanation (1-2 sentences)

ANALYSIS STEPS:
1. Identify primary entity types (person, org, event, thing, etc.)
2. List key attributes and relationships
3. Group by semantic category
4. Propose predicates with rationale
5. Flag exploratory predicates (lower confidence)

Focus on relationships and attributes, not narrative or background.
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
        client = OpenAI(
            base_url=api_base,
            api_key=api_key,
        )

        logger.info(
            "Proposing predicates for document (%d chars) using %s",
            len(document_text),
            model_name,
        )

        try:
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

            # Parse YAML from the response
            try:
                # Strip markdown code fences if present
                import re  # noqa: PLC0415
                content_stripped = content.strip()
                if content_stripped.startswith("```"):
                    # Handle markdown code blocks: ```yaml ... ``` or just ``` ... ```
                    match = re.search(r"```(?:yaml|yml)?\s*\n?([\s\S]*?)\n?```", content_stripped)
                    if match:
                        content_stripped = match.group(1).strip()
                
                parsed = yaml.safe_load(content_stripped)
            except yaml.YAMLError as yaml_err:
                logger.warning(
                    "Failed to parse predicate inference YAML response: %s",
                    yaml_err,
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
                            # Filter by confidence
                            if confidence_threshold == "all" or (
                                confidence_threshold == "high" and conf == "high"
                            ) or (
                                confidence_threshold in ("high", "medium")
                                and conf in ("high", "medium")
                            ):
                                predicates.append(name)
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

            diagnostics = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "model": model_name,
                "predicates_proposed": len(predicates),
            }

            result = {
                "allowed_predicates": predicates,
                "allowed_classes": classes,
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
