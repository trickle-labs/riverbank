"""Unit tests for Phase 2: CorpusPreprocessor (all heavy deps mocked)."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest import mock

import pytest

from riverbank.preprocessors import (
    ClusterSummary,
    CorpusAnalysis,
    CorpusPreprocessor,
)


# ---------------------------------------------------------------------------
# Minimal profile stand-in
# ---------------------------------------------------------------------------


@dataclass
class _Profile:
    name: str = "test"
    embed_model: str = "all-MiniLM-L6-v2"
    model_name: str = "llama3.2"
    corpus_preprocessing: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "min_docs": 3,
            "target_cluster_size": 2,
            "cache": False,
        }
    )


@dataclass
class _ProfileDisabled:
    corpus_preprocessing: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ClusterSummary / CorpusAnalysis dataclasses
# ---------------------------------------------------------------------------


def test_cluster_summary_defaults() -> None:
    cs = ClusterSummary(cluster_id=0, label="Architecture", doc_iris=[], summary="Docs about arch.")
    assert cs.entity_vocabulary == []
    assert cs.predicate_vocabulary == []


def test_corpus_analysis_doc_summaries_field() -> None:
    ca = CorpusAnalysis(
        corpus_summary="A corpus.",
        clusters=[],
        doc_cluster_map={"http://ex/a": 0},
        _doc_summaries={"http://ex/a": "Summary A"},
    )
    assert ca._doc_summaries["http://ex/a"] == "Summary A"


# ---------------------------------------------------------------------------
# analyze() returns None when disabled or corpus too small
# ---------------------------------------------------------------------------


def test_analyze_returns_none_when_disabled() -> None:
    cp = CorpusPreprocessor()
    result = cp.analyze({"a": "s", "b": "s", "c": "s"}, _ProfileDisabled())
    assert result is None


def test_analyze_returns_none_when_below_min_docs() -> None:
    cp = CorpusPreprocessor()

    @dataclass
    class _P:
        corpus_preprocessing: dict = field(
            default_factory=lambda: {"enabled": True, "min_docs": 10}
        )

    result = cp.analyze({"a": "s", "b": "s"}, _P())
    assert result is None


# ---------------------------------------------------------------------------
# analyze() happy path — all external deps mocked
# ---------------------------------------------------------------------------


def _make_embed_mock(n_docs: int, dim: int = 4):
    """Return a mock SentenceTransformer that produces deterministic unit vectors."""
    import numpy as np

    mock_model = mock.MagicMock()
    mock_model.encode.return_value = np.eye(n_docs, dim)  # orthogonal unit vectors
    return mock_model


def _make_kmeans_mock(labels: list[int]):
    mock_km = mock.MagicMock()
    import numpy as np
    mock_km.fit_predict.return_value = np.array(labels)
    return mock_km


def _make_llm_client_mock(label: str = "Architecture", summary: str = "A cluster summary."):
    from pydantic import BaseModel

    class _ClusterResp(BaseModel):
        label: str
        summary: str

    class _CorpusResp(BaseModel):
        summary: str

    call_count = [0]

    def _side_effect(*args, **kwargs):
        call_count[0] += 1
        response_model = kwargs.get("response_model")
        usage = mock.MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 5
        completion = mock.MagicMock()
        completion.usage = usage
        if response_model is not None and hasattr(response_model, "__name__"):
            name = response_model.__name__
            if "Cluster" in name:
                return _ClusterResp(label=label, summary=summary), completion
        return _CorpusResp(summary="Corpus-wide summary of all clusters."), completion

    mock_client = mock.MagicMock()
    mock_client.chat.completions.create_with_completion.side_effect = _side_effect
    return mock_client


@pytest.fixture
def doc_summaries_6():
    return {
        "http://ex/doc1": "Doc 1 is about architecture and system design.",
        "http://ex/doc2": "Doc 2 describes configuration management.",
        "http://ex/doc3": "Doc 3 covers deployment operations.",
        "http://ex/doc4": "Doc 4 is about architecture patterns.",
        "http://ex/doc5": "Doc 5 explains configuration schemas.",
        "http://ex/doc6": "Doc 6 covers monitoring and operations.",
    }


def test_analyze_returns_corpus_analysis(doc_summaries_6) -> None:
    cp = CorpusPreprocessor()
    mock_model = _make_embed_mock(n_docs=6)
    mock_km = _make_kmeans_mock([0, 1, 2, 0, 1, 2])
    mock_client = _make_llm_client_mock()

    with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
        with mock.patch("sklearn.cluster.KMeans", return_value=mock_km):
            cp._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2"))
            result = cp.analyze(doc_summaries_6, _Profile())

    assert result is not None
    assert isinstance(result, CorpusAnalysis)


def test_analyze_cluster_count(doc_summaries_6) -> None:
    cp = CorpusPreprocessor()
    mock_model = _make_embed_mock(n_docs=6)
    mock_km = _make_kmeans_mock([0, 1, 2, 0, 1, 2])
    mock_client = _make_llm_client_mock()

    with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
        with mock.patch("sklearn.cluster.KMeans", return_value=mock_km):
            cp._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2"))
            result = cp.analyze(doc_summaries_6, _Profile())

    assert result is not None
    assert len(result.clusters) == 3


def test_analyze_doc_cluster_map_covers_all_docs(doc_summaries_6) -> None:
    cp = CorpusPreprocessor()
    mock_model = _make_embed_mock(n_docs=6)
    mock_km = _make_kmeans_mock([0, 1, 2, 0, 1, 2])
    mock_client = _make_llm_client_mock()

    with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
        with mock.patch("sklearn.cluster.KMeans", return_value=mock_km):
            cp._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2"))
            result = cp.analyze(doc_summaries_6, _Profile())

    assert result is not None
    assert set(result.doc_cluster_map.keys()) == set(doc_summaries_6.keys())


def test_analyze_corpus_summary_populated(doc_summaries_6) -> None:
    cp = CorpusPreprocessor()
    mock_model = _make_embed_mock(n_docs=6)
    mock_km = _make_kmeans_mock([0, 1, 2, 0, 1, 2])
    mock_client = _make_llm_client_mock()

    with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
        with mock.patch("sklearn.cluster.KMeans", return_value=mock_km):
            cp._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2"))
            result = cp.analyze(doc_summaries_6, _Profile())

    assert result is not None
    assert len(result.corpus_summary) > 0


def test_analyze_stores_doc_summaries_on_analysis(doc_summaries_6) -> None:
    cp = CorpusPreprocessor()
    mock_model = _make_embed_mock(n_docs=6)
    mock_km = _make_kmeans_mock([0, 1, 2, 0, 1, 2])
    mock_client = _make_llm_client_mock()

    with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
        with mock.patch("sklearn.cluster.KMeans", return_value=mock_km):
            cp._get_llm_client = mock.MagicMock(return_value=(mock_client, "llama3.2"))
            result = cp.analyze(doc_summaries_6, _Profile())

    assert result is not None
    assert result._doc_summaries == doc_summaries_6


def test_analyze_corpus_hash_is_deterministic(doc_summaries_6) -> None:
    h1 = CorpusPreprocessor._hash_corpus(doc_summaries_6)
    h2 = CorpusPreprocessor._hash_corpus(doc_summaries_6)
    assert h1 == h2
    assert len(h1) == 16


def test_analyze_corpus_hash_differs_on_change(doc_summaries_6) -> None:
    h1 = CorpusPreprocessor._hash_corpus(doc_summaries_6)
    modified = {**doc_summaries_6, "http://ex/doc1": "Changed summary."}
    h2 = CorpusPreprocessor._hash_corpus(modified)
    assert h1 != h2


# ---------------------------------------------------------------------------
# analyze() falls back gracefully when sentence-transformers is absent
# ---------------------------------------------------------------------------


def test_analyze_returns_none_on_import_error(doc_summaries_6) -> None:
    cp = CorpusPreprocessor()
    with mock.patch("sentence_transformers.SentenceTransformer", side_effect=ImportError("no sentence_transformers")):
        result = cp.analyze(doc_summaries_6, _Profile())
    assert result is None


# ---------------------------------------------------------------------------
# build_context()
# ---------------------------------------------------------------------------


def _make_analysis() -> CorpusAnalysis:
    return CorpusAnalysis(
        corpus_summary="This corpus covers system architecture and configuration.",
        clusters=[
            ClusterSummary(
                cluster_id=0,
                label="Architecture",
                doc_iris=["http://ex/doc1"],
                summary="Docs about architecture and design patterns.",
                entity_vocabulary=["ex:System", "ex:Component"],
                predicate_vocabulary=["schema:isPartOf", "schema:hasPart"],
            ),
            ClusterSummary(
                cluster_id=1,
                label="Configuration",
                doc_iris=["http://ex/doc2"],
                summary="Docs about configuration schemas.",
            ),
        ],
        doc_cluster_map={"http://ex/doc1": 0, "http://ex/doc2": 1},
        _doc_summaries={"http://ex/doc1": "Doc 1 summary.", "http://ex/doc2": "Doc 2 summary."},
    )


def test_build_context_returns_empty_string_for_none_analysis() -> None:
    cp = CorpusPreprocessor()
    result = cp.build_context("http://ex/doc1", None)
    assert result == ""


def test_build_context_includes_corpus_context() -> None:
    cp = CorpusPreprocessor()
    ctx = cp.build_context("http://ex/doc1", _make_analysis())
    assert "CORPUS CONTEXT" in ctx
    assert "system architecture" in ctx


def test_build_context_includes_cluster_context() -> None:
    cp = CorpusPreprocessor()
    ctx = cp.build_context("http://ex/doc1", _make_analysis())
    assert "CLUSTER CONTEXT" in ctx
    assert "Architecture" in ctx
    assert "ex:System" in ctx


def test_build_context_includes_doc_summary_when_provided() -> None:
    cp = CorpusPreprocessor()
    ctx = cp.build_context("http://ex/doc1", _make_analysis(), doc_summary="This specific doc is about X.")
    assert "DOCUMENT CONTEXT" in ctx
    assert "This specific doc is about X." in ctx


def test_build_context_uses_correct_cluster_for_doc() -> None:
    """doc2 is in cluster 1 (Configuration), not cluster 0 (Architecture)."""
    cp = CorpusPreprocessor()
    ctx = cp.build_context("http://ex/doc2", _make_analysis())
    assert "Configuration" in ctx
    assert "Architecture" not in ctx


def test_build_context_unknown_doc_omits_cluster_section() -> None:
    cp = CorpusPreprocessor()
    ctx = cp.build_context("http://ex/unknown", _make_analysis())
    assert "CORPUS CONTEXT" in ctx
    assert "CLUSTER CONTEXT" not in ctx
