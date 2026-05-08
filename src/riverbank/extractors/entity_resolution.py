"""Post-extraction entity resolution pass (v0.16.0).

After fragment-level extraction is complete for a document, this pass takes
all extracted entity IRIs and asks the LLM to identify which ones refer to
the same real-world entity (aliases, abbreviations, translated names, etc.).

Each confirmed equivalence is written as a pair of symmetric ``owl:sameAs``
triples in the trusted named graph, directly attacking the terminology drift
problem: different fragments may produce ``ex:MaryCurie`` and ``ex:MarieCurie``
for the same person.

The pass makes **one LLM call per document** (batched if there are many
entities) and is entirely opt-in via the profile.

Profile YAML::

    entity_resolution:
      enabled: true
      max_entities_per_call: 50    # batch size sent to the LLM at once
      confidence_threshold: 0.8    # minimum confidence to write owl:sameAs
      # prompt: |                  # optional custom system prompt

Usage in the pipeline: called by ``IngestPipeline._process_source`` after the
fragment loop, before cost accounting.
"""
from __future__ import annotations

import logging
from typing import Any

from riverbank.prov import EvidenceSpan, ExtractedTriple

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ENTITIES = 50
_DEFAULT_CONFIDENCE = 0.8

# Embedding-based entity resolution (backend="embeddings")
_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_DEFAULT_SIMILARITY_THRESHOLD = 0.92

_DEFAULT_PROMPT = """\
You are a knowledge graph curator. You are given a list of entity IRIs \
extracted from a document, followed by the document text.

Identify pairs of entity IRIs that refer to the SAME real-world entity \
(aliases, abbreviations, alternate spellings, translated names, etc.).

Rules:
- Only identify equivalences that are clearly supported by the document text.
- Do NOT hallucinate — only pair entities that are demonstrably the same thing.
- Skip pairs where the difference is purely IRI formatting (e.g. underscores \
  vs CamelCase) unless the underlying concepts are genuinely the same entity.

Return a JSON object with key "equivalences" containing an array of objects, \
each with:
  - entity_a: first IRI (exactly as given)
  - entity_b: second IRI (exactly as given)
  - confidence: float 0.0–1.0 reflecting certainty
  - reasoning: one sentence explaining why they are the same\
"""


