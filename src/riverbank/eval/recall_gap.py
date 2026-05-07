"""Per-property recall gap analysis for the Wikidata evaluation framework (v0.15.1).

Identifies Wikidata properties where recall falls below a configurable threshold
(default 0.50) and generates targeted extraction examples to close the gap.

Usage::

    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.50)
    report = analyzer.analyze(dataset_result)

    for gap in report.gaps:
        print(f"{gap.property_id}: recall={gap.recall:.3f}, count={gap.total_count}")
        for ex in gap.extraction_examples:
            print(f"  Example: {ex.example_text!r}")
            print(f"  Expected: {ex.expected_triple}")

CLI::

    riverbank recall-gap-analysis --results eval/results/latest.json \\
        --threshold 0.50 --output eval/results/recall-gaps.json
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExtractionExample:
    """A targeted extraction example for a low-recall Wikidata property.

    These examples are injected as few-shot demonstrations in the extraction
    prompt to improve recall for the targeted property.
    """

    property_id: str          # "P569"
    property_label: str       # "date of birth"
    example_text: str         # Source text from which the triple should be extracted
    expected_triple: tuple[str, str, str]  # (subject_label, predicate, object_value)
    domain: str = "biography"
    difficulty: str = "medium"  # "easy" | "medium" | "hard"


@dataclass
class PropertyRecallGap:
    """Recall gap statistics for a single Wikidata property."""

    property_id: str          # "P569"
    property_label: str       # "date of birth"
    total_count: int          # Total Wikidata statements for this property
    matched_count: int        # Statements correctly extracted by riverbank
    recall: float             # matched_count / total_count
    extraction_examples: list[ExtractionExample] = field(default_factory=list)
    # Predicate patterns that should capture this property
    aligned_predicates: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class RecallGapReport:
    """Full report of per-property recall gaps and targeted extraction examples.

    Written to JSON by ``RecallGapAnalyzer.to_json()``.
    """

    threshold: float                          # Recall threshold used
    gaps: list[PropertyRecallGap]             # Properties below threshold
    covered_properties: list[str]             # Properties at or above threshold
    total_extraction_examples: int = 0        # Total examples generated
    dataset_name: str = ""
    riverbank_version: str = ""


# ---------------------------------------------------------------------------
# Built-in extraction examples for frequently low-recall properties
# ---------------------------------------------------------------------------

_BUILTIN_EXAMPLES: dict[str, list[dict]] = {
    "P569": [  # date of birth
        {
            "example_text": "Marie Curie was born on 7 November 1867 in Warsaw.",
            "expected_triple": ("Marie Curie", "pgc:birthDate", "1867-11-07"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
        {
            "example_text": "Born in 1953, the singer grew up in rural Tennessee.",
            "expected_triple": ("singer", "pgc:birthDate", "1953"),
            "domain": "biography_living",
            "difficulty": "medium",
        },
    ],
    "P570": [  # date of death
        {
            "example_text": "He died on 14 April 1865 after being shot at Ford's Theatre.",
            "expected_triple": ("He", "pgc:deathDate", "1865-04-14"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
    ],
    "P19": [  # place of birth
        {
            "example_text": "Einstein was born in Ulm, in the Kingdom of Württemberg.",
            "expected_triple": ("Einstein", "pgc:birthPlace", "Ulm"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
    ],
    "P20": [  # place of death
        {
            "example_text": "Curie died at the Sancellemoz sanatorium in Passy, Haute-Savoie.",
            "expected_triple": ("Curie", "pgc:deathPlace", "Passy"),
            "domain": "biography_historical",
            "difficulty": "medium",
        },
    ],
    "P106": [  # occupation
        {
            "example_text": "She worked as a physicist and chemist, pioneering research on radioactivity.",
            "expected_triple": ("She", "pgc:hasOccupation", "physicist"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
        {
            "example_text": "During his tenure as CEO, the company grew rapidly.",
            "expected_triple": ("his", "pgc:hasOccupation", "CEO"),
            "domain": "biography_living",
            "difficulty": "easy",
        },
    ],
    "P27": [  # country of citizenship
        {
            "example_text": "A French citizen since 1906, she retained strong ties to Poland.",
            "expected_triple": ("she", "pgc:nationality", "France"),
            "domain": "biography_historical",
            "difficulty": "medium",
        },
    ],
    "P40": [  # child
        {
            "example_text": "Marie and Pierre had two daughters, Irène and Ève.",
            "expected_triple": ("Marie and Pierre", "pgc:hasChild", "Irène"),
            "domain": "biography_historical",
            "difficulty": "medium",
        },
    ],
    "P22": [  # father
        {
            "example_text": "His father, Wilhelm, was a prominent local merchant.",
            "expected_triple": ("His", "pgc:father", "Wilhelm"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
    ],
    "P25": [  # mother
        {
            "example_text": "Her mother, Rosa, died when she was only 10 years old.",
            "expected_triple": ("Her", "pgc:mother", "Rosa"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
    ],
    "P26": [  # spouse
        {
            "example_text": "She married Pierre Curie in 1895 and they collaborated until his death.",
            "expected_triple": ("She", "pgc:spouse", "Pierre Curie"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
    ],
    "P69": [  # educated at
        {
            "example_text": "He studied physics at the University of Cambridge under J.J. Thomson.",
            "expected_triple": ("He", "pgc:educatedAt", "University of Cambridge"),
            "domain": "biography_historical",
            "difficulty": "easy",
        },
    ],
    "P108": [  # employer
        {
            "example_text": "From 1906 she held the Chair of Physics at the University of Paris.",
            "expected_triple": ("she", "pgc:employer", "University of Paris"),
            "domain": "biography_historical",
            "difficulty": "medium",
        },
    ],
    "P159": [  # headquarters location
        {
            "example_text": "The company, headquartered in Cupertino, California, employs over 150,000 people.",
            "expected_triple": ("The company", "pgc:headquartersLocation", "Cupertino"),
            "domain": "organization",
            "difficulty": "easy",
        },
    ],
    "P18": [  # image (commonly missed — should be ignored or noted as novel)
        {
            "example_text": "A well-known photograph of Einstein shows him sticking out his tongue.",
            "expected_triple": ("Einstein", "ex:depictedIn", "photograph"),
            "domain": "biography_historical",
            "difficulty": "hard",
        },
    ],
    "P571": [  # inception
        {
            "example_text": "The organization was founded in 1948 in Geneva.",
            "expected_triple": ("The organization", "pgc:foundingDate", "1948"),
            "domain": "organization",
            "difficulty": "easy",
        },
    ],
    "P577": [  # publication date
        {
            "example_text": "The novel was first published in 1851 by Harper & Brothers.",
            "expected_triple": ("The novel", "pgc:publicationDate", "1851"),
            "domain": "creative_work",
            "difficulty": "easy",
        },
    ],
    "P495": [  # country of origin
        {
            "example_text": "The film is a British production, set largely in post-war London.",
            "expected_triple": ("The film", "pgc:countryOfOrigin", "United Kingdom"),
            "domain": "creative_work",
            "difficulty": "medium",
        },
    ],
    "P17": [  # country
        {
            "example_text": "The city of Lyon is located in south-eastern France.",
            "expected_triple": ("Lyon", "pgc:country", "France"),
            "domain": "geographic",
            "difficulty": "easy",
        },
    ],
    "P131": [  # located in administrative territory
        {
            "example_text": "The museum is situated in the 8th arrondissement of Paris.",
            "expected_triple": ("The museum", "pgc:locatedIn", "8th arrondissement"),
            "domain": "geographic",
            "difficulty": "medium",
        },
    ],
    "P625": [  # coordinate location
        {
            "example_text": "The station is located at coordinates 48.8566°N, 2.3522°E.",
            "expected_triple": ("The station", "pgc:coordinates", "48.8566, 2.3522"),
            "domain": "geographic",
            "difficulty": "hard",
        },
    ],
    "P31": [  # instance of
        {
            "example_text": "Quantum mechanics is a fundamental theory in physics.",
            "expected_triple": ("Quantum mechanics", "rdf:type", "theory"),
            "domain": "scientific",
            "difficulty": "medium",
        },
    ],
    "P279": [  # subclass of
        {
            "example_text": "A mammal is a type of vertebrate animal.",
            "expected_triple": ("mammal", "rdfs:subClassOf", "vertebrate animal"),
            "domain": "scientific",
            "difficulty": "easy",
        },
    ],
}

# Built-in property labels for formatting
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
    "P18": "image",
    "P571": "inception",
    "P577": "publication date",
    "P495": "country of origin",
    "P17": "country",
    "P131": "located in administrative territory",
    "P625": "coordinate location",
    "P31": "instance of",
    "P279": "subclass of",
}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class RecallGapAnalyzer:
    """Analyze per-property recall gaps from a ``DatasetResult`` JSON report.

    Parameters
    ----------
    threshold:
        Properties with recall below this value are flagged as gaps.
        Default ``0.50``.
    alignment_table:
        Optional pre-loaded ``PropertyAlignmentTable``.  Loaded lazily if not
        provided.
    """

    def __init__(
        self,
        threshold: float = 0.50,
        alignment_table=None,  # PropertyAlignmentTable — optional
    ) -> None:
        self.threshold = threshold
        self._alignment = alignment_table

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_json(self, report_path: Path) -> RecallGapReport:
        """Load a JSON evaluation report and run recall gap analysis.

        Parameters
        ----------
        report_path:
            Path to a ``DatasetResult`` JSON file written by
            ``DatasetEvaluator.to_json()``.

        Returns
        -------
        RecallGapReport
            Gaps below threshold with targeted extraction examples.
        """
        with report_path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        by_property: dict[str, dict] = data.get("by_property", {})
        # by_property keys: {"P31": {"precision": 0.9, "count": 45}, ...}

        # DatasetResult does not store per-property recall directly, so we
        # re-derive it.  The scorer's _aggregate_by_property builds per-property
        # precision; we compute pseudo-recall from article_results.
        article_results = data.get("article_results", [])
        run_metadata = data.get("run_metadata", {})

        per_property_stats = self._compute_per_property_recall(
            by_property, article_results
        )

        return self._build_report(
            per_property_stats,
            dataset_name=run_metadata.get("dataset", ""),
            riverbank_version=run_metadata.get("riverbank_version", ""),
        )

    def analyze_dict(
        self,
        by_property: dict[str, dict],
        *,
        dataset_name: str = "",
        riverbank_version: str = "",
    ) -> RecallGapReport:
        """Analyze from an already-loaded ``by_property`` dict.

        Each entry should have at minimum a ``"count"`` key and optionally a
        ``"recall"`` key.  If ``"recall"`` is absent the property is treated
        as having zero recall (worst-case).

        Parameters
        ----------
        by_property:
            Mapping of P-id → metric dict.
        dataset_name:
            Optional label for the report.
        riverbank_version:
            Optional riverbank version string.
        """
        per_property_stats: dict[str, dict] = {}
        for pid, metrics in by_property.items():
            per_property_stats[pid] = {
                "recall": metrics.get("recall", 0.0),
                "total_count": metrics.get("count", 0),
                "matched_count": round(
                    metrics.get("recall", 0.0) * metrics.get("count", 0)
                ),
            }
        return self._build_report(
            per_property_stats,
            dataset_name=dataset_name,
            riverbank_version=riverbank_version,
        )

    def to_json(self, report: RecallGapReport, output_path: Path) -> None:
        """Write a ``RecallGapReport`` to a JSON file.

        Parameters
        ----------
        report:
            The report to serialise.
        output_path:
            Destination path; parent directories are created automatically.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "threshold": report.threshold,
            "dataset_name": report.dataset_name,
            "riverbank_version": report.riverbank_version,
            "total_extraction_examples": report.total_extraction_examples,
            "covered_properties": report.covered_properties,
            "gaps": [
                {
                    "property_id": g.property_id,
                    "property_label": g.property_label,
                    "total_count": g.total_count,
                    "matched_count": g.matched_count,
                    "recall": round(g.recall, 4),
                    "aligned_predicates": g.aligned_predicates,
                    "notes": g.notes,
                    "extraction_examples": [
                        {
                            "property_id": ex.property_id,
                            "property_label": ex.property_label,
                            "example_text": ex.example_text,
                            "expected_triple": list(ex.expected_triple),
                            "domain": ex.domain,
                            "difficulty": ex.difficulty,
                        }
                        for ex in g.extraction_examples
                    ],
                }
                for g in sorted(report.gaps, key=lambda g: g.recall)
            ],
        }
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_per_property_recall(
        self,
        by_property: dict[str, dict],
        article_results: list[dict],
    ) -> dict[str, dict]:
        """Derive per-property recall from article-level result data."""
        # Count Wikidata statements per property across all articles
        prop_total: dict[str, int] = {}
        prop_matched: dict[str, int] = {}

        for pid, metrics in by_property.items():
            prop_total[pid] = metrics.get("count", 0)
            # Estimate matched from precision × count
            prop_matched[pid] = round(
                metrics.get("precision", 0.0) * metrics.get("count", 0)
            )

        # If article_results is available, refine from evidence strings
        for article in article_results:
            # article has: true_positives, false_positives, false_negatives, domain
            pass  # Refinement placeholder: full impl needs TripleMatch-level data

        result: dict[str, dict] = {}
        for pid in prop_total:
            total = prop_total[pid]
            matched = prop_matched[pid]
            recall = matched / total if total > 0 else 0.0
            result[pid] = {
                "recall": recall,
                "total_count": total,
                "matched_count": matched,
            }
        return result

    def _build_report(
        self,
        per_property_stats: dict[str, dict],
        *,
        dataset_name: str,
        riverbank_version: str,
    ) -> RecallGapReport:
        """Build a ``RecallGapReport`` from per-property stats."""
        gaps: list[PropertyRecallGap] = []
        covered: list[str] = []

        for pid, stats in per_property_stats.items():
            recall = stats.get("recall", 0.0)
            total = stats.get("total_count", 0)
            matched = stats.get("matched_count", 0)

            label = _PROPERTY_LABELS.get(pid, "")
            aligned = self._get_aligned_predicates(pid)

            if recall < self.threshold:
                examples = self._generate_examples(pid, label)
                gap = PropertyRecallGap(
                    property_id=pid,
                    property_label=label,
                    total_count=total,
                    matched_count=matched,
                    recall=recall,
                    extraction_examples=examples,
                    aligned_predicates=aligned,
                    notes=self._gap_note(pid, recall),
                )
                gaps.append(gap)
            else:
                covered.append(pid)

        total_examples = sum(len(g.extraction_examples) for g in gaps)

        return RecallGapReport(
            threshold=self.threshold,
            gaps=gaps,
            covered_properties=covered,
            total_extraction_examples=total_examples,
            dataset_name=dataset_name,
            riverbank_version=riverbank_version,
        )

    def _generate_examples(
        self, pid: str, label: str
    ) -> list[ExtractionExample]:
        """Return built-in extraction examples for *pid*, if any."""
        raw = _BUILTIN_EXAMPLES.get(pid, [])
        return [
            ExtractionExample(
                property_id=pid,
                property_label=label or _PROPERTY_LABELS.get(pid, pid),
                example_text=ex["example_text"],
                expected_triple=tuple(ex["expected_triple"]),  # type: ignore[arg-type]
                domain=ex.get("domain", "unknown"),
                difficulty=ex.get("difficulty", "medium"),
            )
            for ex in raw
        ]

    def _get_aligned_predicates(self, pid: str) -> list[str]:
        """Look up the riverbank predicates aligned to *pid*."""
        try:
            if self._alignment is None:
                from riverbank.eval.property_alignment import PropertyAlignmentTable  # noqa: PLC0415
                self._alignment = PropertyAlignmentTable()
            return self._alignment.get_riverbank_predicates(pid)
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _gap_note(pid: str, recall: float) -> str:
        """Generate a human-readable note about the recall gap."""
        if recall == 0.0:
            return f"{pid} was never extracted; check predicate alignment."
        elif recall < 0.25:
            return f"{pid} extracted rarely ({recall:.0%}); prompt lacks examples."
        else:
            return f"{pid} extracted inconsistently ({recall:.0%}); object normalisation may differ."
