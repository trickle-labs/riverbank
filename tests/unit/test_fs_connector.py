"""Unit tests for the FilesystemConnector."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from riverbank.connectors.fs import FilesystemConnector, SourceRecord


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    (tmp_path / "doc1.md").write_text("# Doc 1\n\nContent of doc 1.")
    (tmp_path / "doc2.md").write_text("# Doc 2\n\nContent of doc 2.")
    (tmp_path / "notes.txt").write_text("plain text — should be excluded by default pattern")
    return tmp_path


def test_discover_yields_markdown_files(corpus_dir: Path) -> None:
    connector = FilesystemConnector()
    records = list(connector.discover({"path": str(corpus_dir)}))
    assert len(records) == 2


def test_discover_yields_source_records(corpus_dir: Path) -> None:
    connector = FilesystemConnector()
    records = list(connector.discover({"path": str(corpus_dir)}))
    assert all(isinstance(r, SourceRecord) for r in records)


def test_source_record_has_iri(corpus_dir: Path) -> None:
    connector = FilesystemConnector()
    records = list(connector.discover({"path": str(corpus_dir)}))
    assert all(r.iri.startswith("file://") for r in records)


def test_source_record_has_content_hash(corpus_dir: Path) -> None:
    connector = FilesystemConnector()
    records = list(connector.discover({"path": str(corpus_dir)}))
    assert all(isinstance(r.content_hash, bytes) for r in records)
    assert all(len(r.content_hash) == 16 for r in records)


def test_discover_custom_pattern(corpus_dir: Path) -> None:
    connector = FilesystemConnector()
    records = list(connector.discover({"path": str(corpus_dir), "patterns": ["**/*.txt"]}))
    assert len(records) == 1


def test_fetch_returns_bytes(corpus_dir: Path) -> None:
    connector = FilesystemConnector()
    records = list(connector.discover({"path": str(corpus_dir)}))
    record = records[0]
    content = connector.fetch(record)
    assert isinstance(content, bytes)
    assert len(content) > 0


def test_connector_name() -> None:
    assert FilesystemConnector.name == "filesystem"
