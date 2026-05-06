"""Auto few-shot expansion — self-improving golden example bank (v0.13.1).

**Problem:** The few-shot example bank is static: it only grows when a human
explicitly adds examples via Label Studio review.  High-confidence triples
from validated ingests are discarded rather than recycled as future guidance.

**Approach:** After each ingest run where CQ coverage exceeds a configurable
threshold, high-confidence triples that satisfy at least one competency question
are automatically sampled and appended to the profile's golden examples JSONL
file.  This closes the CQ-as-north-star feedback cycle begun in v0.12.0.

**Diversity constraint:** No two examples with the same ``(predicate, type)``
combination are added in the same expansion.  The bank is capped at
``max_bank_size`` (default 15) examples; oldest entries are dropped when the
cap is reached.

Profile YAML::

    few_shot:
      enabled: true
      source: tests/golden/
      auto_expand: true
      auto_expand_cq_threshold: 0.70   # expand only when CQ coverage ≥ 70%
      auto_expand_confidence: 0.85     # only sample triples with conf ≥ this
      max_bank_size: 15                # cap on total auto-expanded examples

Usage::

    from riverbank.few_shot_expansion import FewShotExpander

    expander = FewShotExpander()
    result = expander.expand(
        triples=high_confidence_triples,
        bank_path="tests/golden/my-profile_autobank.jsonl",
        cq_coverage=0.85,
        competency_questions=profile.competency_questions,
    )
    print(result.examples_added, "examples added to the bank")
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default settings
_DEFAULT_CQ_THRESHOLD = 0.70          # expand when CQ coverage ≥ this
_DEFAULT_CONFIDENCE_THRESHOLD = 0.85  # only sample triples with conf ≥ this
_DEFAULT_MAX_BANK_SIZE = 15           # cap per-profile auto-expanded examples
_DEFAULT_MAX_NEW_PER_RUN = 5          # maximum new examples per expansion run


def _predicate_label(predicate: str) -> str:
    """Extract the local name from a predicate IRI or prefixed name."""
    return predicate.split("/")[-1].split("#")[-1].split(":")[-1].lower()


def _cq_keywords(cq: str) -> list[str]:
    """Extract keywords from a competency question text."""
    stop = {"what", "which", "who", "how", "where", "when", "is", "are", "does",
            "do", "the", "a", "an", "of", "in", "to", "for", "with", "has", "have"}
    words = cq.lower().replace("?", "").replace(",", "").split()
    return [w for w in words if w not in stop and len(w) > 2]


def _triple_satisfies_cq(triple: Any, cq_list: list[str]) -> bool:
    """Return True if the triple's predicate or subject appear in any CQ."""
    if not cq_list:
        return True  # no CQs → accept everything
    pred_label = _predicate_label(getattr(triple, "predicate", ""))
    subj = getattr(triple, "subject", "").lower()
    obj = getattr(triple, "object_value", "").lower()
    for cq in cq_list:
        kws = _cq_keywords(cq)
        if any(kw in pred_label or kw in subj or kw in obj for kw in kws):
            return True
    return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExpansionResult:
    """Summary of an auto few-shot expansion run."""

    examples_added: int = 0
    examples_skipped_confidence: int = 0
    examples_skipped_diversity: int = 0
    examples_skipped_cq: int = 0
    bank_size_after: int = 0
    cq_coverage: float = 0.0
    threshold_met: bool = False


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class FewShotExpander:
    """Sample high-confidence triples and append them to the golden example bank.

    Args:
        cq_threshold: CQ coverage fraction at or above which expansion runs.
        confidence_threshold: Minimum triple confidence for inclusion.
        max_bank_size: Maximum total entries in the JSONL bank.
        max_new_per_run: Maximum new examples added per expansion run.
    """

    def __init__(
        self,
        cq_threshold: float = _DEFAULT_CQ_THRESHOLD,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
        max_bank_size: int = _DEFAULT_MAX_BANK_SIZE,
        max_new_per_run: int = _DEFAULT_MAX_NEW_PER_RUN,
    ) -> None:
        self._cq_threshold = cq_threshold
        self._confidence_threshold = confidence_threshold
        self._max_bank_size = max_bank_size
        self._max_new_per_run = max_new_per_run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def expand(
        self,
        triples: list[Any],
        bank_path: str | Path,
        cq_coverage: float,
        competency_questions: list[str] | None = None,
        dry_run: bool = False,
    ) -> ExpansionResult:
        """Sample triples and append new examples to *bank_path*.

        Args:
            triples: Extracted triples (duck-typed: need .subject, .predicate,
                .object_value, .confidence, .evidence attributes).
            bank_path: Path to the JSONL auto-expansion bank file.
            cq_coverage: Fraction of competency questions covered in this run
                (0.0–1.0).  Expansion only runs when this exceeds the threshold.
            competency_questions: List of CQ strings from the profile.
                When empty, all high-confidence triples are eligible.
            dry_run: When ``True``, compute candidates but do not write to disk.

        Returns:
            :class:`ExpansionResult` with counts.
        """
        result = ExpansionResult(cq_coverage=cq_coverage)
        cqs = competency_questions or []

        # Only expand when CQ coverage is high enough
        if cq_coverage < self._cq_threshold:
            logger.info(
                "few_shot_expander: CQ coverage %.2f below threshold %.2f — "
                "skipping auto-expansion",
                cq_coverage,
                self._cq_threshold,
            )
            return result

        result.threshold_met = True
        bank_path = Path(bank_path)

        # Load current bank
        current_bank = self._load_bank(bank_path)
        existing_keys = {self._triple_key(e) for e in current_bank}

        # Step 1: filter by confidence
        high_conf = []
        for t in triples:
            conf = float(getattr(t, "confidence", 0.0))
            if conf >= self._confidence_threshold:
                high_conf.append(t)
            else:
                result.examples_skipped_confidence += 1

        # Step 2: filter by CQ relevance
        cq_relevant = []
        for t in high_conf:
            if _triple_satisfies_cq(t, cqs):
                cq_relevant.append(t)
            else:
                result.examples_skipped_cq += 1

        if not cq_relevant:
            logger.info(
                "few_shot_expander: no high-confidence CQ-relevant triples found"
            )
            return result

        # Step 3: diversity sampling — no two examples with same predicate+type
        new_examples: list[dict] = []
        seen_pred_type: set[tuple[str, str]] = set()

        # Shuffle for fair sampling
        shuffled = list(cq_relevant)
        random.shuffle(shuffled)

        for t in shuffled:
            if len(new_examples) >= self._max_new_per_run:
                break

            pred_label = _predicate_label(getattr(t, "predicate", ""))
            obj_type = str(getattr(t, "object_value", ""))[:20]  # coarse type proxy
            diversity_key = (pred_label, obj_type)
            if diversity_key in seen_pred_type:
                result.examples_skipped_diversity += 1
                continue

            # Deduplicate against existing bank
            entry = self._triple_to_entry(t)
            if self._triple_key(entry) in existing_keys:
                result.examples_skipped_diversity += 1
                continue

            seen_pred_type.add(diversity_key)
            new_examples.append(entry)

        if not new_examples:
            logger.info("few_shot_expander: no new diverse examples to add")
            return result

        # Step 4: write to bank with cap enforcement
        updated_bank = current_bank + new_examples
        if len(updated_bank) > self._max_bank_size:
            updated_bank = updated_bank[-self._max_bank_size:]

        result.examples_added = len(new_examples)
        result.bank_size_after = len(updated_bank)

        if not dry_run:
            self._write_bank(bank_path, updated_bank)
            logger.info(
                "few_shot_expander: appended %d new examples to %s (bank size: %d)",
                result.examples_added,
                bank_path,
                result.bank_size_after,
            )
        else:
            logger.info(
                "few_shot_expander: dry-run — would append %d new examples",
                result.examples_added,
            )

        return result

    def should_expand(self, profile: Any, cq_coverage: float) -> bool:
        """Return True when auto-expansion is enabled and threshold is met."""
        few_shot_cfg: dict = getattr(profile, "few_shot", {})
        if not few_shot_cfg.get("auto_expand", False):
            return False
        threshold = float(few_shot_cfg.get("auto_expand_cq_threshold", self._cq_threshold))
        return cq_coverage >= threshold

    def bank_path_for_profile(self, profile: Any) -> Path:
        """Derive the auto-expansion bank path from the profile configuration.

        Looks for ``few_shot.source`` in the profile and returns a file named
        ``<profile_name>_autobank.jsonl`` in the same directory.
        """
        few_shot_cfg: dict = getattr(profile, "few_shot", {})
        source_dir = Path(few_shot_cfg.get("source", "tests/golden/"))
        profile_name = getattr(profile, "name", "default").replace(" ", "_")
        return source_dir / f"{profile_name}_autobank.jsonl"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_bank(self, path: Path) -> list[dict]:
        """Load existing JSONL entries from *path*. Returns [] on missing/error."""
        if not path.exists():
            return []
        entries: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        except Exception as exc:  # noqa: BLE001
            logger.warning("few_shot_expander: could not load bank %s: %s", path, exc)
        return entries

    def _write_bank(self, path: Path, entries: list[dict]) -> None:
        """Write *entries* to *path* as JSONL."""
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("w", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("few_shot_expander: could not write bank %s: %s", path, exc)

    @staticmethod
    def _triple_to_entry(t: Any) -> dict:
        """Convert a triple object to a bank JSONL entry dict."""
        evidence = ""
        ev = getattr(t, "evidence", None)
        if ev is not None:
            evidence = getattr(ev, "excerpt", "") or ""
        return {
            "subject": getattr(t, "subject", ""),
            "predicate": getattr(t, "predicate", ""),
            "object_value": getattr(t, "object_value", ""),
            "confidence": float(getattr(t, "confidence", 0.9)),
            "excerpt": str(evidence)[:200],
        }

    @staticmethod
    def _triple_key(entry: dict) -> tuple[str, str, str]:
        return (
            entry.get("subject", ""),
            entry.get("predicate", ""),
            entry.get("object_value", ""),
        )
