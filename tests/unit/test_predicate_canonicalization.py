"""Unit tests for v0.15.5 — Embedding-based predicate canonicalization.

Covers:
- EmbeddingPredicateCanonicali.canonicalize() returns (triples, int, int)
- _dbscan_cluster() groups similar vectors correctly
- Protected namespace predicates are never remapped
- Singleton clusters produce no rewrites
- canon_map correctly maps non-canonical → canonical predicates
- NormalisationConfig has embedding_canonicalization fields with correct defaults
- NormalisationResult has predicates_canonicalized and predicate_clusters_merged fields
- VocabularyNormalisationPass.from_profile() reads embedding_canonicalization config
- VocabularyNormalisationPass.run() calls embedding pass when enabled
- Pipeline stats include predicates_canonicalized and predicate_clusters_merged
- EmbeddingPredicateCanonicali falls back gracefully when no embedder is available
- _pick_canonical() uses frequency as tiebreaker when LLM disabled
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from riverbank.vocabulary import (
    EmbeddingPredicateCanonicali,
    NormalisationConfig,
    NormalisationResult,
    VocabularyNormalisationPass,
)
from riverbank.prov import EvidenceSpan, ExtractedTriple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ev() -> EvidenceSpan:
    return EvidenceSpan(
        source_iri="file:///doc.md",
        char_start=0,
        char_end=10,
        excerpt="Some text.",
    )


def _triple(subject: str, predicate: str, object_value: str, confidence: float = 0.9) -> ExtractedTriple:
    return ExtractedTriple(
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        confidence=confidence,
        evidence=_ev(),
        named_graph="http://test/graph",
    )


# ---------------------------------------------------------------------------
# NormalisationConfig defaults
# ---------------------------------------------------------------------------


def test_config_has_embedding_canonicalization_field() -> None:
    cfg = NormalisationConfig()
    assert hasattr(cfg, "embedding_canonicalization")
    assert cfg.embedding_canonicalization is False


def test_config_embedding_canonicalization_threshold_default() -> None:
    cfg = NormalisationConfig()
    assert cfg.embedding_canonicalization_threshold == 0.88


def test_config_embedding_canonicalization_model_default() -> None:
    cfg = NormalisationConfig()
    assert cfg.embedding_canonicalization_model == "nomic-embed-text"


def test_config_embedding_canonicalization_llm_rename_default() -> None:
    cfg = NormalisationConfig()
    assert cfg.embedding_canonicalization_llm_rename is True


def test_config_embedding_canonicalization_custom() -> None:
    cfg = NormalisationConfig(
        embedding_canonicalization=True,
        embedding_canonicalization_threshold=0.75,
        embedding_canonicalization_model="all-MiniLM-L6-v2",
        embedding_canonicalization_llm_rename=False,
    )
    assert cfg.embedding_canonicalization is True
    assert cfg.embedding_canonicalization_threshold == 0.75
    assert cfg.embedding_canonicalization_model == "all-MiniLM-L6-v2"
    assert cfg.embedding_canonicalization_llm_rename is False


# ---------------------------------------------------------------------------
# NormalisationResult fields
# ---------------------------------------------------------------------------


def test_result_has_new_fields() -> None:
    r = NormalisationResult(triples=[])
    assert hasattr(r, "predicates_canonicalized")
    assert hasattr(r, "predicate_clusters_merged")
    assert r.predicates_canonicalized == 0
    assert r.predicate_clusters_merged == 0


# ---------------------------------------------------------------------------
# VocabularyNormalisationPass.from_profile reads embedding config
# ---------------------------------------------------------------------------


def test_from_profile_embedding_canonicalization_disabled_by_default() -> None:
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    profile = CompilerProfile(
        name="test",
        vocabulary_normalisation={"enabled": True},
    )
    vn_pass = VocabularyNormalisationPass.from_profile(profile)
    assert vn_pass._embedding_canonicali is None


def test_from_profile_embedding_canonicalization_enabled() -> None:
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    profile = CompilerProfile(
        name="test",
        vocabulary_normalisation={
            "enabled": True,
            "embedding_canonicalization": True,
            "embedding_canonicalization_threshold": 0.80,
            "embedding_canonicalization_model": "all-MiniLM-L6-v2",
            "embedding_canonicalization_llm_rename": False,
        },
    )
    vn_pass = VocabularyNormalisationPass.from_profile(profile)
    assert vn_pass._embedding_canonicali is not None
    assert vn_pass._embedding_canonicali._threshold == 0.80
    assert vn_pass._embedding_canonicali._model_name == "all-MiniLM-L6-v2"
    assert vn_pass._embedding_canonicali._llm_rename is False


# ---------------------------------------------------------------------------
# EmbeddingPredicateCanonicali — unit tests
# ---------------------------------------------------------------------------


def test_canonicalize_empty_triples() -> None:
    ec = EmbeddingPredicateCanonicali(llm_rename=False)
    result, n_rewrites, n_clusters = ec.canonicalize([])
    assert result == []
    assert n_rewrites == 0
    assert n_clusters == 0


def test_canonicalize_single_predicate_no_cluster() -> None:
    """A single predicate cannot form a cluster — no rewrites."""
    ec = EmbeddingPredicateCanonicali(llm_rename=False)
    triples = [_triple("ex:Alice", "ex:born_in", "ex:Warsaw")]
    result, n_rewrites, n_clusters = ec.canonicalize(triples)
    assert n_rewrites == 0
    assert n_clusters == 0
    assert result[0].predicate == "ex:born_in"


def test_canonicalize_no_embedder_returns_original() -> None:
    """When no embedder is available, triples pass through unchanged."""
    ec = EmbeddingPredicateCanonicali(
        model_name="nonexistent-model",
        llm_rename=False,
    )
    # Force _get_embedder to return None
    ec._embedder = None
    with patch.object(ec, "_make_ollama_embedder", return_value=None), \
         patch.object(ec, "_make_st_embedder", return_value=None):
        triples = [
            _triple("ex:Alice", "ex:born_in", "ex:Warsaw"),
            _triple("ex:Alice", "ex:was_born_in", "ex:Warsaw"),
        ]
        result, n_rewrites, n_clusters = ec.canonicalize(triples)
    assert n_rewrites == 0
    assert n_clusters == 0


def test_canonicalize_protected_namespace_predicates_not_remapped() -> None:
    """owl:, rdf:, rdfs: predicates must never be remapped."""
    ec = EmbeddingPredicateCanonicali(llm_rename=False)
    owl_type = "http://www.w3.org/2002/07/owl#sameAs"
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    triples = [
        _triple("ex:Alice", owl_type, "ex:Bob"),
        _triple("ex:Alice", rdf_type, "ex:Person"),
    ]
    # Inject a dummy embedder that clusters everything
    def _dummy_embedder(labels):
        return [[1.0, 0.0] for _ in labels]

    ec._embedder = _dummy_embedder
    result, n_rewrites, n_clusters = ec.canonicalize(triples)
    # Both predicates are protected — neither should be remapped
    preds = {t.predicate for t in result}
    assert owl_type in preds
    assert rdf_type in preds
    assert n_rewrites == 0


# ---------------------------------------------------------------------------
# DBSCAN clustering
# ---------------------------------------------------------------------------


def test_dbscan_cluster_high_similarity_grouped() -> None:
    """Predicates with very similar embeddings should end up in one cluster."""
    ec = EmbeddingPredicateCanonicali(threshold=0.85, llm_rename=False)
    preds = ["ex:born_in", "ex:was_born_in", "ex:birthplace"]
    # All identical vectors → cosine similarity = 1.0
    vecs = [[1.0, 0.0, 0.0]] * 3
    clusters = ec._dbscan_cluster(preds, vecs, 0.85)
    # All three should be in the same cluster
    merged = [c for c in clusters if len(c) >= 2]
    assert len(merged) == 1
    assert len(merged[0]) == 3


def test_dbscan_cluster_low_similarity_singletons() -> None:
    """Predicates with orthogonal embeddings should each be their own cluster."""
    ec = EmbeddingPredicateCanonicali(threshold=0.85, llm_rename=False)
    preds = ["ex:born_in", "ex:employed_by", "ex:located_in"]
    # Orthogonal vectors
    vecs = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    clusters = ec._dbscan_cluster(preds, vecs, 0.85)
    # No multi-member clusters
    multi = [c for c in clusters if len(c) >= 2]
    assert len(multi) == 0
    # All three predicates accounted for
    all_preds = [p for c in clusters for p in c]
    assert set(all_preds) == set(preds)


def test_dbscan_cluster_mixed() -> None:
    """Two similar predicates cluster together; a third stays separate."""
    ec = EmbeddingPredicateCanonicali(threshold=0.90, llm_rename=False)
    preds = ["ex:born_in", "ex:was_born_in", "ex:employed_by"]
    # born_in and was_born_in are very close; employed_by is different
    import math  # noqa: PLC0415
    angle = math.radians(5)  # 5° apart → cosine ~0.996
    vecs = [
        [1.0, 0.0],
        [math.cos(angle), math.sin(angle)],
        [0.0, 1.0],  # 90° from born_in
    ]
    clusters = ec._dbscan_cluster(preds, vecs, 0.90)
    multi = [c for c in clusters if len(c) >= 2]
    assert len(multi) == 1
    assert "ex:born_in" in multi[0]
    assert "ex:was_born_in" in multi[0]
    assert "ex:employed_by" not in multi[0]


# ---------------------------------------------------------------------------
# _pick_canonical — frequency-based tiebreaker
# ---------------------------------------------------------------------------


def test_pick_canonical_frequency_fallback() -> None:
    """When llm_rename=False, the most-frequent predicate is canonical."""
    from collections import Counter  # noqa: PLC0415

    ec = EmbeddingPredicateCanonicali(llm_rename=False)
    cluster = ["ex:born_in", "ex:was_born_in", "ex:birthplace"]
    freq: Counter = Counter({"ex:was_born_in": 5, "ex:born_in": 3, "ex:birthplace": 1})
    canonical = ec._pick_canonical(cluster, freq)
    assert canonical == "ex:was_born_in"


def test_pick_canonical_tiebreaker_shorter_iri() -> None:
    """When frequencies are equal, the shorter IRI wins."""
    from collections import Counter  # noqa: PLC0415

    ec = EmbeddingPredicateCanonicali(llm_rename=False)
    cluster = ["ex:born_in", "ex:was_born_in"]
    freq: Counter = Counter({"ex:born_in": 3, "ex:was_born_in": 3})
    canonical = ec._pick_canonical(cluster, freq)
    # "ex:born_in" is shorter → wins tiebreaker
    assert canonical == "ex:born_in"


# ---------------------------------------------------------------------------
# Full canonicalization pass with injected embedder
# ---------------------------------------------------------------------------


def test_canonicalize_rewrites_cluster_members() -> None:
    """Verifies end-to-end rewrite when embedder clusters two predicates."""
    ec = EmbeddingPredicateCanonicali(threshold=0.85, llm_rename=False)

    triples = [
        _triple("ex:Alice", "ex:born_in", "ex:Warsaw"),
        _triple("ex:Alice", "ex:born_in", "ex:Warsaw"),
        _triple("ex:Alice", "ex:was_born_in", "ex:Warsaw"),  # synonym
        _triple("ex:Alice", "ex:works_at", "ex:CNRS"),
    ]

    # Inject embedder: born_in and was_born_in cluster (identical vectors),
    # works_at is orthogonal.
    def _embedder(labels: list[str]) -> list[list[float]]:
        result = []
        for lbl in labels:
            if "born" in lbl:
                result.append([1.0, 0.0, 0.0])
            else:
                result.append([0.0, 1.0, 0.0])
        return result

    ec._embedder = _embedder
    result_triples, n_rewrites, n_clusters = ec.canonicalize(triples)

    # was_born_in should be rewritten to born_in (more frequent: 2 vs 1)
    pred_set = {t.predicate for t in result_triples}
    assert "ex:was_born_in" not in pred_set
    assert "ex:born_in" in pred_set
    assert n_rewrites == 1
    assert n_clusters == 1


def test_canonicalize_preserves_unrelated_predicates() -> None:
    """Predicates that don't cluster are preserved unchanged."""
    ec = EmbeddingPredicateCanonicali(threshold=0.95, llm_rename=False)

    triples = [
        _triple("ex:Alice", "ex:born_in", "ex:Warsaw"),
        _triple("ex:Alice", "ex:works_at", "ex:CNRS"),
        _triple("ex:Alice", "ex:nationality", "ex:French"),
    ]

    # All orthogonal — no clusters
    def _embedder(labels: list[str]) -> list[list[float]]:
        vecs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        return vecs[: len(labels)]

    ec._embedder = _embedder
    result_triples, n_rewrites, n_clusters = ec.canonicalize(triples)
    assert n_rewrites == 0
    assert n_clusters == 0
    orig_preds = {t.predicate for t in triples}
    result_preds = {t.predicate for t in result_triples}
    assert orig_preds == result_preds


