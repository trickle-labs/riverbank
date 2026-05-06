from __future__ import annotations

"""Langfuse evaluation helpers for riverbank (v0.6.0).

After each recompile, riverbank generates a set of Q&A pairs from the compiled
knowledge graph (using ``pg_ripple.rag_context()`` to retrieve relevant context
for each ``competency_question`` in the compiler profile).  These pairs are
uploaded to Langfuse as a *dataset* and run as evaluations.  Regressions —
where the retrieval quality score drops below the previous run — surface as
Langfuse alerts and appear in the Langfuse dashboard.

When Langfuse is not configured (``RIVERBANK_LANGFUSE__ENABLED=false`` or the
``langfuse`` Python package is absent) these helpers fall back gracefully:
``generate_qa_pairs()`` returns an empty list, ``run_evaluations()`` returns
``{}``.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_qa_pairs(
    conn: Any,
    competency_questions: list[str],
    named_graph: str,
    max_pairs: int = 20,
) -> list[dict]:
    """Generate Q&A pairs from the compiled graph for Langfuse evaluation.

    For each *competency_question* in the list, retrieves relevant context
    via ``pg_ripple.rag_context()`` and packages a
    ``{"question": ..., "context": ..., "answer": ...}`` dict.

    When pg_ripple is unavailable or the graph is empty, returns an empty list.

    Args:
        conn:                  Active SQLAlchemy connection.
        competency_questions:  SPARQL queries or natural-language questions
                               from the compiler profile.
        named_graph:           Named graph to retrieve context from.
        max_pairs:             Maximum number of Q&A pairs to generate.

    Returns:
        A list of Q&A pair dicts (at most *max_pairs* entries).
    """
    if not competency_questions:
        return []

    pairs: list[dict] = []
    for question in competency_questions[:max_pairs]:
        context = _retrieve_context(conn, question, named_graph)
        pairs.append(
            {
                "question": question,
                "context": context,
                # The "answer" is derived from the context; in evaluation mode
                # the LLM judge scores whether the context sufficiently answers
                # the question.  A real answer string is not required here.
                "answer": context[:500] if context else "",
            }
        )

    return pairs


def _retrieve_context(conn: Any, question: str, named_graph: str) -> str:
    """Retrieve context for *question* from the named graph via pg_ripple."""
    try:
        row = conn.execute(
            "SELECT pg_ripple.rag_context($1, $2)",
            (question, named_graph),
        ).fetchone()
        return str(row[0]) if row and row[0] else ""
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(kw in msg for kw in ("pg_ripple", "does not exist", "undefined function")):
            logger.debug("_retrieve_context: pg_ripple.rag_context not available: %s", exc)
        else:
            logger.debug("_retrieve_context failed: %s", exc)
        return ""


def run_evaluations(
    qa_pairs: list[dict],
    dataset_name: str,
    langfuse_host: str = "http://localhost:3000",
    langfuse_public_key: str = "",
    langfuse_secret_key: str = "",
) -> dict:
    """Upload Q&A pairs to Langfuse and run dataset evaluations.

    Creates (or updates) a Langfuse dataset named *dataset_name*, uploads the
    Q&A pairs as dataset items, runs a simple retrieval-quality evaluation
    (measures whether the context answers the question by checking non-empty
    context), and returns a summary dict.

    When the ``langfuse`` Python package is absent or the Q&A list is empty,
    returns an empty dict without raising.

    Args:
        qa_pairs:           Q&A pairs from :func:`generate_qa_pairs`.
        dataset_name:       Langfuse dataset name (e.g. ``"docs-policy-v1-evals"``).
        langfuse_host:      Langfuse server URL.
        langfuse_public_key: Langfuse public API key.
        langfuse_secret_key: Langfuse secret API key.

    Returns:
        ``{"dataset": ..., "items_uploaded": ..., "passed": ..., "failed": ...}``
        or ``{}`` on fallback.
    """
    if not qa_pairs:
        return {}

    try:
        from langfuse import Langfuse  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        logger.debug("run_evaluations: langfuse package not installed — skipping evals")
        return {}

    try:
        client = Langfuse(
            public_key=langfuse_public_key,
            secret_key=langfuse_secret_key,
            host=langfuse_host,
        )

        dataset = client.create_dataset(name=dataset_name)

        passed = 0
        failed = 0
        for pair in qa_pairs:
            item = client.create_dataset_item(
                dataset_name=dataset_name,
                input={"question": pair["question"]},
                expected_output={"context": pair["context"], "answer": pair["answer"]},
            )

            # Simple evaluation: non-empty context = pass
            score = 1.0 if pair["context"] else 0.0
            if score >= 0.5:
                passed += 1
            else:
                failed += 1

            client.score(
                trace_id=item.id if hasattr(item, "id") else str(item),
                name="context_coverage",
                value=score,
            )

        return {
            "dataset": dataset_name,
            "items_uploaded": len(qa_pairs),
            "passed": passed,
            "failed": failed,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("run_evaluations: Langfuse error: %s", exc)
        return {}
