"""Unit tests for OpenTelemetry export configuration (v0.7.0)."""
from __future__ import annotations

import os
import unittest.mock as mock


def test_setup_tracing_is_idempotent() -> None:
    """Calling setup_tracing() twice does not raise and does not double-register."""
    from riverbank import observability

    # Reset the initialized flag to allow a clean test
    observability._initialized = False

    observability.setup_tracing("test-service")
    observability.setup_tracing("test-service")  # second call must be a no-op


def test_get_tracer_returns_tracer() -> None:
    """get_tracer returns a tracer object."""
    from opentelemetry import trace

    from riverbank.observability import get_tracer

    tracer = get_tracer("test-component")
    assert tracer is not None


def test_setup_tracing_uses_console_exporter_without_endpoint() -> None:
    """Without OTEL_EXPORTER_OTLP_ENDPOINT, setup_tracing uses ConsoleSpanExporter."""
    from riverbank import observability

    observability._initialized = False

    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        with mock.patch(
            "riverbank.observability.ConsoleSpanExporter"
        ) as mock_console:
            with mock.patch("riverbank.observability.BatchSpanProcessor"):
                with mock.patch("riverbank.observability.TracerProvider") as mock_provider_cls:
                    mock_provider = mock.MagicMock()
                    mock_provider_cls.return_value = mock_provider
                    observability.setup_tracing("test")
                    mock_console.assert_called_once()

    observability._initialized = False


def test_setup_tracing_uses_otlp_exporter_when_endpoint_set() -> None:
    """When OTEL_EXPORTER_OTLP_ENDPOINT is set, _build_otlp_exporter is called."""
    from riverbank import observability

    observability._initialized = False

    with mock.patch.dict(
        os.environ,
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4317"},
    ):
        with mock.patch("riverbank.observability._build_otlp_exporter") as mock_build:
            mock_build.return_value = mock.MagicMock()
            with mock.patch("riverbank.observability.TracerProvider") as mock_provider_cls:
                with mock.patch("riverbank.observability.BatchSpanProcessor"):
                    mock_provider = mock.MagicMock()
                    mock_provider_cls.return_value = mock_provider
                    observability.setup_tracing("test-otlp")
                    mock_build.assert_called_once_with(
                        "http://otel-collector:4317", "test-otlp"
                    )

    observability._initialized = False


def test_build_otlp_exporter_returns_none_when_no_package_installed() -> None:
    """_build_otlp_exporter returns None gracefully when no OTLP package is installed."""
    from riverbank.observability import _build_otlp_exporter

    with mock.patch.dict("sys.modules", {
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": None,
    }):
        result = _build_otlp_exporter("http://localhost:4317", "riverbank")

    # None is returned when neither exporter package is available
    assert result is None


def test_setup_tracing_falls_back_to_console_when_otlp_unavailable() -> None:
    """setup_tracing falls back to ConsoleSpanExporter when OTLP builder returns None."""
    from riverbank import observability

    observability._initialized = False

    with mock.patch.dict(
        os.environ,
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4317"},
    ):
        with mock.patch("riverbank.observability._build_otlp_exporter", return_value=None):
            with mock.patch(
                "riverbank.observability.ConsoleSpanExporter"
            ) as mock_console:
                with mock.patch("riverbank.observability.BatchSpanProcessor"):
                    with mock.patch("riverbank.observability.TracerProvider") as mock_provider_cls:
                        mock_provider = mock.MagicMock()
                        mock_provider_cls.return_value = mock_provider
                        observability.setup_tracing("test-fallback")
                        mock_console.assert_called_once()

    observability._initialized = False
