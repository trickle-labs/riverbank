from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from riverbank.extractors.noop import ExtractionResult, NoOpExtractor


def test_noop_extractor_returns_empty_result() -> None:
    extractor = NoOpExtractor()
    result = extractor.extract(fragment=None, profile=None, trace=None)
    assert isinstance(result, ExtractionResult)
    assert result.triples == []
    assert result.confidence == 1.0


def test_noop_extractor_name() -> None:
    assert NoOpExtractor.name == "noop"


def test_noop_extractor_emits_otel_span() -> None:
    """extract() must emit exactly one OTel span named 'noop_extractor.extract'."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    original_provider = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)
    try:
        extractor = NoOpExtractor()
        extractor.extract(fragment=None, profile=None, trace=None)

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "noop_extractor.extract" in span_names
    finally:
        trace.set_tracer_provider(original_provider)
