"""Unit tests for Prometheus metrics module (v0.7.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_prometheus_available_flag_is_bool() -> None:
    """_PROMETHEUS_AVAILABLE is a bool regardless of whether prometheus_client is installed."""
    from riverbank.metrics import _PROMETHEUS_AVAILABLE

    assert isinstance(_PROMETHEUS_AVAILABLE, bool)


def test_metrics_text_returns_bytes() -> None:
    """metrics_text() always returns bytes."""
    from riverbank.metrics import metrics_text

    result = metrics_text()
    assert isinstance(result, bytes)


def test_record_run_does_not_raise() -> None:
    """record_run() must not raise under any combination of valid inputs."""
    from riverbank.metrics import record_run

    # Successful run
    record_run(profile="docs-policy-v1", outcome="success",
               duration_seconds=1.5, cost_usd=0.001, provider="openai")
    # Error run
    record_run(profile="docs-policy-v1", outcome="error",
               duration_seconds=0.1, cost_usd=0.0, provider="ollama")
    # Zero-cost run
    record_run(profile="default", outcome="success",
               duration_seconds=0.05, cost_usd=0.0)


def test_update_shacl_score_does_not_raise() -> None:
    """update_shacl_score() must not raise."""
    from riverbank.metrics import update_shacl_score

    update_shacl_score("http://riverbank.example/graph/trusted", 0.92)
    update_shacl_score("http://riverbank.example/graph/draft", 0.6)


def test_update_review_queue_depth_does_not_raise() -> None:
    """update_review_queue_depth() must not raise."""
    from riverbank.metrics import update_review_queue_depth

    update_review_queue_depth("http://riverbank.example/graph/trusted", 42)
    update_review_queue_depth("http://riverbank.example/graph/trusted", 0)


def test_update_context_efficiency_does_not_raise() -> None:
    """update_context_efficiency() must not raise."""
    from riverbank.metrics import update_context_efficiency

    update_context_efficiency("docs-policy-v1", 3.7)
    update_context_efficiency("default", 1.0)


def test_metric_names_present_in_metrics_text() -> None:
    """When prometheus_client is available, metric names appear in the output."""
    from riverbank.metrics import _PROMETHEUS_AVAILABLE, metrics_text, record_run

    if not _PROMETHEUS_AVAILABLE:
        # Without prometheus_client the output is empty — that is correct behaviour
        return

    record_run("test-profile", "success", 1.0, 0.0, "ollama")
    text = metrics_text().decode("utf-8")
    assert "riverbank_runs_total" in text
    assert "riverbank_run_duration_seconds" in text


def test_runs_total_labels_are_profile_and_outcome() -> None:
    """runs_total metric has the expected label names."""
    from riverbank.metrics import _PROMETHEUS_AVAILABLE, runs_total

    if not _PROMETHEUS_AVAILABLE:
        return

    # Access label names via prometheus_client internals
    assert hasattr(runs_total, "_labelnames")
    assert "profile" in runs_total._labelnames
    assert "outcome" in runs_total._labelnames


def test_cost_metric_has_provider_label() -> None:
    """llm_cost_usd_total metric has a 'provider' label."""
    from riverbank.metrics import _PROMETHEUS_AVAILABLE, llm_cost_usd_total

    if not _PROMETHEUS_AVAILABLE:
        return

    assert hasattr(llm_cost_usd_total, "_labelnames")
    assert "provider" in llm_cost_usd_total._labelnames


def test_shacl_score_metric_has_named_graph_label() -> None:
    """shacl_score metric has a 'named_graph' label."""
    from riverbank.metrics import _PROMETHEUS_AVAILABLE, shacl_score

    if not _PROMETHEUS_AVAILABLE:
        return

    assert hasattr(shacl_score, "_labelnames")
    assert "named_graph" in shacl_score._labelnames


def test_context_efficiency_metric_has_profile_label() -> None:
    """context_efficiency_ratio metric has a 'profile' label."""
    from riverbank.metrics import _PROMETHEUS_AVAILABLE, context_efficiency_ratio

    if not _PROMETHEUS_AVAILABLE:
        return

    assert hasattr(context_efficiency_ratio, "_labelnames")
    assert "profile" in context_efficiency_ratio._labelnames
