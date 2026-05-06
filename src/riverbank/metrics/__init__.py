from __future__ import annotations

"""Prometheus metrics for riverbank (v0.7.0).

Exposes the following metrics:

* ``riverbank_runs_total`` — counter; labels: profile, outcome
* ``riverbank_run_duration_seconds`` — histogram; labels: profile
* ``riverbank_llm_cost_usd_total`` — counter; labels: profile, provider
* ``riverbank_shacl_score`` — gauge; labels: named_graph
* ``riverbank_review_queue_depth`` — gauge; labels: named_graph
* ``riverbank_context_efficiency_ratio`` — gauge; labels: profile

When *prometheus_client* is not installed the module degrades gracefully:
all metric objects are replaced with no-op stubs so the rest of riverbank
can import this module unconditionally.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful degradation when prometheus_client is absent
# ---------------------------------------------------------------------------

try:
    from prometheus_client import (  # type: ignore[import-untyped]
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    _PROMETHEUS_AVAILABLE = True
    _REGISTRY = CollectorRegistry(auto_describe=True)
except ImportError:
    _PROMETHEUS_AVAILABLE = False

    # Minimal no-op stubs so imports never fail
    class _NoOpMetric:
        """No-op stub that silently discards all metric operations."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def labels(self, **kwargs: Any) -> "_NoOpMetric":
            return self

        def inc(self, amount: float = 1.0) -> None:
            pass

        def set(self, value: float) -> None:
            pass

        def observe(self, value: float) -> None:
            pass

    Counter = _NoOpMetric  # type: ignore[misc,assignment]
    Gauge = _NoOpMetric  # type: ignore[misc,assignment]
    Histogram = _NoOpMetric  # type: ignore[misc,assignment]

    class _FakeRegistry:
        pass

    _REGISTRY = _FakeRegistry()  # type: ignore[assignment]

    def generate_latest(*args: Any) -> bytes:  # type: ignore[misc]
        return b""

    CONTENT_TYPE_LATEST = "text/plain"


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

_LABEL_NAMES_RUNS = ["profile", "outcome"]
_LABEL_NAMES_DURATION = ["profile"]
_LABEL_NAMES_COST = ["profile", "provider"]
_LABEL_NAMES_SHACL = ["named_graph"]
_LABEL_NAMES_QUEUE = ["named_graph"]
_LABEL_NAMES_EFFICIENCY = ["profile"]


def _make_counter(name: str, documentation: str, labelnames: list[str]) -> Any:
    if _PROMETHEUS_AVAILABLE:
        return Counter(name, documentation, labelnames, registry=_REGISTRY)
    return Counter(name, documentation, labelnames)


def _make_gauge(name: str, documentation: str, labelnames: list[str]) -> Any:
    if _PROMETHEUS_AVAILABLE:
        return Gauge(name, documentation, labelnames, registry=_REGISTRY)
    return Gauge(name, documentation, labelnames)


def _make_histogram(name: str, documentation: str, labelnames: list[str]) -> Any:
    if _PROMETHEUS_AVAILABLE:
        return Histogram(name, documentation, labelnames, registry=_REGISTRY)
    return Histogram(name, documentation, labelnames)


runs_total = _make_counter(
    "riverbank_runs_total",
    "Total number of fragment compilation runs, by profile and outcome.",
    _LABEL_NAMES_RUNS,
)

run_duration_seconds = _make_histogram(
    "riverbank_run_duration_seconds",
    "Duration of each fragment compilation run in seconds.",
    _LABEL_NAMES_DURATION,
)

llm_cost_usd_total = _make_counter(
    "riverbank_llm_cost_usd_total",
    "Cumulative LLM cost in USD, by profile and provider.",
    _LABEL_NAMES_COST,
)

shacl_score = _make_gauge(
    "riverbank_shacl_score",
    "Current SHACL validation score for each named graph [0.0–1.0].",
    _LABEL_NAMES_SHACL,
)

review_queue_depth = _make_gauge(
    "riverbank_review_queue_depth",
    "Number of items waiting in the human review queue.",
    _LABEL_NAMES_QUEUE,
)

context_efficiency_ratio = _make_gauge(
    "riverbank_context_efficiency_ratio",
    "Ratio of graph-context tokens to estimated naive-RAG tokens per rag_context() call.",
    _LABEL_NAMES_EFFICIENCY,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def record_run(
    profile: str,
    outcome: str,
    duration_seconds: float,
    cost_usd: float,
    provider: str = "unknown",
) -> None:
    """Record metrics for one completed fragment compilation run."""
    try:
        runs_total.labels(profile=profile, outcome=outcome).inc()
        run_duration_seconds.labels(profile=profile).observe(duration_seconds)
        if cost_usd > 0:
            llm_cost_usd_total.labels(profile=profile, provider=provider).inc(cost_usd)
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics.record_run error: %s", exc)


def update_shacl_score(named_graph: str, score: float) -> None:
    """Update the SHACL score gauge for a named graph."""
    try:
        shacl_score.labels(named_graph=named_graph).set(score)
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics.update_shacl_score error: %s", exc)


def update_review_queue_depth(named_graph: str, depth: int) -> None:
    """Update the review queue depth gauge."""
    try:
        review_queue_depth.labels(named_graph=named_graph).set(depth)
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics.update_review_queue_depth error: %s", exc)


def update_context_efficiency(profile: str, ratio: float) -> None:
    """Update the context efficiency ratio gauge for a profile."""
    try:
        context_efficiency_ratio.labels(profile=profile).set(ratio)
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics.update_context_efficiency error: %s", exc)


def metrics_text() -> bytes:
    """Return the current metrics snapshot as a Prometheus text exposition."""
    return generate_latest(_REGISTRY)
