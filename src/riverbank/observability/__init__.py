from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_initialized: bool = False


def setup_tracing(service_name: str = "riverbank") -> None:
    """Configure the OpenTelemetry TracerProvider.

    Phase 0: exports spans to console (stdout) when no OTLP endpoint is set.
    Phase 1+: set OTEL_EXPORTER_OTLP_ENDPOINT to route spans to Langfuse or
    any compatible collector.
    """
    global _initialized
    if _initialized:
        return

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer(name: str = "riverbank") -> trace.Tracer:
    """Return a named tracer from the configured provider."""
    return trace.get_tracer(name)
