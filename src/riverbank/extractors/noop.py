from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class ExtractionResult:
    """Result returned by any extractor.

    The no-op extractor produces an empty result (no triples written to the
    graph).  The Instructor-based extractor (v0.2.0) will populate ``triples``
    with validated Pydantic-model instances ready for graph writing.
    """

    triples: list[Any] = field(default_factory=list)
    confidence: float = 1.0
    diagnostics: dict[str, Any] = field(default_factory=dict)


class NoOpExtractor:
    """Phase 0 no-op extractor.

    Records a run and emits an OTel span but writes nothing to the graph.
    Used to verify orchestration plumbing end-to-end before Phase 1 LLM work.

    Entry point: ``riverbank.extractors = noop = riverbank.extractors.noop:NoOpExtractor``
    """

    name: ClassVar[str] = "noop"

    def extract(self, fragment: object, profile: object, trace: object) -> ExtractionResult:
        return ExtractionResult()
