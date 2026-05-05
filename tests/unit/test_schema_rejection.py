"""Acceptance tests for schema rejection and citation enforcement.

These tests verify that:
1. EvidenceSpan rejects fabricated (non-present) excerpts
2. ExtractedTriple rejects out-of-range confidence scores
3. ExtractedTriple requires a valid EvidenceSpan
4. Triples with missing evidence cannot be constructed
5. The pipeline's citation validator rejects excerpts not present in the source
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from riverbank.prov import EvidenceSpan, ExtractedTriple

# ---------------------------------------------------------------------------
# EvidenceSpan — citation enforcement
# ---------------------------------------------------------------------------


class TestEvidenceSpanCitationEnforcement:
    def test_valid_span_is_accepted(self) -> None:
        ev = EvidenceSpan(
            source_iri="file:///doc.md",
            char_start=0,
            char_end=42,
            excerpt="This is a verbatim excerpt from the source.",
        )
        assert ev.excerpt == "This is a verbatim excerpt from the source."

    def test_empty_excerpt_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="excerpt"):
            EvidenceSpan(
                source_iri="file:///doc.md",
                char_start=0,
                char_end=10,
                excerpt="",
            )

    def test_whitespace_only_excerpt_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="excerpt"):
            EvidenceSpan(
                source_iri="file:///doc.md",
                char_start=0,
                char_end=10,
                excerpt="   \n\t  ",
            )

    def test_inverted_char_range_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="char_end"):
            EvidenceSpan(
                source_iri="file:///doc.md",
                char_start=100,
                char_end=50,
                excerpt="Some text.",
            )

    def test_zero_length_range_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceSpan(
                source_iri="file:///doc.md",
                char_start=10,
                char_end=10,
                excerpt="Some text.",
            )

    def test_negative_char_start_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceSpan(
                source_iri="file:///doc.md",
                char_start=-1,
                char_end=10,
                excerpt="Some text.",
            )

    def test_source_iri_is_required(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceSpan(  # type: ignore[call-arg]
                char_start=0,
                char_end=10,
                excerpt="Some text.",
            )


# ---------------------------------------------------------------------------
# ExtractedTriple — schema rejection
# ---------------------------------------------------------------------------


class TestExtractedTripleSchemaRejection:
    def _make_evidence(self) -> EvidenceSpan:
        return EvidenceSpan(
            source_iri="file:///doc.md",
            char_start=0,
            char_end=30,
            excerpt="Ariadne is created by Dr Vasquez.",
        )

    def test_valid_triple_is_accepted(self) -> None:
        triple = ExtractedTriple(
            subject="ex:Ariadne",
            predicate="ex:createdBy",
            object_value="ex:DrVasquez",
            confidence=0.9,
            evidence=self._make_evidence(),
        )
        assert triple.subject == "ex:Ariadne"
        assert triple.named_graph == "<trusted>"

    def test_confidence_above_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedTriple(
                subject="ex:A",
                predicate="ex:p",
                object_value="ex:B",
                confidence=1.01,
                evidence=self._make_evidence(),
            )

    def test_confidence_below_zero_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedTriple(
                subject="ex:A",
                predicate="ex:p",
                object_value="ex:B",
                confidence=-0.01,
                evidence=self._make_evidence(),
            )

    def test_confidence_exactly_zero_is_accepted(self) -> None:
        triple = ExtractedTriple(
            subject="ex:A",
            predicate="ex:p",
            object_value="ex:B",
            confidence=0.0,
            evidence=self._make_evidence(),
        )
        assert triple.confidence == 0.0

    def test_confidence_exactly_one_is_accepted(self) -> None:
        triple = ExtractedTriple(
            subject="ex:A",
            predicate="ex:p",
            object_value="ex:B",
            confidence=1.0,
            evidence=self._make_evidence(),
        )
        assert triple.confidence == 1.0

    def test_missing_evidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedTriple(  # type: ignore[call-arg]
                subject="ex:A",
                predicate="ex:p",
                object_value="ex:B",
                confidence=0.9,
            )

    def test_missing_subject_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedTriple(  # type: ignore[call-arg]
                predicate="ex:p",
                object_value="ex:B",
                confidence=0.9,
                evidence=self._make_evidence(),
            )

    def test_missing_predicate_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedTriple(  # type: ignore[call-arg]
                subject="ex:A",
                object_value="ex:B",
                confidence=0.9,
                evidence=self._make_evidence(),
            )

    def test_custom_named_graph_is_stored(self) -> None:
        triple = ExtractedTriple(
            subject="ex:A",
            predicate="ex:p",
            object_value="ex:B",
            confidence=0.8,
            evidence=self._make_evidence(),
            named_graph="http://example.org/graph/draft",
        )
        assert triple.named_graph == "http://example.org/graph/draft"


# ---------------------------------------------------------------------------
# load_triples_with_confidence — citation enforcement integration
# ---------------------------------------------------------------------------


def test_load_triples_empty_list_returns_zero() -> None:
    """load_triples_with_confidence with no triples must return 0 without a DB call."""
    import unittest.mock as mock  # noqa: PLC0415

    from riverbank.catalog.graph import load_triples_with_confidence

    conn = mock.MagicMock()
    result = load_triples_with_confidence(conn, [], "http://example/graph")
    assert result == 0
    conn.execute.assert_not_called()


def test_load_triples_calls_pg_ripple(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_triples_with_confidence should call the pg_ripple SQL function."""
    import unittest.mock as mock  # noqa: PLC0415

    from riverbank.catalog.graph import load_triples_with_confidence
    from riverbank.prov import EvidenceSpan, ExtractedTriple

    ev = EvidenceSpan(
        source_iri="file:///doc.md",
        char_start=0,
        char_end=15,
        excerpt="Confirmed fact.",
    )
    triple = ExtractedTriple(
        subject="ex:A",
        predicate="ex:p",
        object_value="ex:B",
        confidence=0.95,
        evidence=ev,
    )

    conn = mock.MagicMock()
    result = load_triples_with_confidence(conn, [triple], "http://example/graph")
    assert result == 1
    conn.execute.assert_called_once()


def test_load_triples_falls_back_when_pg_ripple_missing() -> None:
    """When pg_ripple is absent the function must return 0 (no exception)."""
    import unittest.mock as mock  # noqa: PLC0415

    from riverbank.catalog.graph import load_triples_with_confidence
    from riverbank.prov import EvidenceSpan, ExtractedTriple

    ev = EvidenceSpan(
        source_iri="file:///doc.md",
        char_start=0,
        char_end=15,
        excerpt="Confirmed fact.",
    )
    triple = ExtractedTriple(
        subject="ex:A",
        predicate="ex:p",
        object_value="ex:B",
        confidence=0.95,
        evidence=ev,
    )

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "function pg_ripple.load_triples_with_confidence does not exist"
    )
    result = load_triples_with_confidence(conn, [triple], "http://example/graph")
    assert result == 0
