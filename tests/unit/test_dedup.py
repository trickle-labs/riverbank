"""Unit tests for Post-1: Embedding-Based Entity Deduplication."""
from __future__ import annotations

from dataclasses import dataclass
from unittest import mock


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


def test_entity_cluster_dataclass() -> None:
    from riverbank.postprocessors.dedup import EntityCluster

    cluster = EntityCluster(
        canonical="http://riverbank.example/entities/sesam-dataset",
        aliases=["http://riverbank.example/entities/dataset"],
        label="Sesam Dataset",
        similarity=0.95,
    )
    assert cluster.canonical.endswith("sesam-dataset")
    assert len(cluster.aliases) == 1
    assert cluster.similarity == 0.95


def test_deduplication_result_defaults() -> None:
    from riverbank.postprocessors.dedup import DeduplicationResult

    result = DeduplicationResult()
    assert result.clusters_found == 0
    assert result.sameas_written == 0
    assert result.entities_examined == 0
    assert result.clusters == []


# ---------------------------------------------------------------------------
# _iri_local_name helper
# ---------------------------------------------------------------------------


def test_iri_local_name_hash_separator() -> None:
    from riverbank.postprocessors.dedup import _iri_local_name

    assert _iri_local_name("http://example.org/ns#Concept") == "Concept"


def test_iri_local_name_slash_separator() -> None:
    from riverbank.postprocessors.dedup import _iri_local_name

    assert _iri_local_name("http://riverbank.example/entities/sesam-pipe") == "sesam-pipe"


def test_iri_local_name_no_separator() -> None:
    from riverbank.postprocessors.dedup import _iri_local_name

    assert _iri_local_name("plainname") == "plainname"


# ---------------------------------------------------------------------------
# EntityDeduplicator — no sentence-transformers
# ---------------------------------------------------------------------------


def test_deduplicator_returns_empty_when_no_model() -> None:
    """When sentence-transformers is unavailable, dedup returns an empty result."""
    from riverbank.postprocessors.dedup import EntityDeduplicator

    deduplicator = EntityDeduplicator()

    # Mock _fetch_entity_labels to return something
    with mock.patch.object(
        deduplicator,
        "_fetch_entity_labels",
        return_value={
            "http://ex.org/a": "Alpha",
            "http://ex.org/b": "Beta",
        },
    ):
        # Mock _get_model to simulate missing sentence-transformers
        with mock.patch.object(deduplicator, "_get_model", return_value=False):
            conn = mock.MagicMock()
            result = deduplicator.deduplicate(conn, "http://ex.org/graph/trusted")

    assert result.entities_examined == 2
    assert result.clusters_found == 0
    assert result.sameas_written == 0


def test_deduplicator_returns_empty_when_no_entities() -> None:
    """When there are no entities in the graph, dedup returns an empty result."""
    from riverbank.postprocessors.dedup import EntityDeduplicator

    deduplicator = EntityDeduplicator()

    with mock.patch.object(deduplicator, "_fetch_entity_labels", return_value={}):
        conn = mock.MagicMock()
        result = deduplicator.deduplicate(conn, "http://ex.org/graph/trusted")

    assert result.entities_examined == 0
    assert result.clusters_found == 0


# ---------------------------------------------------------------------------
# EntityDeduplicator._cluster — pure Python, no I/O
# ---------------------------------------------------------------------------


def test_cluster_identical_vectors_merged() -> None:
    """Two entities with identical embeddings form one cluster."""
    try:
        import numpy as np
    except ImportError:
        import pytest
        pytest.skip("numpy not installed")

    from riverbank.postprocessors.dedup import EntityDeduplicator

    deduplicator = EntityDeduplicator(threshold=0.9)
    iris = [
        "http://ex.org/entities/sesam-dataset",
        "http://ex.org/entities/dataset",
    ]
    # Identical unit vectors → cosine similarity 1.0
    vec = np.array([1.0, 0.0, 0.0], dtype=float)
    embeddings = np.stack([vec, vec])

    clusters = deduplicator._cluster(iris, embeddings, threshold=0.9)
    multi = [c for c in clusters if c.aliases]
    assert len(multi) == 1, "Expected one merged cluster"
    # Shorter IRI should be canonical
    assert multi[0].canonical == "http://ex.org/entities/dataset"
    assert "http://ex.org/entities/sesam-dataset" in multi[0].aliases


def test_cluster_orthogonal_vectors_not_merged() -> None:
    """Two entities with orthogonal embeddings (similarity 0.0) stay separate."""
    try:
        import numpy as np
    except ImportError:
        import pytest
        pytest.skip("numpy not installed")

    from riverbank.postprocessors.dedup import EntityDeduplicator

    deduplicator = EntityDeduplicator(threshold=0.9)
    iris = [
        "http://ex.org/entities/alpha",
        "http://ex.org/entities/beta",
    ]
    embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=float)

    clusters = deduplicator._cluster(iris, embeddings, threshold=0.9)
    multi = [c for c in clusters if c.aliases]
    assert len(multi) == 0, "Orthogonal vectors should not be merged"


# ---------------------------------------------------------------------------
# EntityDeduplicator — dry-run does not write
# ---------------------------------------------------------------------------


def test_deduplicator_dry_run_does_not_write() -> None:
    """dry_run=True: clusters are found but owl:sameAs triples are not written."""
    try:
        import numpy as np
    except ImportError:
        import pytest
        pytest.skip("numpy not installed")

    from riverbank.postprocessors.dedup import EntityDeduplicator

    deduplicator = EntityDeduplicator(threshold=0.9)
    iris = ["http://ex.org/entities/a", "http://ex.org/entities/ab"]
    vec = np.array([1.0, 0.0, 0.0], dtype=float)
    embeddings = np.stack([vec, vec])

    mock_model = mock.MagicMock()
    mock_model.encode.return_value = embeddings

    with mock.patch.object(deduplicator, "_fetch_entity_labels", return_value={
        "http://ex.org/entities/a": "A Entity",
        "http://ex.org/entities/ab": "A Entity extended",
    }):
        with mock.patch.object(deduplicator, "_get_model", return_value=mock_model):
            with mock.patch.object(deduplicator, "_write_sameas") as mock_write:
                conn = mock.MagicMock()
                result = deduplicator.deduplicate(conn, "http://ex.org/graph/trusted", dry_run=True)

    mock_write.assert_not_called()
    assert result.sameas_written == 0
    assert result.clusters_found == 1


# ---------------------------------------------------------------------------
# _SameAsTriple helper
# ---------------------------------------------------------------------------


def test_sameas_triple_dataclass() -> None:
    from riverbank.postprocessors.dedup import _SameAsTriple

    t = _SameAsTriple(
        subject="http://ex.org/entities/old",
        predicate="owl:sameAs",
        object_value="http://ex.org/entities/canonical",
        confidence=0.95,
    )
    assert t.subject == "http://ex.org/entities/old"
    assert t.predicate == "owl:sameAs"
    assert t.confidence == 0.95
