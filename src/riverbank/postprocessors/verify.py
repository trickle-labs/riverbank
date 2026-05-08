"""Post-2: Self-Critique Verification Pass (v0.11.0, batching v0.13.1).

**Problem:** Low-confidence triples (below the ``confidence_threshold``) are
extracted but may not be well-supported by the source text.

**Approach:** After extraction, run LLM verification calls on low-confidence
triples.  Since v0.13.1, triples are grouped into batches of up to
``verification.batch_size`` (default 5) per LLM call, reducing total LLM calls
for a typical 20-triple run from 20 to ≤ 4 and saving ~3 400 tokens.

Profile YAML extension::

    verification:
      enabled: true
      confidence_threshold: 0.75   # only verify triples below this score
      drop_below: 0.4              # quarantine triples where verifier scores < 0.4
      boost_above: 0.8             # re-write with boosted confidence when verifier scores ≥ this
      batch_size: 5                # triples per LLM call (default 5, max 10)

**Expected effect:** ~15–25% of low-confidence triples eliminated; ~5%
false-positive rate (triples incorrectly quarantined).  Batching reduces LLM
calls ≤ ceil(N / batch_size) for N candidate triples.

Falls back gracefully when the LLM is unavailable or when pg_ripple is not
installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Quarantine graph IRI — triples rejected by the verifier move here.
_DRAFT_GRAPH = "http://riverbank.example/graph/draft"

# Maximum allowed batch size to prevent prompt explosion.
_MAX_BATCH_SIZE = 10

# NLI cross-encoder model used when backend=="nli".
_NLI_MODEL_NAME = "cross-encoder/nli-distilroberta-base"
# Label indices for cross-encoder/nli-distilroberta-base:
#   0 = contradiction, 1 = entailment, 2 = neutral
_NLI_IDX_CONTRADICTION = 0
_NLI_IDX_ENTAILMENT = 1

# System prompt for the verification LLM call.
_VERIFIER_SYSTEM_PROMPT = """\
You are a knowledge graph fact-checker.

Given a source text excerpt and a candidate RDF triple, decide whether the
triple is supported by the text.

Respond ONLY with a JSON object with two fields:
  "supported": true or false
  "confidence": a float between 0.0 and 1.0

Do not include any other text.
"""

# System prompt for batched verification (multiple triples per call).
_BATCH_VERIFIER_SYSTEM_PROMPT = """\
You are a knowledge graph fact-checker.

You will be given one or more candidate RDF triples, each with a source text
excerpt.  For EACH triple, decide whether it is supported by its source text.

Respond ONLY with a JSON array.  Each element must be an object with:
  "index": integer matching the triple's index (0-based)
  "supported": true or false
  "confidence": a float between 0.0 and 1.0

Do not include any other text.
"""

_VERIFIER_USER_TEMPLATE = """\
Source text:
{evidence}

Candidate triple:
  subject:   {subject}
  predicate: {predicate}
  object:    {object_value}

