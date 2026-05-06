"""Unit tests for the LabelStudioReviewer plugin (v0.6.0)."""
from __future__ import annotations

import unittest.mock as mock

from riverbank.reviewers.label_studio import (
    HUMAN_REVIEW_GRAPH,
    TEMPLATE_ATOMIC_FACT,
    TEMPLATE_ENSEMBLE_ARBITRATION,
    TEMPLATE_SPAN_EVIDENCE,
    LabelStudioReviewer,
    ReviewDecision,
    ReviewTask,
)


def test_reviewer_name() -> None:
    """LabelStudioReviewer.name must be 'label_studio'."""
    assert LabelStudioReviewer.name == "label_studio"


def test_review_task_dataclass() -> None:
    """ReviewTask stores all fields correctly."""
    task = ReviewTask(
        fragment_iri="fragment:001",
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        confidence=0.72,
        excerpt="Acme is an organisation.",
        template=TEMPLATE_ATOMIC_FACT,
        priority=0.28,
    )
    assert task.fragment_iri == "fragment:001"
    assert task.artifact_iri == "entity:Acme"
    assert task.confidence == 0.72
    assert task.priority == 0.28
    assert task.task_id is None


def test_review_decision_dataclass() -> None:
    """ReviewDecision stores all fields and defaults correctly."""
    decision = ReviewDecision(
        task_id=42,
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        accepted=True,
    )
    assert decision.task_id == 42
    assert decision.accepted is True
    assert decision.corrected is False
    assert decision.named_graph == HUMAN_REVIEW_GRAPH


def test_atomic_fact_template_is_xml() -> None:
    """Atomic-fact labeling config must be non-empty XML."""
    xml = LabelStudioReviewer.atomic_fact_template()
    assert "<View>" in xml
    assert "Choices" in xml
    assert "accept" in xml
    assert "correct" in xml
    assert "reject" in xml


def test_span_evidence_template_is_xml() -> None:
    """Span-evidence template must declare Labels for supporting/contradicting."""
    xml = LabelStudioReviewer.span_evidence_template()
    assert "supporting" in xml
    assert "contradicting" in xml


def test_ensemble_arbitration_template_is_xml() -> None:
    """Ensemble arbitration template must offer model_a / model_b choices."""
    xml = LabelStudioReviewer.ensemble_arbitration_template()
    assert "model_a" in xml
    assert "model_b" in xml
    assert "neither" in xml


def test_template_xml_returns_correct_template() -> None:
    """_template_xml returns the right XML for each template name."""
    assert "supporting" in LabelStudioReviewer._template_xml(TEMPLATE_SPAN_EVIDENCE)
    assert "model_a" in LabelStudioReviewer._template_xml(TEMPLATE_ENSEMBLE_ARBITRATION)
    # Default falls through to atomic-fact
    assert "accept" in LabelStudioReviewer._template_xml(TEMPLATE_ATOMIC_FACT)
    assert "accept" in LabelStudioReviewer._template_xml("unknown-template")


def test_enqueue_returns_none_when_sdk_not_installed() -> None:
    """enqueue() returns None gracefully when label-studio-sdk is absent."""
    reviewer = LabelStudioReviewer(url="http://localhost:8080", api_key="test")
    task = ReviewTask(
        fragment_iri="fragment:001",
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        confidence=0.72,
    )
    with mock.patch.dict("sys.modules", {"label_studio_sdk": None}):
        reviewer._client = None  # reset cached client
        result = reviewer.enqueue(task)
    assert result is None


def test_collect_yields_nothing_when_sdk_not_installed() -> None:
    """collect() yields nothing gracefully when label-studio-sdk is absent."""
    reviewer = LabelStudioReviewer(url="http://localhost:8080", api_key="test")
    with mock.patch.dict("sys.modules", {"label_studio_sdk": None}):
        reviewer._client = None
        decisions = list(reviewer.collect())
    assert decisions == []


def test_enqueue_calls_project_import_tasks() -> None:
    """enqueue() calls project.import_tasks with correct data."""
    reviewer = LabelStudioReviewer(url="http://localhost:8080", api_key="key", project_id=1)

    mock_project = mock.MagicMock()
    mock_project.import_tasks.return_value = [42]

    mock_client = mock.MagicMock()
    mock_client.get_project.return_value = mock_project
    reviewer._client = mock_client

    task = ReviewTask(
        fragment_iri="fragment:001",
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        confidence=0.72,
        excerpt="Acme is an org.",
    )
    task_id = reviewer.enqueue(task)
    assert task_id == 42
    assert mock_project.import_tasks.called


def test_collect_yields_accepted_decision() -> None:
    """collect() yields ReviewDecision for annotated tasks."""
    reviewer = LabelStudioReviewer(url="http://localhost:8080", api_key="key", project_id=1)

    labeled_tasks = [
        {
            "id": 99,
            "data": {
                "fragment_iri": "fragment:001",
                "artifact_iri": "entity:Acme",
                "subject": "entity:Acme",
                "predicate": "rdf:type",
                "object_value": "org:Organization",
                "confidence": 0.72,
                "excerpt": "",
                "priority": 0.28,
            },
            "annotations": [
                {
                    "result": [
                        {
                            "from_name": "decision",
                            "value": {"choices": ["accept"]},
                        }
                    ]
                }
            ],
        }
    ]

    mock_project = mock.MagicMock()
    mock_project.get_labeled_tasks.return_value = labeled_tasks

    mock_client = mock.MagicMock()
    mock_client.get_project.return_value = mock_project
    reviewer._client = mock_client

    decisions = list(reviewer.collect())
    assert len(decisions) == 1
    d = decisions[0]
    assert d.task_id == 99
    assert d.accepted is True
    assert d.subject == "entity:Acme"


def test_write_decision_to_graph_skips_rejected() -> None:
    """write_decision_to_graph returns False for rejected decisions."""
    reviewer = LabelStudioReviewer()
    decision = ReviewDecision(
        task_id=1,
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        accepted=False,
        corrected=False,
    )
    conn = mock.MagicMock()
    result = reviewer.write_decision_to_graph(conn, decision)
    assert result is False
    conn.execute.assert_not_called()


def test_write_decision_to_graph_accepted() -> None:
    """write_decision_to_graph calls load_triples_with_confidence for accepted decisions."""
    reviewer = LabelStudioReviewer()
    decision = ReviewDecision(
        task_id=1,
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        accepted=True,
    )
    conn = mock.MagicMock()

    with mock.patch(
        "riverbank.catalog.graph.load_triples_with_confidence",
        return_value=1,
    ) as mock_load:
        result = reviewer.write_decision_to_graph(conn, decision)

    assert result is True
    assert mock_load.called


def test_reviewer_registered_as_plugin() -> None:
    """LabelStudioReviewer must be discoverable via the plugin entry-point system."""
    from riverbank.plugin import load_plugins

    plugins = load_plugins("reviewers")
    assert "label_studio" in plugins
    assert plugins["label_studio"].name == "label_studio"
