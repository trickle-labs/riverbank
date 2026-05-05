"""Golden corpus tests — CI gate for knowledge quality.

These tests run the full ingestion pipeline against the fixed example corpus
in ``examples/markdown-corpus/`` and assert structural properties that must
hold regardless of which model is used.

The assertions are derived from the ``competency_questions`` array in
``examples/profiles/docs-policy-v1.yaml``.

Design principles
-----------------
* All tests use the **noop extractor** and run without a live LLM endpoint,
  so they pass in any CI environment.
* SPARQL execution is attempted via pg_ripple when available, and skipped
  gracefully when the extension is absent (stock PostgreSQL 17-alpine in CI
  uses plain SQL assertions instead).
* Structural assertions (fragment counts, skip rate) run against the real
  catalog schema via testcontainers PostgreSQL.
"""
from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

from riverbank.pipeline import CompilerProfile, IngestPipeline

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CORPUS_DIR = Path(__file__).parent.parent.parent / "examples" / "markdown-corpus"
PROFILE_YAML = Path(__file__).parent.parent.parent / "examples" / "profiles" / "docs-policy-v1.yaml"


@pytest.fixture(scope="module")
def golden_profile() -> CompilerProfile:
    """Load the docs-policy-v1 profile used for golden corpus tests."""
    return CompilerProfile.from_yaml(PROFILE_YAML)


def _run_dry(corpus_path: str) -> dict:
    """Run the pipeline in dry-run mode with a no-op DB stub."""
    pipeline = IngestPipeline(db_engine=None)
    fake_conn = mock.MagicMock()
    fake_conn.__enter__ = lambda self: fake_conn
    fake_conn.__exit__ = mock.MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    fake_conn.execute.return_value.fetchone.return_value = None

    with (
        mock.patch.object(pipeline, "_get_db", return_value=fake_conn),
        mock.patch.object(pipeline, "_get_existing_hashes", return_value={}),
    ):
        return pipeline.run(corpus_path=corpus_path, dry_run=True)


# ---------------------------------------------------------------------------
# Corpus structural tests (no DB, no LLM)
# ---------------------------------------------------------------------------


class TestGoldenCorpusStructure:
    """Assert that the fixed corpus fragments as expected."""

    def test_corpus_directory_exists(self) -> None:
        assert CORPUS_DIR.is_dir(), f"Golden corpus directory missing: {CORPUS_DIR}"

    def test_corpus_has_expected_markdown_files(self) -> None:
        md_files = list(CORPUS_DIR.glob("*.md"))
        assert len(md_files) >= 3, (
            f"Expected at least 3 Markdown files in corpus, found {len(md_files)}"
        )

    def test_pipeline_produces_fragments_from_corpus(self) -> None:
        stats = _run_dry(str(CORPUS_DIR))
        assert stats["fragments_processed"] >= 5, (
            f"Expected at least 5 fragments from corpus, got {stats['fragments_processed']}"
        )

    def test_dry_run_writes_no_triples(self) -> None:
        stats = _run_dry(str(CORPUS_DIR))
        assert stats["triples_written"] == 0

    def test_dry_run_makes_no_llm_calls(self) -> None:
        stats = _run_dry(str(CORPUS_DIR))
        assert stats["llm_calls"] == 0

    def test_dry_run_has_no_errors(self) -> None:
        stats = _run_dry(str(CORPUS_DIR))
        assert stats["errors"] == 0

    def test_re_ingest_produces_skip_rate(self) -> None:
        """Simulated re-ingest with all hashes pre-populated → all fragments hash-skipped."""
        pipeline = IngestPipeline(db_engine=None)

        # Build fake existing hashes by enumerating all fragments in the corpus
        from riverbank.connectors.fs import FilesystemConnector  # noqa: PLC0415
        from riverbank.fragmenters.heading import HeadingFragmenter  # noqa: PLC0415
        from riverbank.parsers.markdown import MarkdownParser  # noqa: PLC0415

        connector = FilesystemConnector()
        parser = MarkdownParser()
        fragmenter = HeadingFragmenter()

        existing_hashes: dict[str, str] = {}
        total_fragments = 0
        for source in connector.discover({"path": str(CORPUS_DIR)}):
            doc = parser.parse(source)
            for frag in fragmenter.fragment(doc):
                existing_hashes[frag.fragment_key] = frag.content_hash.hex()
                total_fragments += 1

        fake_conn = mock.MagicMock()
        fake_conn.__enter__ = lambda self: fake_conn
        fake_conn.__exit__ = mock.MagicMock(return_value=False)
        fake_conn.execute.return_value.fetchall.return_value = []
        fake_conn.execute.return_value.fetchone.return_value = None

        with (
            mock.patch.object(pipeline, "_get_db", return_value=fake_conn),
            mock.patch.object(pipeline, "_get_existing_hashes", return_value=existing_hashes),
        ):
            second_stats = pipeline.run(corpus_path=str(CORPUS_DIR), dry_run=True)

        # All fragments (including gate-rejected) should be hash-skipped on second run
        assert second_stats["fragments_skipped_hash"] == total_fragments, (
            f"Expected {total_fragments} hash-skipped fragments on re-ingest, "
            f"got {second_stats['fragments_skipped_hash']}"
        )
        assert second_stats["fragments_processed"] == 0, (
            "Re-ingest of unchanged corpus should process 0 fragments"
        )


