"""Unit tests for spaCy NER pre-resolution and vocabulary lookup (v0.5.0)."""
from __future__ import annotations

import unittest.mock as mock

import pytest


def test_ner_entity_dataclass() -> None:
    """NEREntity has the expected fields."""
    from riverbank.ner import NEREntity

    entity = NEREntity(text="Acme Corp", label="ORG", start_char=0, end_char=9)
    assert entity.text == "Acme Corp"
    assert entity.label == "ORG"
    assert entity.start_char == 0
    assert entity.end_char == 9


def test_ner_result_dataclass_defaults_to_empty() -> None:
    """NERResult defaults to an empty entities list."""
    from riverbank.ner import NERResult

    result = NERResult()
    assert result.entities == []


def test_ner_result_dataclass_with_entities() -> None:
    """NERResult stores entities correctly."""
    from riverbank.ner import NEREntity, NERResult

    entities = [NEREntity("London", "GPE", 0, 6)]
    result = NERResult(entities=entities)
    assert len(result.entities) == 1
    assert result.entities[0].label == "GPE"


def test_spacy_ner_extractor_name() -> None:
    """SpacyNERExtractor.name must be 'spacy'."""
    from riverbank.ner import SpacyNERExtractor

    assert SpacyNERExtractor.name == "spacy"


def test_spacy_ner_extractor_falls_back_gracefully_when_not_installed() -> None:
    """When spaCy is not installed, extract() returns an empty NERResult."""
    from riverbank.ner import SpacyNERExtractor

    extractor = SpacyNERExtractor()
    with mock.patch.dict("sys.modules", {"spacy": None}):
        # Force _nlp to be reset so the import is re-attempted
        extractor._nlp = None
        result = extractor.extract("Acme Corporation is based in London.")

    assert result.entities == []


def test_spacy_ner_extractor_returns_ner_result_with_mock_model() -> None:
    """extract() returns a NERResult with entities from the mocked spaCy model."""
    from riverbank.ner import NERResult, SpacyNERExtractor

    mock_ent = mock.MagicMock()
    mock_ent.text = "Acme"
    mock_ent.label_ = "ORG"
    mock_ent.start_char = 0
    mock_ent.end_char = 4

    mock_doc = mock.MagicMock()
    mock_doc.ents = [mock_ent]

    mock_nlp = mock.MagicMock(return_value=mock_doc)
    mock_spacy = mock.MagicMock()
    mock_spacy.load.return_value = mock_nlp

    with mock.patch.dict("sys.modules", {"spacy": mock_spacy}):
        extractor = SpacyNERExtractor()
        extractor._nlp = None  # Force re-load through mock
        extractor._nlp = mock_nlp
        result = extractor.extract("Acme builds products.")

    assert isinstance(result, NERResult)
    assert len(result.entities) == 1
    assert result.entities[0].text == "Acme"
    assert result.entities[0].label == "ORG"


def test_spacy_ner_extractor_default_model_name() -> None:
    """Default model name is 'en_core_web_sm'."""
    from riverbank.ner import SpacyNERExtractor

    extractor = SpacyNERExtractor()
    assert extractor._model_name == "en_core_web_sm"


def test_spacy_ner_extractor_custom_model_name() -> None:
    """Custom model names are accepted."""
    from riverbank.ner import SpacyNERExtractor

    extractor = SpacyNERExtractor(model_name="en_core_web_lg")
    assert extractor._model_name == "en_core_web_lg"


def test_lookup_vocabulary_returns_none_when_pg_ripple_missing() -> None:
    """lookup_vocabulary returns None gracefully when pg_ripple is unavailable."""
    from riverbank.ner import lookup_vocabulary

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "function pg_ripple.skos_label_lookup does not exist"
    )
    result = lookup_vocabulary(conn, "Acme Corporation")
    assert result is None


def test_lookup_vocabulary_returns_iri_when_found() -> None:
    """lookup_vocabulary returns the IRI when the DB returns a match."""
    from riverbank.ner import lookup_vocabulary

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = ("entity:AcmeCorp",)
    result = lookup_vocabulary(conn, "Acme Corp")
    assert result == "entity:AcmeCorp"


def test_lookup_vocabulary_returns_none_when_no_match() -> None:
    """lookup_vocabulary returns None when the DB returns no match."""
    from riverbank.ner import lookup_vocabulary

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    result = lookup_vocabulary(conn, "Unknown Entity")
    assert result is None