# ---------------------------------------------------------------------------
# VocabularyNormalisationPass.run() with embedding pass enabled
# ---------------------------------------------------------------------------


def test_vocab_pass_run_calls_embedding_canonicali_when_enabled() -> None:
    """When embedding_canonicalization=True, the pass calls the canonicali."""
    cfg = NormalisationConfig(
        embedding_canonicalization=True,
        embedding_canonicalization_llm_rename=False,
    )
    vn_pass = VocabularyNormalisationPass(cfg)

    # Replace with a mock that records calls
    mock_canonicali = MagicMock()
    mock_canonicali.canonicalize = MagicMock(return_value=([], 0, 0))
    vn_pass._embedding_canonicali = mock_canonicali

    triples = [_triple("ex:Alice", "ex:born_in", "ex:Warsaw")]
    vn_pass.run(triples)

    mock_canonicali.canonicalize.assert_called_once()


def test_vocab_pass_run_skips_embedding_pass_when_disabled() -> None:
    """When embedding_canonicalization=False (default), the pass is None."""
    cfg = NormalisationConfig(embedding_canonicalization=False)
    vn_pass = VocabularyNormalisationPass(cfg)
    assert vn_pass._embedding_canonicali is None

    triples = [_triple("ex:Alice", "ex:born_in", "ex:Warsaw")]
    result = vn_pass.run(triples)
    assert result.predicates_canonicalized == 0
    assert result.predicate_clusters_merged == 0


