"""Extraction prompt tuning driven by false-positive and false-negative patterns (v0.15.1).

Analyses evaluation results from the Wikidata benchmark to identify systematic
failure modes — false positives (hallucinated/misaligned triples) and false
negatives (missed Wikidata statements) — and generates targeted prompt patches
that improve precision and recall.

Usage::

    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner()
    report = tuner.analyze_json(Path("eval/results/latest.json"))

    for fp in report.false_positive_patterns[:5]:
        print(f"FP pattern: predicate={fp.predicate_pattern!r} freq={fp.frequency}")

    for fn in report.false_negative_patterns[:5]:
        print(f"FN pattern: {fn.property_id} ({fn.property_label}) freq={fn.frequency}")

    # Serialise for review
    tuner.to_json(report, Path("eval/results/tuning-report.json"))

CLI::

    riverbank tune-extraction-prompts --results eval/results/latest.json \\
        --output eval/results/tuning-report.json
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FalsePositivePattern:
    """A recurring false-positive pattern identified from evaluation results.

    A false positive is a riverbank triple that does not match any Wikidata
    statement.  Recurring patterns (same predicate prefix or object type)
    indicate systematic over-extraction.
    """

    predicate_pattern: str     # e.g. "ex:" prefix or specific predicate
    frequency: int             # How often this pattern appears as FP
    example_triples: list[tuple[str, str, str]] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    suggested_fix: str = ""    # Human-readable mitigation suggestion


@dataclass
class FalseNegativePattern:
    """A recurring false-negative pattern (missed Wikidata statement).

    A false negative is a Wikidata statement that riverbank failed to extract.
    Recurring patterns for a property indicate the extraction prompt lacks
    appropriate examples or predicate alignment is missing.
    """

    property_id: str           # "P569"
    property_label: str        # "date of birth"
    frequency: int             # How often this property appears as FN
    affected_domains: list[str] = field(default_factory=list)
    suggested_prompt_addition: str = ""  # Suggested few-shot example to add
    estimated_recall_lift: float = 0.0   # Estimated %-point recall improvement


@dataclass
class PromptPatch:
    """A concrete change to apply to an extraction prompt template.

    Each patch corresponds to a single instruction or few-shot example to add
    or remove from the prompt.
    """

    patch_type: str            # "add_instruction" | "add_example" | "remove_instruction"
    target_section: str        # "system" | "few_shot" | "output_format"
    content: str               # The text to add or remove
    rationale: str             # Why this patch is needed
    priority: str = "medium"   # "high" | "medium" | "low"
    estimated_impact: str = "" # Human-readable impact estimate


@dataclass
class TuningReport:
    """Full prompt tuning report derived from evaluation failure analysis."""

    false_positive_patterns: list[FalsePositivePattern]
    false_negative_patterns: list[FalseNegativePattern]
    prompt_patches: list[PromptPatch]

    # Aggregate statistics
    total_fp_analyzed: int = 0
    total_fn_analyzed: int = 0
    dataset_name: str = ""
    riverbank_version: str = ""
    baseline_precision: float = 0.0
    baseline_recall: float = 0.0
    estimated_precision_lift: float = 0.0
    estimated_recall_lift: float = 0.0


# ---------------------------------------------------------------------------
# Property metadata for FN pattern generation
# ---------------------------------------------------------------------------

_PROPERTY_LABELS: dict[str, str] = {
    "P569": "date of birth",
    "P570": "date of death",
    "P19": "place of birth",
    "P20": "place of death",
    "P106": "occupation",
    "P27": "country of citizenship",
    "P40": "child",
    "P22": "father",
    "P25": "mother",
    "P26": "spouse",
    "P69": "educated at",
    "P108": "employer",
    "P159": "headquarters location",
    "P571": "inception",
    "P577": "publication date",
    "P495": "country of origin",
    "P17": "country",
    "P131": "located in administrative territory",
    "P31": "instance of",
    "P279": "subclass of",
    "P361": "part of",
    "P527": "has part",
    "P21": "sex or gender",
}

# Suggested prompt additions per property
_SUGGESTED_PROMPT_ADDITIONS: dict[str, str] = {
    "P569": (
        "Extract birth dates whenever mentioned. Use pgc:birthDate. "
        "Example: 'born on 7 November 1867' → (subject, pgc:birthDate, '1867-11-07')."
    ),
    "P570": (
        "Extract death dates. Use pgc:deathDate. "
        "Example: 'died in 1934' → (subject, pgc:deathDate, '1934')."
    ),
    "P19": (
        "Extract place of birth. Use pgc:birthPlace. "
        "Example: 'born in Warsaw' → (subject, pgc:birthPlace, 'Warsaw')."
    ),
    "P20": (
        "Extract place of death. Use pgc:deathPlace. "
        "Example: 'died in Paris' → (subject, pgc:deathPlace, 'Paris')."
    ),
    "P106": (
        "Extract occupations and roles. Use pgc:hasOccupation. "
        "Example: 'worked as a physicist' → (subject, pgc:hasOccupation, 'physicist')."
    ),
    "P27": (
        "Extract nationality / country of citizenship. Use pgc:nationality. "
        "Example: 'a French citizen' → (subject, pgc:nationality, 'France')."
    ),
    "P26": (
        "Extract spouse relationships. Use pgc:spouse. "
        "Example: 'married Pierre Curie' → (subject, pgc:spouse, 'Pierre Curie')."
    ),
    "P69": (
        "Extract educational institutions. Use pgc:educatedAt. "
        "Example: 'studied at MIT' → (subject, pgc:educatedAt, 'MIT')."
    ),
    "P108": (
        "Extract employer / affiliated organisation. Use pgc:employer. "
        "Example: 'worked at CERN' → (subject, pgc:employer, 'CERN')."
    ),
    "P159": (
        "Extract headquarters location. Use pgc:headquartersLocation. "
        "Example: 'headquartered in Geneva' → (subject, pgc:headquartersLocation, 'Geneva')."
    ),
    "P571": (
        "Extract founding date. Use pgc:foundingDate. "
        "Example: 'founded in 1945' → (subject, pgc:foundingDate, '1945')."
    ),
    "P577": (
        "Extract publication date. Use pgc:publicationDate. "
        "Example: 'published in 1851' → (subject, pgc:publicationDate, '1851')."
    ),
}


# ---------------------------------------------------------------------------
# PromptTuner
# ---------------------------------------------------------------------------


class PromptTuner:
    """Analyse evaluation failures and generate targeted prompt patches.

    Parameters
    ----------
    fp_min_frequency:
        Minimum number of occurrences to report a false-positive pattern.
    fn_min_frequency:
        Minimum number of occurrences to flag a false-negative property.
    """

    def __init__(
        self,
        fp_min_frequency: int = 2,
        fn_min_frequency: int = 2,
    ) -> None:
        self.fp_min_frequency = fp_min_frequency
        self.fn_min_frequency = fn_min_frequency

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_json(self, report_path: Path) -> TuningReport:
        """Analyse a ``DatasetResult`` JSON report for prompt tuning opportunities.

        Parameters
        ----------
        report_path:
            Path to a JSON file written by ``DatasetEvaluator.to_json()``.

        Returns
        -------
        TuningReport
            Identified FP/FN patterns and concrete prompt patches.
        """
        with report_path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        aggregate = data.get("aggregate", {})
        by_property = data.get("by_property", {})
        article_results = data.get("article_results", [])
        run_metadata = data.get("run_metadata", {})

        fp_patterns = self._extract_fp_patterns(by_property)
        fn_patterns = self._extract_fn_patterns(by_property, article_results)
        patches = self._generate_patches(fp_patterns, fn_patterns)

        # Estimate aggregate lift
        est_recall_lift = min(
            0.15,
            sum(p.estimated_recall_lift for p in fn_patterns) / 100.0
            if fn_patterns else 0.0,
        )

        return TuningReport(
            false_positive_patterns=fp_patterns,
            false_negative_patterns=fn_patterns,
            prompt_patches=patches,
            total_fp_analyzed=sum(p.frequency for p in fp_patterns),
            total_fn_analyzed=sum(p.frequency for p in fn_patterns),
            dataset_name=run_metadata.get("dataset", ""),
            riverbank_version=run_metadata.get("riverbank_version", ""),
            baseline_precision=aggregate.get("precision", 0.0),
            baseline_recall=aggregate.get("recall", 0.0),
            estimated_recall_lift=round(est_recall_lift, 4),
        )

    def analyze_dict(
        self,
        by_property: dict[str, dict],
        *,
        baseline_precision: float = 0.0,
        baseline_recall: float = 0.0,
        dataset_name: str = "",
        riverbank_version: str = "",
    ) -> TuningReport:
        """Analyse from an already-loaded ``by_property`` dict.

        Parameters
        ----------
        by_property:
            Mapping of P-id → metric dict (must include ``"count"`` and
            optionally ``"precision"``).
        baseline_precision / baseline_recall:
            Aggregate metrics from the evaluation run.
        dataset_name / riverbank_version:
            Optional labels for the report.
        """
        fp_patterns = self._extract_fp_patterns(by_property)
        fn_patterns = self._extract_fn_patterns(by_property, [])
        patches = self._generate_patches(fp_patterns, fn_patterns)

        est_recall_lift = min(
            0.15,
            sum(p.estimated_recall_lift for p in fn_patterns) / 100.0
            if fn_patterns else 0.0,
        )

        return TuningReport(
            false_positive_patterns=fp_patterns,
            false_negative_patterns=fn_patterns,
            prompt_patches=patches,
            total_fp_analyzed=sum(p.frequency for p in fp_patterns),
            total_fn_analyzed=sum(p.frequency for p in fn_patterns),
            dataset_name=dataset_name,
            riverbank_version=riverbank_version,
            baseline_precision=baseline_precision,
            baseline_recall=baseline_recall,
            estimated_recall_lift=round(est_recall_lift, 4),
        )

    def to_json(self, report: TuningReport, output_path: Path) -> None:
        """Write a ``TuningReport`` to a JSON file.

        Parameters
        ----------
        report:
            The report to serialise.
        output_path:
            Destination path; parent directories are created as needed.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "dataset_name": report.dataset_name,
            "riverbank_version": report.riverbank_version,
            "baseline_precision": report.baseline_precision,
            "baseline_recall": report.baseline_recall,
            "estimated_recall_lift": report.estimated_recall_lift,
            "total_fp_analyzed": report.total_fp_analyzed,
            "total_fn_analyzed": report.total_fn_analyzed,
            "false_positive_patterns": [
                {
                    "predicate_pattern": p.predicate_pattern,
                    "frequency": p.frequency,
                    "example_triples": [list(t) for t in p.example_triples],
                    "domains": p.domains,
                    "suggested_fix": p.suggested_fix,
                }
                for p in report.false_positive_patterns
            ],
            "false_negative_patterns": [
                {
                    "property_id": p.property_id,
                    "property_label": p.property_label,
                    "frequency": p.frequency,
                    "affected_domains": p.affected_domains,
                    "suggested_prompt_addition": p.suggested_prompt_addition,
                    "estimated_recall_lift": p.estimated_recall_lift,
                }
                for p in report.false_negative_patterns
            ],
            "prompt_patches": [
                {
                    "patch_type": p.patch_type,
                    "target_section": p.target_section,
                    "content": p.content,
                    "rationale": p.rationale,
                    "priority": p.priority,
                    "estimated_impact": p.estimated_impact,
                }
                for p in report.prompt_patches
            ],
        }

        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Private analysis helpers
    # ------------------------------------------------------------------

    def _extract_fp_patterns(
        self, by_property: dict[str, dict]
    ) -> list[FalsePositivePattern]:
        """Identify false-positive patterns from per-property metrics.

        Low precision for an aligned property → systematic FP.
        """
        patterns: list[FalsePositivePattern] = []

        for pid, metrics in by_property.items():
            precision = metrics.get("precision", 1.0)
            count = metrics.get("count", 0)
            if count == 0:
                continue

            fp_estimate = round((1.0 - precision) * count)
            if fp_estimate < self.fp_min_frequency:
                continue

            label = _PROPERTY_LABELS.get(pid, pid)
            patterns.append(
                FalsePositivePattern(
                    predicate_pattern=f"aligned_to:{pid}",
                    frequency=fp_estimate,
                    domains=[],
                    suggested_fix=(
                        f"Add negative constraint: if extracting {label!r}, "
                        "require the object to match the expected value type "
                        f"for {pid}.  "
                        "Consider raising the confidence threshold for this predicate."
                    ),
                )
            )

        return sorted(patterns, key=lambda p: -p.frequency)[: 20]

    def _extract_fn_patterns(
        self,
        by_property: dict[str, dict],
        article_results: list[dict],
    ) -> list[FalseNegativePattern]:
        """Identify false-negative patterns.

        A high count with low precision (and thus high FN) or a property that
        appears in the alignment table but has low coverage is flagged.
        """
        patterns: list[FalseNegativePattern] = []

        for pid, metrics in by_property.items():
            count = metrics.get("count", 0)
            precision = metrics.get("precision", 0.0)
            if count == 0:
                continue

            # Estimated FN: not directly available; use (1 - precision) × count
            # as a proxy — properties with many partial/no matches.
            fn_estimate = max(0, count - round(precision * count))
            if fn_estimate < self.fn_min_frequency:
                continue

            label = _PROPERTY_LABELS.get(pid, pid)
            suggestion = _SUGGESTED_PROMPT_ADDITIONS.get(
                pid,
                f"Add a few-shot example showing how to extract {label!r} ({pid}).",
            )

            # Heuristic: each FN = ~0.3 %-point recall lift if fixed
            est_lift = round(min(5.0, fn_estimate * 0.3), 2)

            patterns.append(
                FalseNegativePattern(
                    property_id=pid,
                    property_label=label,
                    frequency=fn_estimate,
                    affected_domains=[],
                    suggested_prompt_addition=suggestion,
                    estimated_recall_lift=est_lift,
                )
            )

        return sorted(patterns, key=lambda p: -p.frequency)[: 20]

    def _generate_patches(
        self,
        fp_patterns: list[FalsePositivePattern],
        fn_patterns: list[FalseNegativePattern],
    ) -> list[PromptPatch]:
        """Generate concrete ``PromptPatch`` objects from FP/FN patterns."""
        patches: list[PromptPatch] = []

        # FN → add few-shot examples (high priority)
        for fn in fn_patterns[:5]:
            suggestion = fn.suggested_prompt_addition
            patches.append(
                PromptPatch(
                    patch_type="add_example",
                    target_section="few_shot",
                    content=suggestion,
                    rationale=(
                        f"{fn.property_id} ({fn.property_label}) missed "
                        f"{fn.frequency} times; adding a targeted example "
                        f"should lift recall by ≈{fn.estimated_recall_lift}%."
                    ),
                    priority="high",
                    estimated_impact=f"+{fn.estimated_recall_lift}% recall",
                )
            )

        # FP → add constraint instructions (medium priority)
        for fp in fp_patterns[:3]:
            patches.append(
                PromptPatch(
                    patch_type="add_instruction",
                    target_section="system",
                    content=fp.suggested_fix,
                    rationale=(
                        f"Pattern '{fp.predicate_pattern}' produced {fp.frequency} "
                        "false positives."
                    ),
                    priority="medium",
                    estimated_impact=f"-{fp.frequency} false positives",
                )
            )

        # Global instruction if many FNs
        if len(fn_patterns) > 5:
            patches.append(
                PromptPatch(
                    patch_type="add_instruction",
                    target_section="system",
                    content=(
                        "Be thorough: extract dates, occupations, locations, and "
                        "relationships whenever they are explicitly stated. "
                        "Prefer explicit evidence over inference."
                    ),
                    rationale=f"{len(fn_patterns)} distinct properties had recall gaps.",
                    priority="high",
                    estimated_impact="Broad recall improvement across multiple properties",
                )
            )

        return patches
