from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterator

logger = logging.getLogger(__name__)

# Named graph that receives corrections from human reviewers
HUMAN_REVIEW_GRAPH = "http://riverbank.example/graph/human-review"

# Labeling template names
TEMPLATE_ATOMIC_FACT = "atomic-fact-correction"
TEMPLATE_SPAN_EVIDENCE = "span-evidence-annotation"
TEMPLATE_ENSEMBLE_ARBITRATION = "ensemble-disagreement-arbitration"


@dataclass
class ReviewTask:
    """A single review task submitted to Label Studio.

    Attributes:
        task_id:       The Label Studio task ID (set after creation).
        fragment_iri:  IRI of the source fragment.
        artifact_iri:  IRI of the compiled artifact under review.
        subject:       Triple subject IRI.
        predicate:     Triple predicate IRI.
        object_value:  Triple object value or IRI.
        confidence:    Extraction confidence score [0, 1].
        excerpt:       Verbatim evidence excerpt from the source.
        template:      Which labeling template to use.
        priority:      Task priority score (centrality × uncertainty).
        meta:          Arbitrary extra metadata.
    """

    fragment_iri: str
    artifact_iri: str
    subject: str
    predicate: str
    object_value: str
    confidence: float
    excerpt: str = ""
    template: str = TEMPLATE_ATOMIC_FACT
    priority: float = 0.0
    task_id: int | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class ReviewDecision:
    """A completed review decision received from Label Studio.

    Attributes:
        task_id:        The Label Studio task ID.
        artifact_iri:   IRI of the artifact being reviewed.
        subject:        Triple subject IRI.
        predicate:      Triple predicate IRI.
        object_value:   Corrected object value (may differ from original).
        accepted:       True when the reviewer accepted the extraction.
        corrected:      True when the reviewer changed the object value.
        reviewer_note:  Free-text annotation from the reviewer.
        named_graph:    Target named graph for corrected triples.
    """

    task_id: int
    artifact_iri: str
    subject: str
    predicate: str
    object_value: str
    accepted: bool
    corrected: bool = False
    reviewer_note: str = ""
    named_graph: str = HUMAN_REVIEW_GRAPH


