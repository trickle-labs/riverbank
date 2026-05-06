"""Unit tests for sentence-transformers embedding generation (v0.5.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_embedding_generator_name() -> None:
    """EmbeddingGenerator.name must be 'sentence-transformers'."""
    from riverbank.embeddings import EmbeddingGenerator

    assert EmbeddingGenerator.name == "sentence-transformers"


def test_embedding_generator_default_model_name() -> None:
    """Default model is 'all-MiniLM-L6-v2'."""
    from riverbank.embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator()
    assert gen._model_name == "all-MiniLM-L6-v2"


def test_embedding_generator_custom_model_name() -> None:
    """Custom model names are accepted."""
    from riverbank.embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator(model_name="all-mpnet-base-v2")
    assert gen._model_name == "all-mpnet-base-v2"


def test_embedding_generator_falls_back_gracefully_when_not_installed() -> None:
    """generate() returns [] when sentence-transformers is not installed."""
    from riverbank.embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator()
    gen._model = None  # Reset cached model
    with mock.patch.dict(
        "sys.modules",
        {"sentence_transformers": None},
    ):
        gen._model = None  # Force re-attempt
        # Directly simulate the ImportError path
        gen._model = False
        result = gen.generate("Some text for embedding.")

    assert result == []


def test_embedding_generator_returns_list_of_floats() -> None:
    """generate() returns a list of floats when sentence-transformers is available."""
    from riverbank.embeddings import EmbeddingGenerator

    # Use a plain list to simulate the numpy array returned by SentenceTransformer.encode()
    # (supports .tolist() like numpy arrays do)
    class _FakeArray(list):
        def tolist(self):
            return list(self)

    mock_embedding = _FakeArray([0.1, 0.2, 0.3, 0.4])
    mock_model = mock.MagicMock()
    mock_model.encode.return_value = mock_embedding

    gen = EmbeddingGenerator()
    gen._model = mock_model
    result = gen.generate("A sentence about knowledge graphs.")

    assert isinstance(result, list)
    assert len(result) == 4
    assert all(isinstance(v, float) for v in result)


def test_embedding_generator_returns_empty_list_when_model_is_false() -> None:
    """generate() returns [] when _model is False (import failed)."""
    from riverbank.embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator()
    gen._model = False
    result = gen.generate("Test sentence.")
    assert result == []


def test_store_entity_embedding_returns_false_for_empty_embedding() -> None:
    """store_entity_embedding returns False when embedding is empty."""
    from riverbank.embeddings import store_entity_embedding

    conn = mock.MagicMock()
    result = store_entity_embedding(conn, "entity:Acme", [])
    assert result is False
    conn.execute.assert_not_called()


def test_store_entity_embedding_calls_pg_ripple() -> None:
    """store_entity_embedding calls pg_ripple.store_embedding."""
    from riverbank.embeddings import store_entity_embedding

    conn = mock.MagicMock()
    result = store_entity_embedding(conn, "entity:Acme", [0.1, 0.2, 0.3])
    assert result is True
    assert conn.execute.called


def test_store_entity_embedding_falls_back_when_pg_ripple_missing() -> None:
    """store_entity_embedding returns False gracefully when pg_ripple is unavailable."""
    from riverbank.embeddings import store_entity_embedding

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "function pg_ripple.store_embedding does not exist"
    )
    result = store_entity_embedding(conn, "entity:Acme", [0.1, 0.2, 0.3])
    assert result is False
