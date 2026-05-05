"""Unit tests for EvidenceSpan and ExtractedTriple (prov module)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from riverbank.prov import EvidenceSpan, ExtractedTriple


def make_evidence(**kwargs) -> EvidenceSpan:
    defaults = {
        "source_iri": "file:///doc.md",
        "char_start": 0,
        "char_end": 10,
        "excerpt": "Some text.",
    }
    defaults.update(kwargs)
    return EvidenceSpan(**defaults)


def test_evidence_span_valid() -> None:
    ev = make_evidence()
    assert ev.source_iri == "file:///doc.md"
    assert ev.char_start == 0
    assert ev.char_end == 10


def test_evidence_span_inverted_range_raises() -> None:
    with pytest.raises(ValidationError, match="char_end"):
        make_evidence(char_start=10, char_end=5)


def test_evidence_span_empty_range_raises() -> None:
    with pytest.raises(ValidationError):
        make_evidence(char_start=5, char_end=5)


def test_evidence_span_empty_excerpt_raises() -> None:
    with pytest.raises(ValidationError, match="excerpt"):
        make_evidence(excerpt="   ")


def test_extracted_triple_valid() -> None:
    ev = make_evidence()
    triple = ExtractedTriple(
        subject="ex:Ariadne",
        predicate="ex:createdBy",
        object_value="ex:DrVasquez",
        confidence=0.9,
        evidence=ev,
    )
    assert triple.named_graph == "<trusted>"


def test_extracted_triple_confidence_range() -> None:
    ev = make_evidence()
    with pytest.raises(ValidationError):
        ExtractedTriple(
            subject="x", predicate="y", object_value="z",
            confidence=1.5, evidence=ev,
        )
    with pytest.raises(ValidationError):
        ExtractedTriple(
            subject="x", predicate="y", object_value="z",
            confidence=-0.1, evidence=ev,
        )