class LabelStudioReviewer:
    """Label Studio review back-end for the human-in-the-loop pipeline.

    Creates one Label Studio task per review-queue item, pre-labels it with
    the LLM extraction, receives webhook decisions, and routes corrections into
    the ``<human-review>`` named graph via pg_ripple.

    Custom labeling templates:
    - ``atomic-fact-correction``: reviewer can accept, reject, or edit a single
      triple (subject / predicate / object).
    - ``span-evidence-annotation``: reviewer marks exact character spans as
      supporting, contradicting, or irrelevant evidence.
    - ``ensemble-disagreement-arbitration``: side-by-side view of two model
      outputs; reviewer picks the correct one or writes a third version.

    When ``label_studio_sdk`` (``label-studio-sdk``) is not installed the
    reviewer falls back gracefully: ``enqueue()`` logs a warning and returns
    ``None``; ``collect()`` yields nothing.

    Configuration is taken from the settings object or from the environment
    variables ``RIVERBANK_LABEL_STUDIO__URL``,
    ``RIVERBANK_LABEL_STUDIO__API_KEY``, and
    ``RIVERBANK_LABEL_STUDIO__PROJECT_ID``.
    """

    name: ClassVar[str] = "label_studio"

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str = "",
        project_id: int | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._project_id = project_id
        self._client: Any = None  # label_studio_sdk.Client, lazily initialised

    # ------------------------------------------------------------------
    # Labeling template definitions
    # ------------------------------------------------------------------

    @staticmethod
    def atomic_fact_template() -> str:
        """Return the Label Studio labeling config XML for atomic-fact correction."""
        return """\
<View>
  <Header value="Review extracted triple"/>
  <Text name="subject"   value="$subject"/>
  <Text name="predicate" value="$predicate"/>
  <TextArea name="object_value" toName="subject"
            value="$object_value" editable="true" rows="2"/>
  <Choices name="decision" toName="subject" choice="single">
    <Choice value="accept"  alias="accept"  />
    <Choice value="correct" alias="correct" />
    <Choice value="reject"  alias="reject"  />
  </Choices>
  <TextArea name="note" toName="subject" placeholder="Optional reviewer note" rows="2"/>
</View>"""

    @staticmethod
    def span_evidence_template() -> str:
        """Return the labeling config XML for span-based evidence annotation."""
        return """\
<View>
  <Header value="Annotate evidence span"/>
  <Text name="text" value="$excerpt"/>
  <Labels name="span_label" toName="text">
    <Label value="supporting"    background="green"/>
    <Label value="contradicting" background="red"/>
    <Label value="irrelevant"    background="grey"/>
  </Labels>
</View>"""

    @staticmethod
    def ensemble_arbitration_template() -> str:
        """Return the labeling config XML for ensemble disagreement arbitration."""
        return """\
<View>
  <Header value="Arbitrate model disagreement"/>
  <Text name="model_a" value="$model_a_output"/>
  <Text name="model_b" value="$model_b_output"/>
  <Choices name="decision" toName="model_a" choice="single">
    <Choice value="model_a" alias="model_a"/>
    <Choice value="model_b" alias="model_b"/>
    <Choice value="neither" alias="neither"/>
  </Choices>
  <TextArea name="corrected_value" toName="model_a"
            placeholder="Enter corrected value if neither is acceptable" rows="2"/>
</View>"""

    # ------------------------------------------------------------------
    # Core reviewer protocol
    # ------------------------------------------------------------------

    def enqueue(self, task: ReviewTask) -> int | None:
        """Submit a review task to Label Studio.

        Pre-labels the task with the LLM extraction result so that reviewers
        start from the model's best guess and correct only what is wrong.

        Returns the Label Studio task ID on success, or ``None`` when the SDK
        is unavailable or the task could not be created.
        """
        client = self._get_client()
        if client is None:
            logger.warning(
                "LabelStudioReviewer: label-studio-sdk not available or not configured "
                "— task for %r not submitted",
                task.fragment_iri,
            )
            return None

        project = self._get_or_create_project(client, task.template)
        if project is None:
            return None

        data = {
            "fragment_iri": task.fragment_iri,
            "artifact_iri": task.artifact_iri,
            "subject": task.subject,
            "predicate": task.predicate,
            "object_value": task.object_value,
            "confidence": task.confidence,
            "excerpt": task.excerpt,
            "priority": task.priority,
        }
        data.update(task.meta)

        try:
            result = project.import_tasks([{"data": data}])
            if result and len(result) > 0:
                created_id = result[0] if isinstance(result[0], int) else result[0].get("id")
                task.task_id = created_id
                logger.info(
                    "LabelStudioReviewer: task %d created for artifact %r",
                    created_id,
                    task.artifact_iri,
                )
                return created_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("LabelStudioReviewer: failed to import task: %s", exc)

        return None

    def collect(self) -> Iterator[ReviewDecision]:
        """Yield completed review decisions from Label Studio.

        Polls the configured project for tasks with completed annotations and
        converts each annotation into a :class:`ReviewDecision`.  Decisions
        whose tasks have no annotations are skipped.
        """
        client = self._get_client()
        if client is None:
            return

        project = self._get_project(client)
        if project is None:
            return

        try:
            tasks = project.get_labeled_tasks()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LabelStudioReviewer: could not fetch labeled tasks: %s", exc)
            return

        for ls_task in tasks:
            data = ls_task.get("data", {}) if isinstance(ls_task, dict) else {}
            annotations = (
                ls_task.get("annotations", []) if isinstance(ls_task, dict) else []
            )
            if not annotations:
                continue

            # Use the first completed annotation
            annotation = annotations[0]
            result_items = annotation.get("result", []) if isinstance(annotation, dict) else []

            decision_value = "accept"
            corrected_object = data.get("object_value", "")
            reviewer_note = ""

            for item in result_items:
                if not isinstance(item, dict):
                    continue
                from_name = item.get("from_name", "")
                value = item.get("value", {})
                if from_name == "decision":
                    choices = value.get("choices", [])
                    if choices:
                        decision_value = choices[0]
                elif from_name == "object_value":
                    texts = value.get("text", [])
                    if texts:
                        corrected_object = texts[0]
                elif from_name == "note":
                    texts = value.get("text", [])
                    if texts:
                        reviewer_note = texts[0]

            accepted = decision_value == "accept"
            corrected = decision_value == "correct" and corrected_object != data.get(
                "object_value", ""
            )

            yield ReviewDecision(
                task_id=ls_task.get("id", 0) if isinstance(ls_task, dict) else 0,
                artifact_iri=data.get("artifact_iri", ""),
                subject=data.get("subject", ""),
                predicate=data.get("predicate", ""),
                object_value=corrected_object,
                accepted=accepted,
                corrected=corrected,
                reviewer_note=reviewer_note,
            )

    def write_decision_to_graph(
        self,
        conn: Any,
        decision: ReviewDecision,
    ) -> bool:
        """Write a review decision as triples into the ``<human-review>`` named graph.

        Inserts an ``rdf:Statement`` with the reviewed triple and attaches
        ``pgc:reviewedBy``, ``pgc:reviewOutcome``, and ``pgc:reviewNote``
        annotations.

        Falls back gracefully when pg_ripple is not available.
        """
        if not decision.accepted and not decision.corrected:
            # Rejected — do not write to the graph
            logger.debug(
                "LabelStudioReviewer: task %d rejected — not writing to graph",
                decision.task_id,
            )
            return False

        from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415

        # Build a minimal triple-like object compatible with load_triples_with_confidence.
        # Evidence is intentionally absent (human-reviewed facts have no character span).
        class _ReviewedTriple:
            __slots__ = ("subject", "predicate", "object_value", "confidence", "named_graph", "evidence")

            def __init__(self, subject: str, predicate: str, object_value: str,
                         confidence: float, named_graph: str) -> None:
                self.subject = subject
                self.predicate = predicate
                self.object_value = object_value
                self.confidence = confidence
                self.named_graph = named_graph
                self.evidence = None  # no char-span for human reviews

        triple = _ReviewedTriple(
            subject=decision.subject,
            predicate=decision.predicate,
            object_value=decision.object_value,
            confidence=1.0,  # human-reviewed → maximum confidence
            named_graph=decision.named_graph,
        )

        count = load_triples_with_confidence(conn, [triple], decision.named_graph)
        return count > 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Return an initialised label_studio_sdk.Client, or None."""
        if self._client is not None:
            return self._client
        try:
            import label_studio_sdk as ls_sdk  # noqa: PLC0415

            self._client = ls_sdk.Client(url=self._url, api_key=self._api_key)
            return self._client
        except ImportError:
            logger.debug(
                "label-studio-sdk not installed — LabelStudioReviewer running in stub mode"
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("LabelStudioReviewer: could not connect to Label Studio: %s", exc)
            return None

    def _get_or_create_project(self, client: Any, template: str) -> Any:
        """Return the Label Studio project, creating it if it doesn't exist."""
        if self._project_id is not None:
            return self._get_project(client)

        project_title = f"riverbank-review-{template}"
        labeling_config = self._template_xml(template)

        try:
            project = client.start_project(
                title=project_title,
                label_config=labeling_config,
            )
            self._project_id = project.id
            return project
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LabelStudioReviewer: could not create project %r: %s", project_title, exc
            )
            return None

    def _get_project(self, client: Any) -> Any:
        """Return the configured Label Studio project."""
        if self._project_id is None:
            return None
        try:
            return client.get_project(self._project_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LabelStudioReviewer: could not get project %d: %s", self._project_id, exc
            )
            return None

    @staticmethod
    def _template_xml(template: str) -> str:
        """Return the labeling config XML for the given template name."""
        if template == TEMPLATE_SPAN_EVIDENCE:
            return LabelStudioReviewer.span_evidence_template()
        if template == TEMPLATE_ENSEMBLE_ARBITRATION:
            return LabelStudioReviewer.ensemble_arbitration_template()
        return LabelStudioReviewer.atomic_fact_template()