Is this triple supported by the source text?
"""


@dataclass
class VerificationOutcome:
    """The result of verifying a single triple."""

    triple_id: str          # unique identifier for the triple (subject + predicate + object)
    supported: bool         # verifier says the triple holds
    verifier_confidence: float  # verifier's confidence in its decision
    action: str             # "boosted" | "kept" | "quarantined" | "skipped" | "error"


@dataclass
class VerificationResult:
    """Summary of a full verification pass."""

    triples_examined: int = 0
    boosted: int = 0        # confidence raised (verified as supported, high confidence)
    kept: int = 0           # unchanged (verified as supported, moderate confidence)
    quarantined: int = 0    # moved to <draft> (verifier rejected)
    errors: int = 0         # LLM call failures
    prompt_tokens: int = 0
    completion_tokens: int = 0
    outcomes: list[VerificationOutcome] = field(default_factory=list)


class VerificationPass:
    """Re-evaluate low-confidence triples with a second LLM call.

    The verifier reads the evidence excerpt stored in ``pgc:evidenceExcerpt``
    for each triple and asks the LLM whether the claim is supported by the
    source text.

    Args:
        settings: riverbank :class:`~riverbank.config.Settings` instance.
            When ``None``, settings are loaded from environment / config file.

    Profile YAML keys consumed from ``verification:``::

        enabled: true
        confidence_threshold: 0.75   # verify triples below this score
        drop_below: 0.4              # quarantine when verifier confidence < this
        boost_above: 0.8             # boost confidence when verifier confidence ≥ this
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        conn: Any,
        named_graph: str,
        profile: Any,
        dry_run: bool = False,
    ) -> VerificationResult:
        """Run the verification pass against *named_graph*.

        Args:
            conn: Active SQLAlchemy connection (SQLAlchemy 2.x engine connection).
            named_graph: IRI of the named graph to verify.
            profile: :class:`~riverbank.pipeline.CompilerProfile` instance.
            dry_run: Compute outcomes but do not write any changes to the graph.

        Returns:
            :class:`VerificationResult` with per-triple outcomes and summary
            statistics.
        """
        verification_cfg: dict = getattr(profile, "verification", {})
        if not verification_cfg.get("enabled", False):
            logger.debug("verify: verification disabled in profile — skipping")
            return VerificationResult()

        conf_threshold: float = float(verification_cfg.get("confidence_threshold", 0.75))
        drop_below: float = float(verification_cfg.get("drop_below", 0.4))
        boost_above: float = float(verification_cfg.get("boost_above", 0.8))
        batch_size: int = min(
            int(verification_cfg.get("batch_size", 5)),
            _MAX_BATCH_SIZE,
        )
        draft_graph: str = verification_cfg.get(
            "quarantine_graph", _DRAFT_GRAPH
        )

        # Fetch low-confidence triples with their evidence excerpts.
        candidates = self._fetch_candidates(conn, named_graph, conf_threshold)
        if not candidates:
            logger.info(
                "verify: no triples below confidence threshold %.2f in <%s>",
                conf_threshold,
                named_graph,
            )
            return VerificationResult()

        llm_calls = -(-len(candidates) // max(batch_size, 1))  # ceil division
        logger.info(
            "verify: examining %d low-confidence triples (threshold=%.2f) in <%s> "
            "using %d LLM call(s) (batch_size=%d)",
            len(candidates),
            conf_threshold,
            named_graph,
            llm_calls,
            batch_size,
        )

        result = VerificationResult(triples_examined=len(candidates))

        # Load verifier once — NLI cross-encoder or LLM (fail fast if unavailable).
        backend: str = verification_cfg.get("backend", "llm")
        nli_model: Any = None
        client: Any = None
        model_name: str = ""

        if backend == "nli":
            try:
                nli_model = self._get_nli_model()
            except ImportError as exc:
                logger.warning(
                    "verify: NLI model not available — verification skipped. %s", exc
                )
                return result
        else:
            try:
                client, model_name = self._get_llm_client(profile)
            except ImportError as exc:
                logger.warning(
                    "verify: LLM not available — verification skipped. %s", exc
                )
                return result

        # Process candidates in batches
        for batch_start in range(0, len(candidates), batch_size):
            batch = candidates[batch_start : batch_start + batch_size]
            if nli_model is not None:
                if len(batch) == 1:
                    outcomes = [self._verify_triple_nli(batch[0], nli_model)]
                else:
                    outcomes = self._verify_batch_nli(batch, nli_model)
            elif len(batch) == 1:
                # Single-triple path — use the original per-triple verifier
                outcomes = [self._verify_triple(batch[0], client, model_name)]
            else:
                outcomes = self._verify_batch(batch, client, model_name)

            for triple, outcome in zip(batch, outcomes):
                result.prompt_tokens += outcome.get("prompt_tokens", 0)
                result.completion_tokens += outcome.get("completion_tokens", 0)

                triple_id = _triple_id(triple)
                supported = outcome.get("supported", True)
                vc = outcome.get("verifier_confidence", 0.5)
                error = outcome.get("error")

                if error:
                    result.errors += 1
                    result.outcomes.append(
                        VerificationOutcome(
                            triple_id=triple_id,
                            supported=True,
                            verifier_confidence=0.0,
                            action="error",
                        )
                    )
                    continue

                if not supported or vc < drop_below:
                    action = "quarantined"
                    if not dry_run:
                        self._quarantine_triple(conn, triple, named_graph, draft_graph)
                    result.quarantined += 1
                elif vc >= boost_above:
                    action = "boosted"
                    if not dry_run:
                        self._update_confidence(conn, triple, named_graph, new_confidence=vc)
                    result.boosted += 1
                else:
                    action = "kept"
                    result.kept += 1

                result.outcomes.append(
                    VerificationOutcome(
                        triple_id=triple_id,
                        supported=supported,
                        verifier_confidence=vc,
                        action=action,
                    )
                )

        if not dry_run and (result.quarantined + result.boosted) > 0:
            try:
                conn.commit()
            except Exception:  # noqa: BLE001
                pass  # caller may handle commit

        logger.info(
            "verify: done — boosted=%d  kept=%d  quarantined=%d  errors=%d",
            result.boosted,
            result.kept,
            result.quarantined,
            result.errors,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_candidates(
        self,
        conn: Any,
        named_graph: str,
        threshold: float,
    ) -> list[dict]:
        """Return low-confidence triples with their evidence from *named_graph*.

        Each item is a dict with keys: ``subject``, ``predicate``,
        ``object_value``, ``confidence``, ``evidence``.

        Falls back to ``[]`` when pg_ripple is unavailable.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        sparql = f"""\
SELECT ?s ?p ?o ?confidence ?evidence WHERE {{
  GRAPH <{named_graph}> {{
    ?s ?p ?o .
    ?s <http://riverbank.example/pgc/confidence> ?confidence .
    OPTIONAL {{ ?s <http://riverbank.example/pgc/evidenceExcerpt> ?evidence . }}
    FILTER(?confidence < {threshold})
    FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
  }}
}}
LIMIT 500
"""
        try:
            rows = sparql_query(conn, sparql)
        except Exception as exc:  # noqa: BLE001
            logger.warning("verify: could not fetch candidates — %s", exc)
            return []

        candidates: list[dict] = []
        for row in rows:
            s = str(row.get("s", "")).strip()
            p = str(row.get("p", "")).strip()
            o = str(row.get("o", "")).strip()
            conf_raw = row.get("confidence", 0.5)
            evidence = str(row.get("evidence", "")).strip()
            if not (s and p and o):
                continue
            try:
                confidence = float(conf_raw)
            except (TypeError, ValueError):
                confidence = 0.5
            candidates.append(
                {
                    "subject": s,
                    "predicate": p,
                    "object_value": o,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            )
        return candidates

    def _verify_triple(
        self,
        triple: dict,
        client: Any,
        model_name: str,
    ) -> dict:
        """Make one LLM verification call for *triple*.

        Returns a dict with ``supported``, ``verifier_confidence``,
        ``prompt_tokens``, ``completion_tokens``, and optionally ``error``.
        """
        evidence = triple.get("evidence", "") or "(no evidence available)"
        user_message = _VERIFIER_USER_TEMPLATE.format(
            evidence=evidence[:2000],  # cap excerpt length
            subject=triple["subject"],
            predicate=triple["predicate"],
            object_value=triple["object_value"],
        )

        try:
            from pydantic import BaseModel  # noqa: PLC0415

            class _VerificationDecision(BaseModel):
                supported: bool
                confidence: float

            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _VERIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_model=_VerificationDecision,
                max_retries=1,
            )

            usage = getattr(completion, "usage", None)
            pt = getattr(usage, "prompt_tokens", 0) if usage else 0
            ct = getattr(usage, "completion_tokens", 0) if usage else 0

            return {
                "supported": result.supported,
                "verifier_confidence": float(max(0.0, min(1.0, result.confidence))),
                "prompt_tokens": pt,
                "completion_tokens": ct,
            }

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "verify: LLM call failed for triple (%s, %s, %s) — %s",
                triple["subject"],
                triple["predicate"],
                triple["object_value"],
                exc,
            )
            return {"error": str(exc), "prompt_tokens": 0, "completion_tokens": 0}

    def _verify_batch(
        self,
        batch: list[dict],
        client: Any,
        model_name: str,
    ) -> list[dict]:
        """Verify a batch of triples in a single LLM call.

        Groups the triples into a single prompt and parses a JSON array response.
        Returns one outcome dict per triple in the same order as *batch*.
        Falls back to individual calls if the LLM returns unparseable output.

        Each outcome dict has keys: ``supported``, ``verifier_confidence``,
        ``prompt_tokens``, ``completion_tokens``, and optionally ``error``.
        """
        # Build a multi-triple prompt
        parts = []
        for idx, triple in enumerate(batch):
            evidence = triple.get("evidence", "") or "(no evidence available)"
            parts.append(
                f"[{idx}] Source text: {evidence[:500]}\n"
                f"    Triple: ({triple['subject']}, {triple['predicate']}, "
                f"{triple['object_value']})"
            )
        user_message = (
            "Verify each of the following triples against its source text.\n\n"
            + "\n\n".join(parts)
            + "\n\nReturn a JSON array with one object per triple (index, supported, confidence)."
        )

        try:
            import json as _json  # noqa: PLC0415
            from pydantic import BaseModel  # noqa: PLC0415

            class _BatchDecision(BaseModel):
                index: int
                supported: bool
                confidence: float

            class _BatchResponse(BaseModel):
                results: list[_BatchDecision]

            result, completion = client.chat.completions.create_with_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": _BATCH_VERIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_model=_BatchResponse,
                max_retries=1,
            )

            usage = getattr(completion, "usage", None)
            pt = getattr(usage, "prompt_tokens", 0) if usage else 0
            ct = getattr(usage, "completion_tokens", 0) if usage else 0

            # Build index → decision map; fill missing indices with safe defaults
            decision_map: dict[int, _BatchDecision] = {d.index: d for d in result.results}
            outcomes: list[dict] = []
            for idx in range(len(batch)):
                dec = decision_map.get(idx)
                if dec is not None:
                    outcomes.append(
                        {
                            "supported": dec.supported,
                            "verifier_confidence": float(
                                max(0.0, min(1.0, dec.confidence))
                            ),
                            # Distribute token counts evenly across batch
                            "prompt_tokens": pt // len(batch),
                            "completion_tokens": ct // len(batch),
                        }
                    )
                else:
                    outcomes.append(
                        {
                            "supported": True,
                            "verifier_confidence": 0.5,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                        }
                    )
            return outcomes

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "verify: batch LLM call failed (%s) — falling back to individual calls",
                exc,
            )
            # Fallback: individual calls
            return [self._verify_triple(t, client, model_name) for t in batch]

    def _quarantine_triple(
        self,
        conn: Any,
        triple: dict,
        source_graph: str,
        draft_graph: str,
    ) -> None:
        """Move *triple* from *source_graph* to *draft_graph*.

        First writes the triple to the draft graph with the existing confidence,
        then deletes it from the source graph.  Falls back gracefully on any error.
        """
        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415
        from riverbank.postprocessors.dedup import _SameAsTriple  # noqa: PLC0415

        quarantine_triple = _SameAsTriple(
            subject=triple["subject"],
            predicate=triple["predicate"],
            object_value=triple["object_value"],
            confidence=triple.get("confidence", 0.5),
        )
        try:
            # Write to draft graph
            load_triples_with_confidence(conn, [quarantine_triple], draft_graph)
            # Delete from source graph using SPARQL DELETE
            self._delete_triple_from_graph(conn, triple, source_graph)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "verify: could not quarantine triple (%s, %s, %s) — %s",
                triple["subject"],
                triple["predicate"],
                triple["object_value"],
                exc,
            )

    def _update_confidence(
        self,
        conn: Any,
        triple: dict,
        named_graph: str,
        new_confidence: float,
    ) -> None:
        """Boost the confidence of *triple* in *named_graph*.

        Deletes the old triple and re-inserts with the new confidence.
        Falls back gracefully on error.
        """
        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415
        from riverbank.postprocessors.dedup import _SameAsTriple  # noqa: PLC0415

        boosted_triple = _SameAsTriple(
            subject=triple["subject"],
            predicate=triple["predicate"],
            object_value=triple["object_value"],
            confidence=new_confidence,
        )
        try:
            self._delete_triple_from_graph(conn, triple, named_graph)
            load_triples_with_confidence(conn, [boosted_triple], named_graph)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "verify: could not update confidence for triple (%s, %s, %s) — %s",
                triple["subject"],
                triple["predicate"],
                triple["object_value"],
                exc,
            )

    def _delete_triple_from_graph(
        self,
        conn: Any,
        triple: dict,
        named_graph: str,
    ) -> None:
        """Delete a single triple from *named_graph* via SPARQL UPDATE.

        Falls back gracefully when pg_ripple does not support SPARQL UPDATE.
        """
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        s = triple["subject"]
        p = triple["predicate"]
        o = triple["object_value"]

        # Build N-Triples-style terms for use in SPARQL DELETE DATA
        s_term = f"<{s}>" if s.startswith("http") else f"<http://riverbank.example/entities/{s}>"
        p_term = f"<{p}>" if p.startswith("http") else f"<http://www.w3.org/1999/02/22-rdf-syntax-ns#{p}>"
        if o.startswith("http"):
            o_term = f"<{o}>"
        else:
            escaped = o.replace("\\", "\\\\").replace('"', '\\"')
            o_term = f'"{escaped}"'

        sparql_delete = (
            f"DELETE DATA {{ GRAPH <{named_graph}> {{ {s_term} {p_term} {o_term} . }} }}"
        )
        try:
            sparql_query(conn, sparql_delete)
        except Exception as exc:  # noqa: BLE001
            logger.debug("verify: SPARQL DELETE failed (non-critical) — %s", exc)

    def _get_nli_model(self) -> Any:
        """Load and cache the NLI cross-encoder (sentence-transformers).

        Raises ``ImportError`` when ``sentence-transformers`` is not installed.
        """
        if not hasattr(self, "_cached_nli_model"):
            try:
                from sentence_transformers import CrossEncoder  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required for NLI verification. "
                    "Install with: pip install 'riverbank[ingest]'"
                ) from exc
            logger.info("verify: loading NLI model %r …", _NLI_MODEL_NAME)
            self._cached_nli_model: Any = CrossEncoder(_NLI_MODEL_NAME)
        return self._cached_nli_model

    def _verify_triple_nli(self, triple: dict, model: Any) -> dict:
        """Verify a single triple using the NLI cross-encoder (no LLM call)."""
        evidence = triple.get("evidence", "") or "(no evidence available)"
        hypothesis = _triple_to_hypothesis(triple)
        try:
            logits = model.predict([(evidence[:2000], hypothesis)])[0]
            probs = _softmax(logits)
            entailment_p = float(probs[_NLI_IDX_ENTAILMENT])
            contradiction_p = float(probs[_NLI_IDX_CONTRADICTION])
            supported = entailment_p >= contradiction_p
            vc = entailment_p if supported else contradiction_p
            return {
                "supported": supported,
                "verifier_confidence": vc,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "verify: NLI call failed for (%s, %s, %s) — %s",
                triple["subject"],
                triple["predicate"],
                triple["object_value"],
                exc,
            )
            return {"error": str(exc), "prompt_tokens": 0, "completion_tokens": 0}

    def _verify_batch_nli(self, batch: list[dict], model: Any) -> list[dict]:
        """Verify a batch of triples in a single NLI forward pass."""
        # Build (premise, hypothesis) pairs
        input_pairs = [
            (
                (t.get("evidence", "") or "(no evidence available)")[:2000],
                _triple_to_hypothesis(t),
            )
            for t in batch
        ]
        try:
            logits_batch = model.predict(input_pairs)
            outcomes: list[dict] = []
            for logits in logits_batch:
                probs = _softmax(logits)
                entailment_p = float(probs[_NLI_IDX_ENTAILMENT])
                contradiction_p = float(probs[_NLI_IDX_CONTRADICTION])
                supported = entailment_p >= contradiction_p
                vc = entailment_p if supported else contradiction_p
                outcomes.append({
                    "supported": supported,
                    "verifier_confidence": vc,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                })
            return outcomes
        except Exception as exc:  # noqa: BLE001
            logger.warning("verify: NLI batch call failed (%s) — falling back to individual calls", exc)
            return [self._verify_triple_nli(t, model) for t in batch]

    def _get_llm_client(self, profile: Any) -> tuple[Any, str]:
        """Return an (instructor_client, model_name) pair."""
        try:
            import instructor  # noqa: PLC0415
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "instructor and openai are required for the verification pass. "
                "Install with: pip install 'riverbank[ingest]'"
            ) from exc

        settings = self._settings
        if settings is None:
            from riverbank.config import get_settings  # noqa: PLC0415
            settings = get_settings()

        llm = getattr(settings, "llm", None)
        provider: str = getattr(llm, "provider", "ollama")
        api_base: str = getattr(llm, "api_base", "http://localhost:11434/v1")
        api_key: str = getattr(llm, "api_key", "ollama")
        model_name: str = getattr(llm, "model", getattr(profile, "model_name", "llama3.2"))

        if provider == "copilot":
            mode = instructor.Mode.JSON
            client = instructor.from_openai(
                OpenAI(base_url="https://models.inference.ai.azure.com", api_key=api_key),
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

        return client, model_name


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _triple_id(triple: dict) -> str:
    """Return a short identifier string for a triple (for logging / reporting)."""
    s = triple.get("subject", "?")
    p = triple.get("predicate", "?")
    o = triple.get("object_value", "?")
    return f"({s}, {p}, {o})"


def _triple_to_hypothesis(triple: dict) -> str:
    """Render a triple as a short natural-language hypothesis for NLI."""
    def _localname(iri: str) -> str:
        local = iri.split(":")[-1] if ":" in iri else iri
        return local.replace("_", " ").replace("-", " ")

    subj = _localname(triple["subject"])
    pred = _localname(triple["predicate"])
    obj_raw = triple["object_value"]
    # If it looks like an IRI (contains ':' and no spaces), extract local name
    if ":" in obj_raw and " " not in obj_raw and not obj_raw.startswith('"'):
        obj = _localname(obj_raw)
    else:
        obj = obj_raw.strip('"')
    return f"{subj} {pred} {obj}."


def _softmax(logits: Any) -> list[float]:
    """Compute softmax probabilities from a list/array of raw logits."""
    import math  # noqa: PLC0415
    max_l = max(float(x) for x in logits)
    exp_l = [math.exp(float(x) - max_l) for x in logits]
    total = sum(exp_l)
    return [v / total for v in exp_l]
