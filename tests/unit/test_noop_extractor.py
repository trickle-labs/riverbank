from __future__ import annotations

from riverbank.extractors.noop import ExtractionResult, NoOpExtractor


def test_noop_extractor_returns_empty_result() -> None:
    extractor = NoOpExtractor()
    result = extractor.extract(fragment=None, profile=None, trace=None)
    assert isinstance(result, ExtractionResult)
    assert result.triples == []
    assert result.confidence == 1.0


def test_noop_extractor_name() -> None:
    assert NoOpExtractor.name == "noop"
