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


class ExtractedEntity(BaseModel):
    """A vocabulary entity extracted during the SKOS vocabulary pass.

    During ``--mode vocabulary`` ingestion the pipeline uses this schema to
    identify canonical concepts from the corpus before any relationship
    extraction.  Each entity is converted to a ``skos:Concept`` and written
    into the ``<vocab>`` named graph so that subsequent full passes can snap
    entity references to canonical preferred-label IRIs.
    """

    concept_iri: str
    preferred_label: str
    alternate_labels: list[str] = Field(default_factory=list)
    scope_note: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: EvidenceSpan

    def to_skos_triples(self, vocab_graph: str = "<vocab>") -> list[ExtractedTriple]:
        """Convert this entity to a list of skos:Concept ExtractedTriples."""
        triples: list[ExtractedTriple] = [
            ExtractedTriple(
                subject=self.concept_iri,
                predicate="rdf:type",
                object_value="skos:Concept",
                confidence=self.confidence,
                evidence=self.evidence,
                named_graph=vocab_graph,
            ),
            ExtractedTriple(
                subject=self.concept_iri,
                predicate="skos:prefLabel",
                object_value=self.preferred_label,
                confidence=self.confidence,
                evidence=self.evidence,
                named_graph=vocab_graph,
            ),
        ]
        for alt in self.alternate_labels:
            triples.append(
                ExtractedTriple(
                    subject=self.concept_iri,
                    predicate="skos:altLabel",
                    object_value=alt,
                    confidence=self.confidence,
                    evidence=self.evidence,
                    named_graph=vocab_graph,
                )
            )
        if self.scope_note:
            triples.append(
                ExtractedTriple(
                    subject=self.concept_iri,
                    predicate="skos:scopeNote",
                    object_value=self.scope_note,
                    confidence=self.confidence,
                    evidence=self.evidence,
                    named_graph=vocab_graph,
                )
            )
        return triples
