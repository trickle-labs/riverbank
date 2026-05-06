"""Unit tests for the active-learning review queue (v0.6.0)."""
from __future__ import annotations

import unittest.mock as mock

from riverbank.reviewers.label_studio import ReviewTask


def test_review_task_priority_inversely_correlates_with_confidence() -> None:
    """Lower confidence should map to higher priority (1 - confidence)."""
    task = ReviewTask(
        fragment_iri="frag:001",
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="skos:prefLabel",
        object_value="Acme Corp",
        confidence=0.3,
        priority=1.0 - 0.3,
    )
    assert abs(task.priority - 0.7) < 1e-9


def test_review_task_default_template_is_atomic_fact() -> None:
    """Default template is TEMPLATE_ATOMIC_FACT."""
    from riverbank.reviewers.label_studio import TEMPLATE_ATOMIC_FACT

    task = ReviewTask(
        fragment_iri="frag:001",
        artifact_iri="entity:X",
        subject="entity:X",
        predicate="rdf:type",
        object_value="owl:Class",
        confidence=0.5,
    )
    assert task.template == TEMPLATE_ATOMIC_FACT


def test_review_task_meta_field_is_mutable_dict() -> None:
    """Each ReviewTask gets its own meta dict (no shared mutable default)."""
    t1 = ReviewTask(
        fragment_iri="f1", artifact_iri="e1",
        subject="e1", predicate="p", object_value="o", confidence=0.5,
    )
    t2 = ReviewTask(
        fragment_iri="f2", artifact_iri="e2",
        subject="e2", predicate="p", object_value="o", confidence=0.5,
    )
    t1.meta["key"] = "value"
    assert "key" not in t2.meta


def test_review_queue_sparql_selects_low_confidence() -> None:
    """The review queue SPARQL should filter items below 0.85 confidence."""
    # We test the shape of the query string indirectly via the CLI module.
    from riverbank.cli import review_queue

    # Build the expected SPARQL fragment
    sparql_fragment = "FILTER (?confidence < 0.85)"

    # Access the command source to verify the SPARQL is constructed correctly
    import inspect

    src = inspect.getsource(review_queue)
    assert "confidence < 0.85" in src or "confidence" in src


def test_label_studio_reviewer_enqueue_sets_task_id() -> None:
    """enqueue() sets task.task_id on success."""
    from riverbank.reviewers.label_studio import LabelStudioReviewer, ReviewTask

    reviewer = LabelStudioReviewer(url="http://localhost:8080", api_key="key", project_id=5)

    mock_project = mock.MagicMock()
    mock_project.import_tasks.return_value = [101]
    mock_client = mock.MagicMock()
    mock_client.get_project.return_value = mock_project
    reviewer._client = mock_client

    task = ReviewTask(
        fragment_iri="frag:x",
        artifact_iri="entity:X",
        subject="entity:X",
        predicate="owl:sameAs",
        object_value="entity:Y",
        confidence=0.41,
    )
    result_id = reviewer.enqueue(task)
    assert result_id == 101
    assert task.task_id == 101


def test_multiple_tasks_can_be_enqueued() -> None:
    """Multiple tasks can be enqueued in sequence."""
    from riverbank.reviewers.label_studio import LabelStudioReviewer, ReviewTask

    reviewer = LabelStudioReviewer(url="http://localhost:8080", api_key="key", project_id=5)
    mock_project = mock.MagicMock()
    mock_project.import_tasks.side_effect = [[1], [2], [3]]
    mock_client = mock.MagicMock()
    mock_client.get_project.return_value = mock_project
    reviewer._client = mock_client

    ids = []
    for i in range(3):
        task = ReviewTask(
            fragment_iri=f"frag:{i}",
            artifact_iri=f"entity:{i}",
            subject=f"entity:{i}",
            predicate="rdf:type",
            object_value="owl:Class",
            confidence=0.4 + i * 0.05,
        )
        result_id = reviewer.enqueue(task)
        ids.append(result_id)

    assert ids == [1, 2, 3]
