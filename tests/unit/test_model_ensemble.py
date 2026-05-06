"""Unit tests for model ensemble compilation (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_ensemble_config_defaults() -> None:
    """EnsembleConfig has sensible defaults."""
    from riverbank.ensemble import EnsembleConfig

    cfg = EnsembleConfig()
    assert cfg.models == []
    assert cfg.cost_cap_usd == 1.0
    assert cfg.route_disagreements is True
    assert cfg.agreement_threshold == 0.5


def test_ensemble_result_succeeded_when_no_error() -> None:
    """EnsembleResult.succeeded is True when error is empty string."""
    from riverbank.ensemble import EnsembleResult

    result = EnsembleResult(provider="openai", model_name="gpt-4o", triples=[], cost_usd=0.01)
    assert result.succeeded is True


def test_ensemble_result_not_succeeded_when_error_set() -> None:
    """EnsembleResult.succeeded is False when error is non-empty."""
    from riverbank.ensemble import EnsembleResult

    result = EnsembleResult(provider="openai", model_name="gpt-4o", error="timeout")
    assert result.succeeded is False


def test_detect_disagreements_returns_empty_for_single_model() -> None:
    """detect_disagreements returns [] when only one model ran (trivially agrees)."""
    from riverbank.ensemble import EnsembleResult, detect_disagreements

    results = [
        EnsembleResult(
            provider="openai",
            model_name="gpt-4o",
            triples=[{"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:B"}],
        )
    ]

    disagreements = detect_disagreements(results, threshold=0.5)
    # Single model: agreement is 1/1 = 1.0 ≥ 0.5 — no disagreement
    assert disagreements == []


def test_detect_disagreements_finds_disagreement() -> None:
    """detect_disagreements finds pairs where models disagree on the object."""
    from riverbank.ensemble import EnsembleResult, detect_disagreements

    results = [
        EnsembleResult(
            provider="openai",
            model_name="gpt-4o",
            triples=[{"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Alice"}],
        ),
        EnsembleResult(
            provider="anthropic",
            model_name="claude-3",
            triples=[{"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Bob"}],
        ),
        EnsembleResult(
            provider="ollama",
            model_name="llama3.2",
            triples=[{"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Carol"}],
        ),
    ]

    disagreements = detect_disagreements(results, threshold=0.5)
    assert len(disagreements) == 1
    assert disagreements[0]["subject"] == "ex:Acme"
    assert disagreements[0]["predicate"] == "ex:hasCEO"
    assert len(disagreements[0]["values"]) == 3


def test_detect_disagreements_no_disagreement_when_majority_agrees() -> None:
    """detect_disagreements returns [] when majority of models agree."""
    from riverbank.ensemble import EnsembleResult, detect_disagreements

    results = [
        EnsembleResult(
            provider="openai",
            model_name="gpt-4o",
            triples=[{"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Alice"}],
        ),
        EnsembleResult(
            provider="anthropic",
            model_name="claude-3",
            triples=[{"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Alice"}],
        ),
        EnsembleResult(
            provider="ollama",
            model_name="llama3.2",
            triples=[{"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Bob"}],
        ),
    ]

    # 2/3 agree on Alice = 0.667 ≥ threshold 0.5
    disagreements = detect_disagreements(results, threshold=0.5)
    assert disagreements == []


def test_merge_ensemble_results_keeps_majority_triples() -> None:
    """merge_ensemble_results keeps triples where >= threshold fraction agree."""
    from riverbank.ensemble import EnsembleResult, merge_ensemble_results

    results = [
        EnsembleResult(
            provider="openai",
            model_name="gpt-4o",
            triples=[
                {"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Alice"},
                {"subject": "ex:Acme", "predicate": "ex:hasCTO", "object_value": "ex:Dave"},
            ],
        ),
        EnsembleResult(
            provider="anthropic",
            model_name="claude-3",
            triples=[
                {"subject": "ex:Acme", "predicate": "ex:hasCEO", "object_value": "ex:Alice"},
                # CTO not extracted
            ],
        ),
    ]

    merged = merge_ensemble_results(results, threshold=0.5)
    # ex:hasCEO agrees 2/2 = 1.0 ≥ 0.5 — include
    # ex:hasCTO agrees 1/2 = 0.5 ≥ 0.5 — include (borderline)
    ceo_triples = [t for t in merged if t["predicate"] == "ex:hasCEO"]
    assert len(ceo_triples) == 1
    assert ceo_triples[0]["object_value"] == "ex:Alice"
    assert ceo_triples[0]["confidence"] == 1.0


def test_merge_ensemble_results_sets_confidence_to_agreement_fraction() -> None:
    """merge_ensemble_results sets confidence to the agreement fraction."""
    from riverbank.ensemble import EnsembleResult, merge_ensemble_results

    results = [
        EnsembleResult(
            provider="openai",
            model_name="gpt-4o",
            triples=[{"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:X"}],
        ),
        EnsembleResult(
            provider="anthropic",
            model_name="claude-3",
            triples=[{"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:X"}],
        ),
        EnsembleResult(
            provider="ollama",
            model_name="llama3.2",
            triples=[{"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:Y"}],
        ),
    ]

    merged = merge_ensemble_results(results, threshold=0.5)
    x_triples = [t for t in merged if t.get("object_value") == "ex:X"]
    assert len(x_triples) == 1
    assert abs(x_triples[0]["confidence"] - 2 / 3) < 0.01


def test_run_ensemble_respects_cost_cap() -> None:
    """run_ensemble stops when cost cap is reached."""
    from riverbank.ensemble import EnsembleConfig, EnsembleResult, run_ensemble

    call_count = [0]

    def extract_fn(fragment_text: str, provider: str, model_name: str) -> EnsembleResult:
        call_count[0] += 1
        return EnsembleResult(
            provider=provider,
            model_name=model_name,
            triples=[],
            cost_usd=0.60,  # Each model costs $0.60
        )

    config = EnsembleConfig(
        models=[("openai", "gpt-4o"), ("anthropic", "claude-3"), ("ollama", "llama3.2")],
        cost_cap_usd=1.0,  # Cap at $1.00
        agreement_threshold=0.5,
    )

    merged, disagreements, total_cost = run_ensemble("test fragment", config, extract_fn)

    # Model 1 runs → cost=0.60 (< 1.0 cap, continues)
    # Model 2 runs → cost=1.20, cap reached → model 3 skipped
    assert call_count[0] == 2
    assert abs(total_cost - 1.20) < 0.001


def test_run_ensemble_handles_model_failure_gracefully() -> None:
    """run_ensemble records failed models but continues with remaining models."""
    from riverbank.ensemble import EnsembleConfig, EnsembleResult, run_ensemble

    def extract_fn(fragment_text: str, provider: str, model_name: str) -> EnsembleResult:
        if provider == "failing":
            raise RuntimeError("Connection timeout")
        return EnsembleResult(
            provider=provider,
            model_name=model_name,
            triples=[{"subject": "ex:A", "predicate": "ex:p", "object_value": "ex:X"}],
            cost_usd=0.01,
        )

    config = EnsembleConfig(
        models=[("failing", "model-x"), ("openai", "gpt-4o")],
        cost_cap_usd=10.0,
        agreement_threshold=0.5,
    )

    merged, disagreements, total_cost = run_ensemble("test fragment", config, extract_fn)

    # Failing model produces no triples; openai model produces one triple (1/1 = 1.0 ≥ 0.5)
    assert len(merged) == 1
    assert total_cost == 0.01


def test_detect_disagreements_returns_empty_for_failed_models() -> None:
    """detect_disagreements returns [] when all models failed."""
    from riverbank.ensemble import EnsembleResult, detect_disagreements

    results = [
        EnsembleResult(provider="openai", model_name="gpt-4o", error="timeout"),
        EnsembleResult(provider="anthropic", model_name="claude-3", error="rate_limit"),
    ]

    disagreements = detect_disagreements(results, threshold=0.5)
    assert disagreements == []


def test_merge_ensemble_results_returns_empty_for_failed_models() -> None:
    """merge_ensemble_results returns [] when all models failed."""
    from riverbank.ensemble import EnsembleResult, merge_ensemble_results

    results = [
        EnsembleResult(provider="openai", model_name="gpt-4o", error="timeout"),
    ]

    merged = merge_ensemble_results(results, threshold=0.5)
    assert merged == []