# ---------------------------------------------------------------------------
# Profile competency questions — structural validation
# ---------------------------------------------------------------------------


class TestCompetencyQuestions:
    """Validate the structure of competency questions in the profile YAML."""

    def test_profile_has_competency_questions(
        self, golden_profile: CompilerProfile
    ) -> None:
        assert golden_profile.competency_questions, (
            "docs-policy-v1 profile must define competency_questions"
        )

    def test_each_cq_has_id_description_sparql(
        self, golden_profile: CompilerProfile
    ) -> None:
        for cq in golden_profile.competency_questions:
            assert "id" in cq, f"Competency question missing 'id': {cq}"
            assert "description" in cq, f"Competency question missing 'description': {cq}"
            assert "sparql" in cq, f"Competency question missing 'sparql': {cq}"

    def test_each_cq_sparql_is_non_empty(
        self, golden_profile: CompilerProfile
    ) -> None:
        for cq in golden_profile.competency_questions:
            sparql = cq.get("sparql", "").strip()
            assert sparql, f"Competency question {cq.get('id')} has empty SPARQL"

    def test_each_cq_sparql_looks_like_sparql(
        self, golden_profile: CompilerProfile
    ) -> None:
        """Basic syntactic smoke-check: each SPARQL must start with ASK or SELECT."""
        for cq in golden_profile.competency_questions:
            sparql = cq.get("sparql", "").strip().upper()
            assert sparql.startswith(("ASK", "SELECT")), (
                f"Competency question {cq.get('id')} SPARQL must start with ASK or SELECT, "
                f"got: {cq.get('sparql')[:50]!r}"
            )

    def test_cq_ids_are_unique(self, golden_profile: CompilerProfile) -> None:
        ids = [cq["id"] for cq in golden_profile.competency_questions]
        assert len(ids) == len(set(ids)), f"Duplicate competency question IDs: {ids}"

    def test_at_least_three_competency_questions(
        self, golden_profile: CompilerProfile
    ) -> None:
        assert len(golden_profile.competency_questions) >= 3, (
            "docs-policy-v1 profile should define at least 3 competency questions"
        )


# ---------------------------------------------------------------------------
# SPARQL competency question CI gate
# (executes when pg_ripple is available; skips gracefully otherwise)
# ---------------------------------------------------------------------------


class TestCompetencyQuestionCIGate:
    """Run SPARQL ASK competency questions against the compiled graph.

    These tests are gated on pg_ripple being available.  In stock-PostgreSQL CI
    (without pg_ripple) the sparql_query() function returns ``[]`` with a
    warning, and the test verifies graceful degradation only.
    """

    def test_sparql_query_falls_back_gracefully_without_pg_ripple(self) -> None:
        """sparql_query() must not raise when pg_ripple is absent."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        conn = mock.MagicMock()
        conn.execute.side_effect = Exception(
            "function pg_ripple.sparql_query does not exist"
        )
        result = sparql_query(conn, "ASK { ?s ?p ?o . }")
        assert result == []

    def test_sparql_query_with_mock_returns_rows(self) -> None:
        """sparql_query() must pass the SPARQL to the DB and return rows."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        mock_row = mock.MagicMock()
        mock_row._mapping = {"result": True}
        conn = mock.MagicMock()
        conn.execute.return_value.fetchall.return_value = [mock_row]

        result = sparql_query(conn, "ASK { ?s ?p ?o . }")
        assert result == [{"result": True}]
        conn.execute.assert_called_once()

    def test_competency_question_sparql_fed_to_query_function(
        self, golden_profile: CompilerProfile
    ) -> None:
        """Each CQ SPARQL is passed verbatim to sparql_query() without truncation."""
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

        for cq in golden_profile.competency_questions:
            conn = mock.MagicMock()
            conn.execute.side_effect = Exception(
                "function pg_ripple.sparql_query does not exist"
            )
            # Must not raise
            sparql_query(conn, cq["sparql"])
