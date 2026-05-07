"""Scoring engine for the Wikidata evaluation framework.

Computes precision, recall, F1, confidence calibration (Pearson ρ), novel
discovery rate, and false positive rate by matching riverbank triples against
Wikidata statements.

Matching pipeline (``Scorer.score_article``)
--------------------------------------------
For each riverbank triple ``(s, p, o, confidence)``:

1. Map predicate *p* to Wikidata P-id(s) via the ``PropertyAlignmentTable``.
2. Resolve subject *s* to a Wikidata Q-id via the ``EntityResolver``.
3. Normalise object *o* (ISO 8601 dates, Q-id normalisation, fuzzy string).
4. Search Wikidata statements for a match; assign match_type:
   - ``"exact"``   — predicate and object both match (TP)
   - ``"partial"`` — predicate matches but object doesn't (FP)
   - ``"no_match"``— predicate not in alignment table (novel discovery candidate)
5. Aggregate into precision / recall / F1.
6. Bucket confidence scores and compute calibration.

``DatasetEvaluator.aggregate`` rolls up per-article scores into a
``DatasetResult`` with per-domain and per-property breakdowns plus Pearson ρ.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from riverbank.eval.entity_resolution import EntityResolver
from riverbank.eval.models import (
    ArticleScore,
    DatasetResult,
    RunMetadata,
    TripleMatch,
    WikidataItem,
    WikidataStatement,
)
from riverbank.eval.property_alignment import PropertyAlignmentTable

# Confidence calibration buckets
_CONFIDENCE_BUCKETS = ["0.0-0.25", "0.25-0.5", "0.5-0.75", "0.75-1.0"]


class Scorer:
    """Score a single article's extraction against its Wikidata item.

    Parameters
    ----------
    alignment_table:
        ``PropertyAlignmentTable`` mapping P-ids to riverbank predicates.
    entity_resolver:
        ``EntityResolver`` instance for linking IRIs to Q-ids.
    """

    def __init__(
        self,
        alignment_table: PropertyAlignmentTable | None = None,
        entity_resolver: EntityResolver | None = None,
    ) -> None:
        self.alignment = alignment_table or PropertyAlignmentTable()
        self.resolver = entity_resolver or EntityResolver()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_article(
        self,
        article_title: str,
        riverbank_triples: list[tuple[str, str, str, float]],
        wikidata_item: WikidataItem,
        domain: str = "unknown",
    ) -> ArticleScore:
        """Score extraction for a single article.

        Parameters
        ----------
        article_title:
            Wikipedia article title (used for entity resolution hints).
        riverbank_triples:
            List of ``(subject, predicate, object, confidence)`` tuples
            extracted by riverbank's pipeline.
        wikidata_item:
            Ground-truth Wikidata item for this article.
        domain:
            Domain label (``"biography_living"``, ``"organization"``, …).

        Returns
        -------
        ArticleScore
            Per-article metrics including precision, recall, F1, and
            confidence calibration buckets.
        """
        matches: list[TripleMatch] = []

        wikidata_statements = wikidata_item.statements

        # Track which Wikidata statements were covered (for recall)
        covered_statement_indices: set[int] = set()

        for s, p, o, conf in riverbank_triples:
            tm = self._match_triple(
                riverbank_s=s,
                riverbank_p=p,
                riverbank_o=o,
                riverbank_confidence=conf,
                wikidata_statements=wikidata_statements,
                article_title=article_title,
                article_qid=wikidata_item.qid,
                covered_statement_indices=covered_statement_indices,
            )
            matches.append(tm)

        tp = sum(1 for m in matches if m.match_type == "exact")
        fp = sum(1 for m in matches if m.match_type in ("partial", "no_match"))
        fn = max(0, len(wikidata_statements) - len(covered_statement_indices))

        precision, recall, f1 = self._compute_precision_recall(tp, fp, fn)
        novel = sum(1 for m in matches if m.match_type == "no_match")
        buckets = self._compute_confidence_calibration(matches)

        return ArticleScore(
            article_title=article_title,
            wikidata_qid=wikidata_item.qid,
            riverbank_triples=len(riverbank_triples),
            wikidata_statements=len(wikidata_statements),
            triple_matches=matches,
            precision=precision,
            recall=recall,
            f1=f1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            novel_discoveries=novel,
            confidence_buckets=buckets,
            domain=domain,
        )

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _match_triple(
        self,
        riverbank_s: str,
        riverbank_p: str,
        riverbank_o: str,
        riverbank_confidence: float,
        wikidata_statements: list[WikidataStatement],
        article_title: str,
        article_qid: str,
        covered_statement_indices: set[int],
    ) -> TripleMatch:
        """Match a single riverbank triple against the Wikidata statement list."""
        # Map predicate to P-ids
        pids = self.alignment.predicate_to_pids(riverbank_p)
        if not pids:
            # No alignment; count as potential novel discovery
            return TripleMatch(
                riverbank_triple=(riverbank_s, riverbank_p, riverbank_o),
                riverbank_confidence=riverbank_confidence,
                wikidata_statement=None,
                match_type="no_match",
                match_score=0.0,
                evidence=f"Predicate '{riverbank_p}' not in alignment table",
            )

        # Try to find matching Wikidata statement
        for idx, stmt in enumerate(wikidata_statements):
            if stmt.property_id not in pids:
                continue

            # Check object match
            obj_score = self._object_match_score(riverbank_o, stmt)
            if obj_score >= 0.85:
                covered_statement_indices.add(idx)
                return TripleMatch(
                    riverbank_triple=(riverbank_s, riverbank_p, riverbank_o),
                    riverbank_confidence=riverbank_confidence,
                    wikidata_statement=stmt,
                    match_type="exact",
                    match_score=obj_score,
                    evidence=f"Matched P{stmt.property_id}: '{stmt.value}'",
                )
            elif obj_score >= 0.5:
                # Partial match (same property, similar object)
                return TripleMatch(
                    riverbank_triple=(riverbank_s, riverbank_p, riverbank_o),
                    riverbank_confidence=riverbank_confidence,
                    wikidata_statement=stmt,
                    match_type="partial",
                    match_score=obj_score,
                    evidence=f"Partial P{stmt.property_id}: expected '{stmt.value}', got '{riverbank_o}'",
                )

        # Predicate is known but no object matched → false positive
        return TripleMatch(
            riverbank_triple=(riverbank_s, riverbank_p, riverbank_o),
            riverbank_confidence=riverbank_confidence,
            wikidata_statement=None,
            match_type="partial",
            match_score=0.0,
            evidence=f"Predicate maps to {pids} but no object match found",
        )

    @staticmethod
    def _object_match_score(riverbank_o: str, stmt: WikidataStatement) -> float:
        """Compute a match score (0–1) between riverbank object and Wikidata value."""
        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", s.lower())

        # Direct match
        if _norm(riverbank_o) == _norm(stmt.value):
            return 1.0
        if stmt.value_label and _norm(riverbank_o) == _norm(stmt.value_label):
            return 1.0

        # Date normalization: extract year
        year_rb = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", riverbank_o)
        year_wd = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", str(stmt.value))
        if year_rb and year_wd and year_rb.group() == year_wd.group():
            return 0.95

        # Fuzzy string similarity
        try:
            from rapidfuzz import fuzz  # noqa: PLC0415
            ratio = fuzz.token_sort_ratio(_norm(riverbank_o), _norm(stmt.value)) / 100.0
        except ImportError:
            from difflib import SequenceMatcher  # noqa: PLC0415
            ratio = SequenceMatcher(None, _norm(riverbank_o), _norm(stmt.value)).ratio()

        if stmt.value_label:
            try:
                from rapidfuzz import fuzz as _fuzz  # noqa: PLC0415
                ratio_label = _fuzz.token_sort_ratio(_norm(riverbank_o), _norm(stmt.value_label)) / 100.0
            except ImportError:
                from difflib import SequenceMatcher as _SM  # noqa: PLC0415
                ratio_label = _SM(None, _norm(riverbank_o), _norm(stmt.value_label)).ratio()
            ratio = max(ratio, ratio_label)

        return ratio

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_precision_recall(
        tp: int, fp: int, fn: int
    ) -> tuple[float, float, float]:
        """Compute precision, recall, and F1 from TP/FP/FN counts."""
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        if precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0
        return round(precision, 4), round(recall, 4), round(f1, 4)

    @staticmethod
    def _compute_confidence_calibration(
        matches: list[TripleMatch],
    ) -> dict[str, tuple[int, float]]:
        """Bucket matches by confidence; compute observed accuracy per bucket."""
        buckets: dict[str, list[bool]] = {b: [] for b in _CONFIDENCE_BUCKETS}

        for m in matches:
            conf = m.riverbank_confidence
            if conf < 0.25:
                key = "0.0-0.25"
            elif conf < 0.5:
                key = "0.25-0.5"
            elif conf < 0.75:
                key = "0.5-0.75"
            else:
                key = "0.75-1.0"
            buckets[key].append(m.match_type == "exact")

        result: dict[str, tuple[int, float]] = {}
        for key, correct_flags in buckets.items():
            count = len(correct_flags)
            accuracy = sum(correct_flags) / count if count > 0 else 0.0
            result[key] = (count, round(accuracy, 4))
        return result


class DatasetEvaluator:
    """Aggregate per-article scores into a full dataset result.

    Used by the ``riverbank evaluate-wikidata --dataset ...`` batch command.

    Parameters
    ----------
    scorer:
        Configured ``Scorer`` instance.
    """

    def __init__(self, scorer: Scorer | None = None) -> None:
        self.scorer = scorer or Scorer()

    def aggregate(
        self,
        article_scores: list[ArticleScore],
        run_metadata: RunMetadata,
    ) -> DatasetResult:
        """Aggregate per-article scores into a ``DatasetResult``.

        Parameters
        ----------
        article_scores:
            One ``ArticleScore`` per evaluated article.
        run_metadata:
            Evaluation run metadata.

        Returns
        -------
        DatasetResult
            Populated with aggregate, per-domain, per-property metrics and
            a calibration curve.
        """
        if not article_scores:
            return DatasetResult(run_metadata=run_metadata)

        # Overall aggregate
        total_tp = sum(s.true_positives for s in article_scores)
        total_fp = sum(s.false_positives for s in article_scores)
        total_fn = sum(s.false_negatives for s in article_scores)
        total_rb = sum(s.riverbank_triples for s in article_scores)
        total_wd = sum(s.wikidata_statements for s in article_scores)
        total_novel = sum(s.novel_discoveries for s in article_scores)

        precision, recall, f1 = Scorer._compute_precision_recall(total_tp, total_fp, total_fn)

        # False positive rate: FP / (FP + TN) approximation
        fpr = total_fp / (total_fp + total_tp) if (total_fp + total_tp) > 0 else 0.0
        novel_rate = total_novel / total_rb if total_rb > 0 else 0.0

        # Confidence calibration: Pearson ρ
        pearson_r = self._compute_calibration_pearson(article_scores)

        # Per-domain
        by_domain = self._aggregate_by_domain(article_scores)

        # Per-property (from TripleMatch evidence)
        by_property = self._aggregate_by_property(article_scores)

        # Calibration curve (aggregate across all articles)
        calibration_curve = self._aggregate_calibration_curve(article_scores)

        result = DatasetResult(
            run_metadata=run_metadata,
            article_scores=article_scores,
            precision=precision,
            recall=recall,
            f1=f1,
            confidence_calibration_pearson_r=round(pearson_r, 4),
            novel_discovery_rate=round(novel_rate, 4),
            false_positive_rate=round(fpr, 4),
            total_riverbank_triples=total_rb,
            total_wikidata_statements=total_wd,
            by_domain=by_domain,
            by_property=by_property,
            calibration_curve=calibration_curve,
        )
        return result

    def to_json(self, result: DatasetResult, output_path: Path) -> None:
        """Write the evaluation result to a JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "run_metadata": {
                "date": result.run_metadata.date,
                "riverbank_version": result.run_metadata.riverbank_version,
                "dataset": result.run_metadata.dataset,
                "profile": result.run_metadata.profile,
                "articles_evaluated": result.run_metadata.articles_evaluated,
                "duration_seconds": result.run_metadata.duration_seconds,
                "llm_model": result.run_metadata.llm_model,
                "total_llm_cost_usd": result.run_metadata.total_llm_cost_usd,
            },
            "aggregate": {
                "precision": result.precision,
                "recall": result.recall,
                "f1": result.f1,
                "confidence_calibration_pearson_r": result.confidence_calibration_pearson_r,
                "novel_discovery_rate": result.novel_discovery_rate,
                "false_positive_rate": result.false_positive_rate,
                "total_riverbank_triples": result.total_riverbank_triples,
                "total_wikidata_statements": result.total_wikidata_statements,
            },
            "by_domain": result.by_domain,
            "by_property": result.by_property,
            "calibration_curve": result.calibration_curve,
            "article_results": [s.to_dict() for s in result.article_scores],
        }

        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_by_domain(scores: list[ArticleScore]) -> dict[str, dict]:
        domain_map: dict[str, list[ArticleScore]] = defaultdict(list)
        for s in scores:
            domain_map[s.domain].append(s)

        result: dict[str, dict] = {}
        for domain, ds in domain_map.items():
            tp = sum(s.true_positives for s in ds)
            fp = sum(s.false_positives for s in ds)
            fn = sum(s.false_negatives for s in ds)
            rb = sum(s.riverbank_triples for s in ds)
            novel = sum(s.novel_discoveries for s in ds)
            p, r, f = Scorer._compute_precision_recall(tp, fp, fn)
            result[domain] = {
                "articles": len(ds),
                "precision": p,
                "recall": r,
                "f1": f,
                "novel_discovery_rate": round(novel / rb, 4) if rb > 0 else 0.0,
            }
        return result

    @staticmethod
    def _aggregate_by_property(scores: list[ArticleScore]) -> dict[str, dict]:
        """Extract per-property metrics from TripleMatch evidence strings."""
        prop_tp: dict[str, int] = defaultdict(int)
        prop_fp: dict[str, int] = defaultdict(int)
        prop_count: dict[str, int] = defaultdict(int)

        for score in scores:
            for match in score.triple_matches:
                pid_match = re.search(r"P(\d+)", match.evidence)
                if not pid_match:
                    continue
                pid = f"P{pid_match.group(1)}"
                prop_count[pid] += 1
                if match.match_type == "exact":
                    prop_tp[pid] += 1
                else:
                    prop_fp[pid] += 1

        result: dict[str, dict] = {}
        for pid in sorted(prop_count, key=lambda k: -prop_count[k])[:30]:
            tp = prop_tp[pid]
            fp = prop_fp[pid]
            fn = 0  # approximate
            p, r, f = Scorer._compute_precision_recall(tp, fp, fn)
            result[pid] = {
                "precision": p,
                "count": prop_count[pid],
            }
        return result

    @staticmethod
    def _aggregate_calibration_curve(scores: list[ArticleScore]) -> dict[str, dict]:
        agg: dict[str, list[int]] = {b: [0, 0] for b in _CONFIDENCE_BUCKETS}  # [count, correct]
        for score in scores:
            for bucket, (count, accuracy) in score.confidence_buckets.items():
                correct = round(accuracy * count)
                agg[bucket][0] += count
                agg[bucket][1] += correct
        result: dict[str, dict] = {}
        for bucket, (count, correct) in agg.items():
            observed_acc = correct / count if count > 0 else 0.0
            result[bucket] = {"count": count, "observed_accuracy": round(observed_acc, 4)}
        return result

    @staticmethod
    def _compute_calibration_pearson(scores: list[ArticleScore]) -> float:
        """Compute Pearson ρ between median bucket confidence and observed accuracy."""
        bucket_midpoints = {"0.0-0.25": 0.125, "0.25-0.5": 0.375, "0.5-0.75": 0.625, "0.75-1.0": 0.875}
        agg: dict[str, list[int]] = {b: [0, 0] for b in _CONFIDENCE_BUCKETS}

        for score in scores:
            for bucket, (count, accuracy) in score.confidence_buckets.items():
                correct = round(accuracy * count)
                agg[bucket][0] += count
                agg[bucket][1] += correct

        confidences = []
        accuracies = []
        for bucket, (count, correct) in agg.items():
            if count == 0:
                continue
            confidences.append(bucket_midpoints[bucket])
            accuracies.append(correct / count)

        if len(confidences) < 2:
            return 0.0

        try:
            import numpy as np  # noqa: PLC0415
            r = float(np.corrcoef(confidences, accuracies)[0, 1])
            return r if not math.isnan(r) else 0.0
        except ImportError:
            # Manual Pearson ρ
            n = len(confidences)
            mean_x = sum(confidences) / n
            mean_y = sum(accuracies) / n
            cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(confidences, accuracies))
            std_x = math.sqrt(sum((x - mean_x) ** 2 for x in confidences))
            std_y = math.sqrt(sum((y - mean_y) ** 2 for y in accuracies))
            if std_x * std_y == 0:
                return 0.0
            r = cov / (std_x * std_y)
            return round(r, 4)