class EntityResolutionPass:
    """Ask the LLM to merge entity aliases across the full document.

    Runs once per source document after fragment extraction is complete.
    Returns ``(triples, prompt_tokens, completion_tokens)`` where *triples*
    is a list of ``owl:sameAs`` ``ExtractedTriple`` objects.

    Falls back gracefully to ``([], 0, 0)`` when ``instructor`` / ``openai``
    are not installed or when the LLM call fails.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        raw_text: str,
        source_iri: str,
        subjects: list[str],
        profile: Any,
    ) -> tuple[list[ExtractedTriple], int, int]:
        """Run entity resolution and return ``(triples, prompt_tokens, completion_tokens)``.

        Deduplicates *subjects*, batches LLM calls when there are more than
        *max_entities_per_call* subjects, and returns all ``owl:sameAs``
        triples found.  Returns ``([], 0, 0)`` on any failure.
        """
        cfg: dict = getattr(profile, "entity_resolution", {}) or {}
        backend: str = cfg.get("backend", "llm")
        max_entities: int = int(cfg.get("max_entities_per_call", _DEFAULT_MAX_ENTITIES))
        confidence_threshold: float = float(cfg.get("confidence_threshold", _DEFAULT_CONFIDENCE))
        system_prompt: str = cfg.get("prompt") or _DEFAULT_PROMPT

        # Deduplicate and filter to IRI-like subjects only (must contain ":")
        seen: set[str] = set()
        unique: list[str] = []
        for s in subjects:
            if s and s not in seen and ":" in s:
                seen.add(s)
                unique.append(s)

        if not unique:
            return [], 0, 0

        # Embedding-based backend — no LLM call, uses cosine similarity
        if backend == "embeddings":
            similarity_threshold: float = float(
                cfg.get("similarity_threshold", _DEFAULT_SIMILARITY_THRESHOLD)
            )
            return self._run_embeddings_pass(
                source_iri, unique, profile, similarity_threshold
            )

        all_triples: list[ExtractedTriple] = []
        total_pt = 0
        total_ct = 0

        for batch_start in range(0, len(unique), max_entities):
            batch = unique[batch_start : batch_start + max_entities]
            triples, pt, ct = self._call_llm(
                raw_text, source_iri, batch, profile, system_prompt, confidence_threshold
            )
            all_triples.extend(triples)
            total_pt += pt
            total_ct += ct

        return all_triples, total_pt, total_ct

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_embeddings_pass(
        self,
        source_iri: str,
        subjects: list[str],
        profile: Any,
        similarity_threshold: float,
    ) -> tuple[list[ExtractedTriple], int, int]:
        """Find entity aliases using embedding cosine similarity (no LLM call).

        Embeds the human-readable label derived from each IRI using
        ``all-MiniLM-L6-v2`` and pairs entities whose cosine similarity
        exceeds *similarity_threshold*.

        Returns ``(triples, 0, 0)`` — token counts are zero (no LLM used).
        """
        import re  # noqa: PLC0415

        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "EntityResolutionPass: sentence-transformers not available "
                "— skipping embedding entity resolution"
            )
            return [], 0, 0

        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            logger.warning("EntityResolutionPass: numpy not available — skipping")
            return [], 0, 0

        def _iri_to_label(iri: str) -> str:
            """Convert an IRI local name to a human-readable embedding input."""
            local = iri.split(":")[-1] if ":" in iri else iri
            # Split CamelCase: "MarieCurie" → "Marie Curie"
            label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local)
            return label.replace("_", " ").replace("-", " ").strip().lower() or iri

        labels = [_iri_to_label(s) for s in subjects]

        try:
            model = SentenceTransformer(_EMBEDDING_MODEL_NAME)
            embeddings = model.encode(
                labels, normalize_embeddings=True, show_progress_bar=False
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("EntityResolutionPass: embedding failed: %s", exc)
            return [], 0, 0

        # Pairwise cosine similarity (L2-normalised → dot product == cosine)
        sim_matrix: Any = embeddings @ embeddings.T
        named_graph = getattr(profile, "named_graph", "<trusted>")
        triples: list[ExtractedTriple] = []

        for i in range(len(subjects)):
            for j in range(i + 1, len(subjects)):
                sim = float(sim_matrix[i, j])
                if sim < similarity_threshold or subjects[i] == subjects[j]:
                    continue
                excerpt = (
                    f"embedding similarity {sim:.3f}: "
                    f"{subjects[i]} \u2261 {subjects[j]}"
                )[:200]
                try:
                    evidence = EvidenceSpan(
                        source_iri=source_iri,
                        char_start=0,
                        char_end=1,
                        excerpt=excerpt,
                    )
                    for subj, obj in (
                        (subjects[i], subjects[j]),
                        (subjects[j], subjects[i]),
                    ):
                        triples.append(
                            ExtractedTriple(
                                subject=subj,
                                predicate="owl:sameAs",
                                object_value=obj,
                                confidence=sim,
                                evidence=evidence,
                                named_graph=named_graph,
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "EntityResolutionPass: could not build triple: %s", exc
                    )

        logger.debug(
            "EntityResolutionPass: embeddings found %d equivalence pair(s) from %d entities",
            len(triples) // 2,
            len(subjects),
        )
        return triples, 0, 0

    def _call_llm(
        self,
        raw_text: str,
        source_iri: str,
        subjects: list[str],
        profile: Any,
        system_prompt: str,
        confidence_threshold: float,
    ) -> tuple[list[ExtractedTriple], int, int]:
        """Call the LLM for a single batch of entity IRIs."""
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
            from pydantic import BaseModel, Field as PydField  # noqa: PLC0415
        except ImportError:
            logger.debug("EntityResolutionPass: instructor/openai/pydantic not available")
            return [], 0, 0

        class _EquivalencePair(BaseModel):
            entity_a: str
            entity_b: str
            confidence: float = PydField(ge=0.0, le=1.0)
            reasoning: str = ""

        class _ResolutionOut(BaseModel):
            equivalences: list[_EquivalencePair] = []

        try:
            client, model_name, provider = self._get_llm_client(profile)
        except Exception as exc:  # noqa: BLE001
            logger.debug("EntityResolutionPass: could not build LLM client: %s", exc)
            return [], 0, 0

        entity_list = "\n".join(f"  - {s}" for s in subjects)
        # Truncate document to avoid overflow — first 6 000 chars give enough context
        doc_excerpt = raw_text[:6000] if len(raw_text) > 6000 else raw_text
        user_content = (
            f"ENTITY IRIs extracted from this document:\n{entity_list}\n\n"
            f"DOCUMENT TEXT:\n{doc_excerpt}"
        )

        try:
            extra_kwargs: dict = (
                {"extra_body": {"keep_alive": "5m"}} if provider == "ollama" else {}
            )
            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_model=_ResolutionOut,
                **extra_kwargs,
            )
            usage = completion.usage if completion else None
            pt = usage.prompt_tokens if usage else 0
            ct = usage.completion_tokens if usage else 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("EntityResolutionPass: LLM call failed: %s", str(exc)[:200])
            return [], 0, 0

        named_graph = getattr(profile, "named_graph", "<trusted>")
        subject_set = set(subjects)  # for fast O(1) membership check
        doc_len = len(raw_text)
        triples: list[ExtractedTriple] = []

        for pair in result.equivalences:
            if pair.confidence < confidence_threshold:
                continue
            # Reject hallucinated IRIs — both must have been in our input
            if pair.entity_a not in subject_set or pair.entity_b not in subject_set:
                logger.debug(
                    "EntityResolutionPass: skipping hallucinated pair (%s, %s)",
                    pair.entity_a,
                    pair.entity_b,
                )
                continue
            if pair.entity_a == pair.entity_b:
                continue

            raw_excerpt = f"{pair.entity_a} \u2261 {pair.entity_b}"
            if pair.reasoning:
                raw_excerpt += f": {pair.reasoning}"
            excerpt = raw_excerpt[:200] or f"entity equivalence: {pair.entity_a}"

            try:
                evidence = EvidenceSpan(
                    source_iri=source_iri,
                    char_start=0,
                    char_end=max(1, doc_len),
                    excerpt=excerpt,
                )
                # owl:sameAs is symmetric — write both directions
                for subj, obj in (
                    (pair.entity_a, pair.entity_b),
                    (pair.entity_b, pair.entity_a),
                ):
                    triples.append(
                        ExtractedTriple(
                            subject=subj,
                            predicate="owl:sameAs",
                            object_value=obj,
                            confidence=pair.confidence,
                            evidence=evidence,
                            named_graph=named_graph,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("EntityResolutionPass: could not build triple: %s", exc)

        logger.debug(
            "EntityResolutionPass: %d equivalences → %d triples from %d entities",
            len(result.equivalences),
            len(triples),
            len(subjects),
        )
        return triples, pt, ct

    def _get_llm_client(self, profile: Any) -> tuple[Any, str, str]:
        """Return ``(instructor_client, model_name, provider)``."""
        import instructor  # noqa: PLC0415
        from openai import OpenAI  # noqa: PLC0415

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415

            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434/v1")
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(llm, "model", "llama3.2")

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
