from __future__ import annotations

"""Model ensemble compilation (v0.8.0).

Per-profile opt-in ensemble compilation runs N model variants on the same
fragment and routes disagreements to Label Studio with a side-by-side
comparison template.  A hard cost cap is configurable per profile to prevent
runaway LLM costs during ensemble runs.

Architecture:
- ``EnsembleConfig`` captures the per-profile ensemble settings.
- ``EnsembleResult`` holds the per-model extraction results.
- ``run_ensemble`` orchestrates the N-model run, detects disagreements, and
  optionally queues disagreements for review.
- ``detect_disagreements`` compares extraction results across models and
  returns the triples where models disagree (by predicate + object).

Relay pipeline and cost accounting integrate with the existing
``_riverbank.runs`` table — each model variant records its own run row.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EnsembleConfig:
    """Per-profile ensemble compilation configuration.

    Attributes:
        models:           List of (provider, model_name) tuples to run.
        cost_cap_usd:     Maximum total cost in USD before ensemble is aborted.
        route_disagreements: Whether to send disagreements to Label Studio.
        agreement_threshold: Fraction of models that must agree for a triple to
                             be accepted without review. Default 0.5 (majority).
    """

    models: list[tuple[str, str]] = field(default_factory=list)
    cost_cap_usd: float = 1.0
    route_disagreements: bool = True
    agreement_threshold: float = 0.5


@dataclass
class EnsembleResult:
    """Result from running one model in the ensemble.

    Attributes:
        provider:    LLM provider name.
        model_name:  Model name / version.
        triples:     List of extracted triple dicts.
        cost_usd:    Estimated cost for this model's run.
        error:       Error message if the run failed, else empty string.
    """

    provider: str
    model_name: str
    triples: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str = ""

    @property
    def succeeded(self) -> bool:
        """Return True if the run completed without error."""
        return self.error == ""


# ---------------------------------------------------------------------------
# Disagreement detection
# ---------------------------------------------------------------------------

def detect_disagreements(
    results: list[EnsembleResult],
    threshold: float = 0.5,
) -> list[dict]:
    """Find triples where fewer than *threshold* of models agree.

    Groups triples by ``(subject, predicate)`` and counts how many models
    produced each unique ``object_value``.  Returns a list of disagreement
    dicts:

    .. code-block:: python

        {
            "subject": "...",
            "predicate": "...",
            "values": [
                {"object_value": "...", "models": ["openai/gpt-4o", ...], "count": 2},
                ...
            ],
        }

    A pair is considered a *disagreement* when no single object_value is
    produced by >= *threshold* fraction of successful models.
    """
    successful = [r for r in results if r.succeeded]
    if not successful:
        return []

    n = len(successful)

    # Accumulate votes: (subject, predicate) → {object_value → [model_labels]}
    votes: dict[tuple[str, str], dict[str, list[str]]] = {}

    for result in successful:
        model_label = f"{result.provider}/{result.model_name}"
        for triple in result.triples:
            s = str(triple.get("subject", ""))
            p = str(triple.get("predicate", ""))
            o = str(triple.get("object_value", triple.get("object", "")))
            key = (s, p)
            if key not in votes:
                votes[key] = {}
            if o not in votes[key]:
                votes[key][o] = []
            votes[key][o].append(model_label)

    disagreements: list[dict] = []
    for (subject, predicate), object_votes in votes.items():
        max_agreement = max(len(models) for models in object_votes.values()) / n
        if max_agreement < threshold:
            disagreements.append(
                {
                    "subject": subject,
                    "predicate": predicate,
                    "values": [
                        {"object_value": obj, "models": ms, "count": len(ms)}
                        for obj, ms in sorted(object_votes.items(), key=lambda x: -len(x[1]))
                    ],
                }
            )

    return disagreements


def merge_ensemble_results(
    results: list[EnsembleResult],
    threshold: float = 0.5,
) -> list[dict]:
    """Merge ensemble results, keeping only triples that meet the agreement threshold.

    Returns a list of triple dicts where >= *threshold* fraction of successful
    models agree on the object value.  The confidence is set to the agreement
    fraction.
    """
    successful = [r for r in results if r.succeeded]
    if not successful:
        return []

    n = len(successful)

    # Accumulate votes
    votes: dict[tuple[str, str], dict[str, list[dict]]] = {}

    for result in successful:
        for triple in result.triples:
            s = str(triple.get("subject", ""))
            p = str(triple.get("predicate", ""))
            o = str(triple.get("object_value", triple.get("object", "")))
            key = (s, p)
            if key not in votes:
                votes[key] = {}
            if o not in votes[key]:
                votes[key][o] = []
            votes[key][o].append(triple)

    merged: list[dict] = []
    for (subject, predicate), object_votes in votes.items():
        for obj, triples in object_votes.items():
            agreement = len(triples) / n
            if agreement >= threshold:
                # Use the first triple as the template, override confidence
                base = dict(triples[0])
                base["confidence"] = agreement
                merged.append(base)

    return merged


def run_ensemble(
    fragment_text: str,
    config: EnsembleConfig,
    extract_fn: Callable[[str, str, str], EnsembleResult],
) -> tuple[list[dict], list[dict], float]:
    """Run all models in the ensemble and return merged triples + disagreements.

    Args:
        fragment_text: The text fragment to extract from.
        config:        Ensemble configuration (models, cost cap, etc.).
        extract_fn:    Callable that takes (fragment_text, provider, model_name)
                       and returns an ``EnsembleResult``.  Injected for
                       testability.

    Returns:
        A 3-tuple of (merged_triples, disagreements, total_cost_usd).
        ``merged_triples`` contains only triples meeting the agreement threshold.
        ``disagreements`` contains triples where models disagree.
        ``total_cost_usd`` is the sum of all model run costs.
    """
    results: list[EnsembleResult] = []
    total_cost = 0.0

    for provider, model_name in config.models:
        if total_cost >= config.cost_cap_usd:
            logger.warning(
                "run_ensemble: cost cap $%.4f reached after %d models — stopping",
                config.cost_cap_usd,
                len(results),
            )
            break
        try:
            result = extract_fn(fragment_text, provider, model_name)
            results.append(result)
            total_cost += result.cost_usd
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "run_ensemble: model %s/%s failed: %s", provider, model_name, exc
            )
            results.append(
                EnsembleResult(provider=provider, model_name=model_name, error=str(exc))
            )

    merged = merge_ensemble_results(results, threshold=config.agreement_threshold)
    disagreements = detect_disagreements(results, threshold=config.agreement_threshold)

    logger.info(
        "run_ensemble: %d models, %d merged triples, %d disagreements, cost=$%.4f",
        len(results),
        len(merged),
        len(disagreements),
        total_cost,
    )

    return merged, disagreements, total_cost