def test_vocab_pass_result_counts_embedding_stats() -> None:
    """predicates_canonicalized and predicate_clusters_merged are populated."""
    cfg = NormalisationConfig(
        embedding_canonicalization=True,
        embedding_canonicalization_llm_rename=False,
    )
    vn_pass = VocabularyNormalisationPass(cfg)

    triples = [_triple("ex:Alice", "ex:born_in", "ex:Warsaw")]
    mock_canonicali = MagicMock()
    mock_canonicali.canonicalize = MagicMock(return_value=(triples, 3, 2))
    vn_pass._embedding_canonicali = mock_canonicali

    result = vn_pass.run(triples)
    assert result.predicates_canonicalized == 3
    assert result.predicate_clusters_merged == 2


# ---------------------------------------------------------------------------
# Pipeline stats keys
# ---------------------------------------------------------------------------


def test_pipeline_stats_include_canonicalization_keys() -> None:
    """IngestPipeline.run() returns a dict with the new v0.15.5 stats."""
    import unittest.mock as mock  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from riverbank.pipeline import CompilerProfile, IngestPipeline  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        p = _Path(tmp) / "doc.md"
        p.write_text("# A\n\n" + "x" * 100)

        pipeline = IngestPipeline(db_engine=None)
        profile = CompilerProfile(name="test")

        fake_conn = mock.MagicMock()
        fake_conn.__enter__ = lambda self: fake_conn
        fake_conn.__exit__ = mock.MagicMock(return_value=False)
        fake_conn.execute.return_value.fetchall.return_value = []
        fake_conn.execute.return_value.fetchone.return_value = None

        with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
            with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
                stats = pipeline.run(corpus_path=str(p), profile=profile)

    assert "predicates_canonicalized" in stats
    assert "predicate_clusters_merged" in stats
    assert isinstance(stats["predicates_canonicalized"], int)
    assert isinstance(stats["predicate_clusters_merged"], int)


# ---------------------------------------------------------------------------
# Profile YAML round-trip
# ---------------------------------------------------------------------------


def test_profile_yaml_embedding_canonicalization(tmp_path) -> None:
    """CompilerProfile.from_yaml() reads embedding_canonicalization settings."""
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    yaml_content = """\
name: test-embed-canon
extractor: noop
vocabulary_normalisation:
  enabled: true
  embedding_canonicalization: true
  embedding_canonicalization_threshold: 0.80
  embedding_canonicalization_model: all-MiniLM-L6-v2
  embedding_canonicalization_llm_rename: false
"""
    yaml_path = tmp_path / "profile.yaml"
    yaml_path.write_text(yaml_content)

    profile = CompilerProfile.from_yaml(str(yaml_path))
    vn_cfg = profile.vocabulary_normalisation
    assert vn_cfg.get("embedding_canonicalization") is True
    assert vn_cfg.get("embedding_canonicalization_threshold") == 0.80
    assert vn_cfg.get("embedding_canonicalization_model") == "all-MiniLM-L6-v2"
    assert vn_cfg.get("embedding_canonicalization_llm_rename") is False
