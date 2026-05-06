"""Unit tests for Langfuse evaluation helpers (v0.6.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_generate_qa_pairs_returns_empty_for_no_questions() -> None:
    """generate_qa_pairs returns [] when competency_questions is empty."""
    from riverbank.langfuse_evals import generate_qa_pairs

    conn = mock.MagicMock()
    result = generate_qa_pairs(conn, [], "http://example.com/graph/trusted")
    assert result == []


def test_generate_qa_pairs_returns_one_pair_per_question() -> None:
    """generate_qa_pairs returns one dict per competency question."""
    from riverbank.langfuse_evals import generate_qa_pairs

    conn = mock.MagicMock()
    questions = [
        "What is Acme's main product?",
        "Who is the CEO of Acme?",
    ]

    with mock.patch("riverbank.langfuse_evals._retrieve_context", return_value="Some context."):
        pairs = generate_qa_pairs(conn, questions, "http://example.com/graph/trusted")

    assert len(pairs) == 2
    for pair in pairs:
        assert "question" in pair
        assert "context" in pair
        assert "answer" in pair


def test_generate_qa_pairs_respects_max_pairs() -> None:
    """generate_qa_pairs returns at most max_pairs items."""
    from riverbank.langfuse_evals import generate_qa_pairs

    conn = mock.MagicMock()
    questions = [f"Question {i}?" for i in range(30)]

    with mock.patch("riverbank.langfuse_evals._retrieve_context", return_value="ctx"):
        pairs = generate_qa_pairs(
            conn, questions, "http://example.com/g", max_pairs=5
        )

    assert len(pairs) == 5


def test_retrieve_context_falls_back_gracefully_without_pg_ripple() -> None:
    """_retrieve_context returns '' when pg_ripple is not available."""
    from riverbank.langfuse_evals import _retrieve_context

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = _retrieve_context(conn, "What is Acme?", "http://example.com/g")
    assert result == ""


def test_retrieve_context_returns_string() -> None:
    """_retrieve_context returns the context string on success."""
    from riverbank.langfuse_evals import _retrieve_context

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = ("Relevant context about Acme.",)

    result = _retrieve_context(conn, "What is Acme?", "http://example.com/g")
    assert result == "Relevant context about Acme."


def test_run_evaluations_returns_empty_dict_for_no_pairs() -> None:
    """run_evaluations returns {} when qa_pairs is empty."""
    from riverbank.langfuse_evals import run_evaluations

    result = run_evaluations([], dataset_name="test-dataset")
    assert result == {}


def test_run_evaluations_returns_empty_dict_without_langfuse() -> None:
    """run_evaluations returns {} gracefully when langfuse is not installed."""
    from riverbank.langfuse_evals import run_evaluations

    pairs = [{"question": "Q?", "context": "Some context.", "answer": "A."}]

    with mock.patch.dict("sys.modules", {"langfuse": None}):
        result = run_evaluations(pairs, dataset_name="test-dataset")

    assert result == {}


def test_run_evaluations_returns_summary_dict() -> None:
    """run_evaluations returns expected summary keys on success."""
    from riverbank.langfuse_evals import run_evaluations

    pairs = [
        {"question": "Q1?", "context": "Context 1.", "answer": "A1."},
        {"question": "Q2?", "context": "", "answer": ""},  # empty context → fail
    ]

    mock_langfuse = mock.MagicMock()
    mock_client_instance = mock.MagicMock()
    mock_langfuse.Langfuse.return_value = mock_client_instance
    mock_client_instance.create_dataset.return_value = mock.MagicMock(name="test-dataset")
    mock_client_instance.create_dataset_item.return_value = mock.MagicMock(id="item-1")

    with mock.patch.dict("sys.modules", {"langfuse": mock_langfuse}):
        result = run_evaluations(
            pairs,
            dataset_name="test-dataset",
            langfuse_public_key="pk",
            langfuse_secret_key="sk",
        )

    assert "dataset" in result
    assert result["dataset"] == "test-dataset"
    assert "items_uploaded" in result
    assert result["items_uploaded"] == 2
    assert "passed" in result
    assert "failed" in result
    # Q1 has context → pass, Q2 has no context → fail
    assert result["passed"] == 1
    assert result["failed"] == 1
