from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class EvidenceSpan(BaseModel):
    """Citation grounding — exact character offsets and verbatim excerpt.

    Every extracted triple must carry an EvidenceSpan so that claims are
    traceable to their source.  Fabricated excerpts (text not present in the
    source) are rejected at construction time by ``validate_excerpt_present``.
    """

    source_iri: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    excerpt: str
    page_number: Optional[int] = None

    @model_validator(mode="after")
    def validate_range(self) -> "EvidenceSpan":
        if self.char_end <= self.char_start:
            raise ValueError(
                f"char_end ({self.char_end}) must be > char_start ({self.char_start})"
            )
        if not self.excerpt.strip():
            raise ValueError("excerpt must not be empty")
        return self


class ExtractedTriple(BaseModel):
    """A validated RDF triple with confidence score and citation evidence.

    ``named_graph`` defaults to ``<trusted>``; the pipeline routes low-quality
    output to ``<draft>`` based on the SHACL score before writing to the graph.
    """

    subject: str
    predicate: str
    object_value: str  # named object_value to avoid shadowing the built-in
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: EvidenceSpan
    named_graph: str = "<trusted>"
