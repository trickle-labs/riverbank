"""Unit tests for the IngestPipeline (no DB required — uses dry_run=True)."""
from __future__ import annotations

from pathlib import Path

import pytest

from riverbank.pipeline import CompilerProfile, IngestPipeline


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    (tmp_path / "intro.md").write_text(
        "# Introduction\n\nAriadne is an open-source library for managing structured research threads."
    )
    (tmp_path / "concepts.md").write_text(
        "# Concepts\n\n## Confidence\n\nConfidence scores are floats in [0, 1].\n\n"
        "## Evidence\n\nEvidence spans record exact character offsets."
    )
    return tmp_path


def test_dry_run_processes_fragments(corpus_dir: Path) -> None:
    """dry_run=True must parse + fragment but write zero triples."""
    pipeline = IngestPipeline(db_engine=None)
    # Override db access by using a non-existent engine — dry_run won't hit the DB
    # for the actual write path.  We supply a dummy DSN that will raise on connect,
    # but since the DB is only accessed when not dry_run, this is fine...
    # Actually, the current implementation accesses DB even in dry_run for hash checks.
    # We test via a fully-patched path instead.
    stats = _run_dry(pipeline, str(corpus_dir))
    assert stats["fragments_processed"] >= 2
    assert stats["triples_written"] == 0


def test_dry_run_no_llm_calls(corpus_dir: Path) -> None:
    stats = _run_dry(IngestPipeline(db_engine=None), str(corpus_dir))
    assert stats["llm_calls"] == 0


def test_dry_run_on_single_file(corpus_dir: Path) -> None:
    path = str(corpus_dir / "intro.md")
    stats = _run_dry(IngestPipeline(db_engine=None), path)
    assert stats["fragments_processed"] >= 1


def test_short_fragment_skipped_by_gate(tmp_path: Path) -> None:
    (tmp_path / "tiny.md").write_text("# A\n\nHi.")  # too short
    stats = _run_dry(IngestPipeline(db_engine=None), str(tmp_path))
    # "Hi." is below default min_fragment_length=50, so fragment is skipped
    assert stats["fragments_skipped"] >= 1


def test_compiler_profile_default() -> None:
    p = CompilerProfile.default()
    assert p.name == "default"
    assert p.extractor == "noop"


def test_compiler_profile_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "profile.yaml"
    yaml_path.write_text(
        "name: test-profile\nversion: 2\nextractor: noop\nmodel_provider: ollama\n"
        "model_name: llama3.2\nembed_model: nomic-embed-text\nmax_fragment_tokens: 1000\n"
        "named_graph: http://test/graph\nprompt_text: Test prompt.\n"
        "editorial_policy:\n  min_fragment_length: 10\n"
    )
    p = CompilerProfile.from_yaml(yaml_path)
    assert p.name == "test-profile"
    assert p.version == 2
    assert p.max_fragment_tokens == 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_dry(pipeline: IngestPipeline, corpus_path: str) -> dict:
    """Run the pipeline in dry_run mode with a no-op DB stub."""
    import unittest.mock as mock  # noqa: PLC0415

    # Stub the DB context manager so no real connection is attempted
    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with mock.patch.object(pipeline, "_get_db", return_value=fake_conn):
        with mock.patch.object(pipeline, "_get_existing_hashes", return_value={}):
            return pipeline.run(corpus_path=corpus_path, dry_run=True)
