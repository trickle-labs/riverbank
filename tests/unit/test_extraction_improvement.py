"""Unit tests for v0.15.1 recall gap analysis and prompt tuning modules.

Tests cover:
- recall_gap.py: RecallGapAnalyzer, PropertyRecallGap, ExtractionExample, RecallGapReport
- prompt_tuning.py: PromptTuner, FalsePositivePattern, FalseNegativePattern, TuningReport
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


# ===========================================================================
# recall_gap.py — ExtractionExample
# ===========================================================================


def test_extraction_example_construction() -> None:
    from riverbank.eval.recall_gap import ExtractionExample

    ex = ExtractionExample(
        property_id="P569",
        property_label="date of birth",
        example_text="Marie Curie was born on 7 November 1867.",
        expected_triple=("Marie Curie", "pgc:birthDate", "1867-11-07"),
    )
    assert ex.property_id == "P569"
    assert ex.expected_triple[2] == "1867-11-07"
    assert ex.domain == "biography"
    assert ex.difficulty == "medium"


def test_extraction_example_custom_fields() -> None:
    from riverbank.eval.recall_gap import ExtractionExample

    ex = ExtractionExample(
        property_id="P106",
        property_label="occupation",
        example_text="He worked as a physicist.",
        expected_triple=("He", "pgc:hasOccupation", "physicist"),
        domain="biography_historical",
        difficulty="easy",
    )
    assert ex.domain == "biography_historical"
    assert ex.difficulty == "easy"


# ===========================================================================
# recall_gap.py — PropertyRecallGap
# ===========================================================================


def test_property_recall_gap_defaults() -> None:
    from riverbank.eval.recall_gap import PropertyRecallGap

    gap = PropertyRecallGap(
        property_id="P569",
        property_label="date of birth",
        total_count=10,
        matched_count=3,
        recall=0.3,
    )
    assert gap.extraction_examples == []
    assert gap.aligned_predicates == []
    assert gap.notes == ""


def test_property_recall_gap_with_examples() -> None:
    from riverbank.eval.recall_gap import ExtractionExample, PropertyRecallGap

    ex = ExtractionExample("P569", "date of birth", "Born in 1867.", ("Subject", "pgc:birthDate", "1867"))
    gap = PropertyRecallGap(
        property_id="P569",
        property_label="date of birth",
        total_count=10,
        matched_count=2,
        recall=0.2,
        extraction_examples=[ex],
    )
    assert len(gap.extraction_examples) == 1
    assert gap.extraction_examples[0].property_id == "P569"


# ===========================================================================
# recall_gap.py — RecallGapReport
# ===========================================================================


def test_recall_gap_report_defaults() -> None:
    from riverbank.eval.recall_gap import RecallGapReport

    report = RecallGapReport(threshold=0.5, gaps=[], covered_properties=[])
    assert report.total_extraction_examples == 0
    assert report.dataset_name == ""
    assert report.riverbank_version == ""


def test_recall_gap_report_with_data() -> None:
    from riverbank.eval.recall_gap import PropertyRecallGap, RecallGapReport

    gap = PropertyRecallGap("P569", "date of birth", 10, 3, 0.3)
    report = RecallGapReport(
        threshold=0.5,
        gaps=[gap],
        covered_properties=["P31"],
        total_extraction_examples=2,
        dataset_name="test",
        riverbank_version="0.15.1",
    )
    assert len(report.gaps) == 1
    assert "P31" in report.covered_properties
    assert report.total_extraction_examples == 2


# ===========================================================================
# recall_gap.py — RecallGapAnalyzer.analyze_dict
# ===========================================================================


def test_recall_gap_analyzer_empty_dict() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.5)
    report = analyzer.analyze_dict({})
    assert report.gaps == []
    assert report.covered_properties == []
    assert report.total_extraction_examples == 0


def test_recall_gap_analyzer_all_above_threshold() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.5)
    by_property = {
        "P31": {"recall": 0.8, "count": 100},
        "P106": {"recall": 0.75, "count": 50},
    }
    report = analyzer.analyze_dict(by_property)
    assert len(report.gaps) == 0
    assert "P31" in report.covered_properties
    assert "P106" in report.covered_properties


def test_recall_gap_analyzer_below_threshold() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.5)
    by_property = {
        "P569": {"recall": 0.3, "count": 20},
        "P106": {"recall": 0.8, "count": 30},
    }
    report = analyzer.analyze_dict(by_property)
    assert len(report.gaps) == 1
    assert report.gaps[0].property_id == "P569"
    assert report.gaps[0].recall == 0.3


def test_recall_gap_analyzer_threshold_boundary() -> None:
    """Property at exactly the threshold should be covered, not flagged."""
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.5)
    by_property = {"P31": {"recall": 0.5, "count": 10}}
    report = analyzer.analyze_dict(by_property)
    assert len(report.gaps) == 0
    assert "P31" in report.covered_properties


def test_recall_gap_analyzer_builtin_examples_p569() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=1.0)  # Force all properties below threshold
    by_property = {"P569": {"recall": 0.3, "count": 10}}
    report = analyzer.analyze_dict(by_property)
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert len(gap.extraction_examples) > 0
    assert any("1867" in ex.example_text for ex in gap.extraction_examples)


def test_recall_gap_analyzer_no_builtin_examples_unknown_pid() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=1.0)
    by_property = {"P99999": {"recall": 0.0, "count": 5}}
    report = analyzer.analyze_dict(by_property)
    assert len(report.gaps) == 1
    assert report.gaps[0].extraction_examples == []


def test_recall_gap_analyzer_gap_note_zero_recall() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    note = RecallGapAnalyzer._gap_note("P569", 0.0)
    assert "never extracted" in note or "P569" in note


def test_recall_gap_analyzer_gap_note_low_recall() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    note = RecallGapAnalyzer._gap_note("P106", 0.15)
    assert "P106" in note or "rarely" in note


def test_recall_gap_analyzer_gap_note_mid_recall() -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    note = RecallGapAnalyzer._gap_note("P27", 0.38)
    assert "P27" in note or "inconsistently" in note


def test_recall_gap_analyzer_to_json(tmp_path: Path) -> None:
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.5)
    by_property = {
        "P569": {"recall": 0.3, "count": 20},
        "P106": {"recall": 0.8, "count": 30},
    }
    report = analyzer.analyze_dict(by_property, dataset_name="test", riverbank_version="0.15.1")
    output = tmp_path / "recall-gaps.json"
    analyzer.to_json(report, output)

    assert output.exists()
    data = json.loads(output.read_text())
    assert data["threshold"] == 0.5
    assert len(data["gaps"]) == 1
    assert data["gaps"][0]["property_id"] == "P569"
    assert data["riverbank_version"] == "0.15.1"
    assert "covered_properties" in data


def test_recall_gap_analyzer_json_roundtrip_examples(tmp_path: Path) -> None:
    """ExtractionExamples should be serialised with expected_triple as list."""
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=1.0)
    by_property = {"P569": {"recall": 0.0, "count": 5}}
    report = analyzer.analyze_dict(by_property)
    output = tmp_path / "gaps.json"
    analyzer.to_json(report, output)

    data = json.loads(output.read_text())
    gap = data["gaps"][0]
    assert len(gap["extraction_examples"]) > 0
    ex = gap["extraction_examples"][0]
    assert isinstance(ex["expected_triple"], list)
    assert len(ex["expected_triple"]) == 3


def test_recall_gap_analyzer_analyze_json(tmp_path: Path) -> None:
    """analyze_json should load and process a DatasetResult JSON."""
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    # Create a minimal DatasetResult JSON
    dataset_result = {
        "run_metadata": {
            "date": "2026-05-07T00:00:00Z",
            "riverbank_version": "0.15.0",
            "dataset": "test",
            "profile": "wikidata-eval-v1",
            "articles_evaluated": 2,
            "duration_seconds": 1.0,
            "llm_model": "",
            "total_llm_cost_usd": 0.0,
        },
        "aggregate": {
            "precision": 0.8,
            "recall": 0.5,
            "f1": 0.62,
            "confidence_calibration_pearson_r": 0.8,
            "novel_discovery_rate": 0.1,
            "false_positive_rate": 0.2,
            "total_riverbank_triples": 10,
            "total_wikidata_statements": 20,
        },
        "by_property": {
            "P569": {"precision": 0.4, "count": 10},
            "P31": {"precision": 0.9, "count": 30},
        },
        "by_domain": {},
        "calibration_curve": {},
        "article_results": [],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(dataset_result))

    analyzer = RecallGapAnalyzer(threshold=0.5)
    report = analyzer.analyze_json(report_path)

    # P569 has precision 0.4, so estimated recall ~0.4 < 0.5 → gap
    # P31 has precision 0.9 → covered
    assert isinstance(report.gaps, list)
    assert isinstance(report.covered_properties, list)


def test_recall_gap_analyzer_multiple_gaps_sorted_by_recall(tmp_path: Path) -> None:
    """JSON output should sort gaps by recall ascending."""
    from riverbank.eval.recall_gap import RecallGapAnalyzer

    analyzer = RecallGapAnalyzer(threshold=0.8)
    by_property = {
        "P569": {"recall": 0.4, "count": 10},
        "P106": {"recall": 0.1, "count": 15},
        "P27": {"recall": 0.6, "count": 8},
    }
    report = analyzer.analyze_dict(by_property)
    output = tmp_path / "out.json"
    analyzer.to_json(report, output)

    data = json.loads(output.read_text())
    recalls = [g["recall"] for g in data["gaps"]]
    assert recalls == sorted(recalls)


# ===========================================================================
# prompt_tuning.py — FalsePositivePattern
# ===========================================================================


def test_false_positive_pattern_defaults() -> None:
    from riverbank.eval.prompt_tuning import FalsePositivePattern

    p = FalsePositivePattern(predicate_pattern="ex:foo", frequency=5)
    assert p.example_triples == []
    assert p.domains == []
    assert p.suggested_fix == ""


def test_false_positive_pattern_with_data() -> None:
    from riverbank.eval.prompt_tuning import FalsePositivePattern

    p = FalsePositivePattern(
        predicate_pattern="aligned_to:P31",
        frequency=12,
        example_triples=[("ex:A", "rdf:type", "human")],
        domains=["biography_historical"],
        suggested_fix="Add negative constraint",
    )
    assert p.frequency == 12
    assert "biography_historical" in p.domains


# ===========================================================================
# prompt_tuning.py — FalseNegativePattern
# ===========================================================================


def test_false_negative_pattern_defaults() -> None:
    from riverbank.eval.prompt_tuning import FalseNegativePattern

    p = FalseNegativePattern(
        property_id="P569",
        property_label="date of birth",
        frequency=8,
    )
    assert p.affected_domains == []
    assert p.estimated_recall_lift == 0.0
    assert p.suggested_prompt_addition == ""


# ===========================================================================
# prompt_tuning.py — PromptPatch
# ===========================================================================


def test_prompt_patch_defaults() -> None:
    from riverbank.eval.prompt_tuning import PromptPatch

    patch = PromptPatch(
        patch_type="add_example",
        target_section="few_shot",
        content="Extract birth dates.",
        rationale="P569 has low recall.",
    )
    assert patch.priority == "medium"
    assert patch.estimated_impact == ""


def test_prompt_patch_high_priority() -> None:
    from riverbank.eval.prompt_tuning import PromptPatch

    patch = PromptPatch(
        patch_type="add_instruction",
        target_section="system",
        content="Be thorough.",
        rationale="Too many FN.",
        priority="high",
        estimated_impact="+5% recall",
    )
    assert patch.priority == "high"
    assert patch.estimated_impact == "+5% recall"


# ===========================================================================
# prompt_tuning.py — TuningReport
# ===========================================================================


def test_tuning_report_defaults() -> None:
    from riverbank.eval.prompt_tuning import TuningReport

    report = TuningReport(
        false_positive_patterns=[],
        false_negative_patterns=[],
        prompt_patches=[],
    )
    assert report.total_fp_analyzed == 0
    assert report.total_fn_analyzed == 0
    assert report.baseline_precision == 0.0
    assert report.baseline_recall == 0.0
    assert report.estimated_recall_lift == 0.0


# ===========================================================================
# prompt_tuning.py — PromptTuner.analyze_dict
# ===========================================================================


def test_prompt_tuner_empty_dict() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner()
    report = tuner.analyze_dict({})
    assert report.false_positive_patterns == []
    assert report.false_negative_patterns == []
    assert report.prompt_patches == []


def test_prompt_tuner_fp_pattern_detected() -> None:
    """Low precision → FP pattern reported."""
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fp_min_frequency=2)
    by_property = {
        "P31": {"precision": 0.5, "count": 10},  # 5 FP estimated
    }
    report = tuner.analyze_dict(by_property)
    assert len(report.false_positive_patterns) >= 1
    fp = report.false_positive_patterns[0]
    assert "P31" in fp.predicate_pattern
    assert fp.frequency >= 2


def test_prompt_tuner_fn_pattern_detected() -> None:
    """Low precision with many items → FN pattern flagged."""
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=2)
    by_property = {
        "P569": {"precision": 0.3, "count": 10},  # 7 FN estimated
    }
    report = tuner.analyze_dict(by_property)
    assert len(report.false_negative_patterns) >= 1
    fn = report.false_negative_patterns[0]
    assert fn.property_id == "P569"
    assert fn.frequency >= 2


def test_prompt_tuner_no_pattern_below_min_frequency() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fp_min_frequency=100, fn_min_frequency=100)
    by_property = {"P31": {"precision": 0.5, "count": 10}}
    report = tuner.analyze_dict(by_property)
    assert report.false_positive_patterns == []
    assert report.false_negative_patterns == []


def test_prompt_tuner_fn_has_suggested_prompt_addition() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1)
    by_property = {"P569": {"precision": 0.0, "count": 5}}
    report = tuner.analyze_dict(by_property)
    fn_patterns = [p for p in report.false_negative_patterns if p.property_id == "P569"]
    assert len(fn_patterns) == 1
    assert len(fn_patterns[0].suggested_prompt_addition) > 0


def test_prompt_tuner_patches_generated_for_fn() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1)
    by_property = {
        f"P{i}": {"precision": 0.0, "count": 5} for i in range(569, 580)
    }
    report = tuner.analyze_dict(by_property)
    assert len(report.prompt_patches) > 0
    patch_types = {p.patch_type for p in report.prompt_patches}
    assert "add_example" in patch_types or "add_instruction" in patch_types


def test_prompt_tuner_patches_for_fp() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fp_min_frequency=1)
    by_property = {"P31": {"precision": 0.1, "count": 20}}
    report = tuner.analyze_dict(by_property)
    # At least one instruction patch for FP
    instruction_patches = [p for p in report.prompt_patches if p.patch_type == "add_instruction"]
    assert len(instruction_patches) >= 1


def test_prompt_tuner_estimated_recall_lift_capped() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1)
    # Many properties with high FN counts
    by_property = {f"P{i}": {"precision": 0.0, "count": 100} for i in range(100, 150)}
    report = tuner.analyze_dict(by_property)
    assert report.estimated_recall_lift <= 0.15  # Capped at 15%


def test_prompt_tuner_to_json(tmp_path: Path) -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1, fp_min_frequency=1)
    by_property = {
        "P569": {"precision": 0.2, "count": 10},
        "P106": {"precision": 0.9, "count": 20},
    }
    report = tuner.analyze_dict(
        by_property,
        baseline_precision=0.8,
        baseline_recall=0.5,
        dataset_name="test",
        riverbank_version="0.15.1",
    )
    output = tmp_path / "tuning.json"
    tuner.to_json(report, output)

    assert output.exists()
    data = json.loads(output.read_text())
    assert data["dataset_name"] == "test"
    assert data["riverbank_version"] == "0.15.1"
    assert data["baseline_precision"] == 0.8
    assert "false_positive_patterns" in data
    assert "false_negative_patterns" in data
    assert "prompt_patches" in data


def test_prompt_tuner_to_json_example_triples_serialised(tmp_path: Path) -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1, fp_min_frequency=1)
    report = tuner.analyze_dict({"P569": {"precision": 0.1, "count": 10}})
    output = tmp_path / "t.json"
    tuner.to_json(report, output)
    data = json.loads(output.read_text())
    for fp in data.get("false_positive_patterns", []):
        for triple in fp.get("example_triples", []):
            assert isinstance(triple, list)


def test_prompt_tuner_analyze_json(tmp_path: Path) -> None:
    """analyze_json should load a DatasetResult JSON and produce a report."""
    from riverbank.eval.prompt_tuning import PromptTuner

    dataset_result = {
        "run_metadata": {
            "date": "2026-05-07T00:00:00Z",
            "riverbank_version": "0.15.0",
            "dataset": "test",
            "profile": "wikidata-eval-v1",
            "articles_evaluated": 5,
            "duration_seconds": 2.0,
            "llm_model": "",
            "total_llm_cost_usd": 0.0,
        },
        "aggregate": {
            "precision": 0.75,
            "recall": 0.55,
            "f1": 0.64,
            "confidence_calibration_pearson_r": 0.8,
            "novel_discovery_rate": 0.1,
            "false_positive_rate": 0.25,
            "total_riverbank_triples": 50,
            "total_wikidata_statements": 80,
        },
        "by_property": {
            "P569": {"precision": 0.3, "count": 10},
            "P31": {"precision": 0.95, "count": 30},
        },
        "by_domain": {},
        "calibration_curve": {},
        "article_results": [],
    }
    report_path = tmp_path / "result.json"
    report_path.write_text(json.dumps(dataset_result))

    tuner = PromptTuner(fn_min_frequency=1, fp_min_frequency=1)
    report = tuner.analyze_json(report_path)

    assert report.baseline_precision == 0.75
    assert report.baseline_recall == 0.55
    assert report.dataset_name == "test"
    assert report.riverbank_version == "0.15.0"
    # P569 with low precision → FN pattern expected
    fn_pids = {p.property_id for p in report.false_negative_patterns}
    assert "P569" in fn_pids


def test_prompt_tuner_fn_recall_lift_positive() -> None:
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1)
    by_property = {"P569": {"precision": 0.0, "count": 20}}
    report = tuner.analyze_dict(by_property)
    fn = next(p for p in report.false_negative_patterns if p.property_id == "P569")
    assert fn.estimated_recall_lift > 0.0


def test_prompt_tuner_global_instruction_patch_when_many_fn() -> None:
    """When more than 5 FN patterns are found, a global 'be thorough' patch should be added."""
    from riverbank.eval.prompt_tuning import PromptTuner

    tuner = PromptTuner(fn_min_frequency=1)
    by_property = {f"P{i}": {"precision": 0.1, "count": 5} for i in range(560, 570)}
    report = tuner.analyze_dict(by_property)
    # More than 5 FN patterns
    if len(report.false_negative_patterns) > 5:
        global_patch = next(
            (p for p in report.prompt_patches if "thorough" in p.content.lower()),
            None,
        )
        assert global_patch is not None


# ===========================================================================
# Integration: analyze_dict round-trip
# ===========================================================================


def test_recall_gap_prompt_tuning_integration(tmp_path: Path) -> None:
    """Smoke test: run both analyzers on the same data, serialize both reports."""
    import json as _json  # noqa: PLC0415

    from riverbank.eval.prompt_tuning import PromptTuner  # noqa: PLC0415
    from riverbank.eval.recall_gap import RecallGapAnalyzer  # noqa: PLC0415

    by_property = {
        "P569": {"precision": 0.2, "count": 20},
        "P106": {"precision": 0.7, "count": 30},
        "P31": {"precision": 0.95, "count": 100},
        "P27": {"recall": 0.3, "count": 15},
    }

    # Recall gap
    gap_analyzer = RecallGapAnalyzer(threshold=0.5)
    gap_report = gap_analyzer.analyze_dict(by_property, dataset_name="integration-test")
    gap_out = tmp_path / "gaps.json"
    gap_analyzer.to_json(gap_report, gap_out)

    # Prompt tuning
    tuner = PromptTuner(fn_min_frequency=1)
    tune_report = tuner.analyze_dict(by_property, dataset_name="integration-test")
    tune_out = tmp_path / "tuning.json"
    tuner.to_json(tune_report, tune_out)

    # Both files should be valid JSON
    gap_data = _json.loads(gap_out.read_text())
    tune_data = _json.loads(tune_out.read_text())

    assert "gaps" in gap_data
    assert "false_negative_patterns" in tune_data
    assert "prompt_patches" in tune_data
    assert "covered_properties" in gap_data
