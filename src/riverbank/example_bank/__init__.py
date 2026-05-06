from __future__ import annotations

"""Editorial policy example bank (v0.6.0).

Each Label Studio decision that is accepted or corrected is exported to the
profile's example bank.  On the next compile run the few-shot example list is
injected into the LLM prompt, so the model sees recent high-quality extractions
from the same corpus before it produces new triples.

The example bank is stored as a JSONL file adjacent to the compiler profile
YAML (``<profile_name>_examples.jsonl``), making it easy to commit to version
control or inspect by hand.

The :func:`append_example` function is called by the pipeline after a
:class:`~riverbank.reviewers.label_studio.ReviewDecision` has been accepted.
The :func:`load_examples` function returns the current bank as a list of dicts
that can be embedded in the LLM prompt as a ``few_shot_examples`` parameter.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_EXAMPLES = 50


def append_example(
    bank_path: str | Path,
    subject: str,
    predicate: str,
    object_value: str,
    excerpt: str,
    reviewer_note: str = "",
    max_examples: int = _DEFAULT_MAX_EXAMPLES,
) -> int:
    """Append one reviewed example to the JSONL example bank.

    Keeps the bank bounded: once the file reaches *max_examples* entries the
    oldest entry is dropped so the bank never exceeds that size (a FIFO ring
    buffer).

    Returns the number of examples now in the bank.
    """
    bank_path = Path(bank_path)
    existing: list[dict] = load_examples(bank_path)

    entry: dict[str, Any] = {
        "subject": subject,
        "predicate": predicate,
        "object_value": object_value,
        "excerpt": excerpt,
        "reviewer_note": reviewer_note,
    }
    existing.append(entry)

    # Trim to max_examples (keep most recent)
    if len(existing) > max_examples:
        existing = existing[-max_examples:]

    try:
        bank_path.parent.mkdir(parents=True, exist_ok=True)
        with bank_path.open("w", encoding="utf-8") as fh:
            for ex in existing:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("example_bank: could not write %s: %s", bank_path, exc)

    return len(existing)


def load_examples(bank_path: str | Path) -> list[dict]:
    """Load all examples from a JSONL bank file.

    Returns an empty list when the file does not exist or cannot be parsed.
    """
    bank_path = Path(bank_path)
    if not bank_path.exists():
        return []

    examples: list[dict] = []
    try:
        with bank_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        examples.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        logger.debug("example_bank: skipping bad line: %s", exc)
    except OSError as exc:
        logger.warning("example_bank: could not read %s: %s", bank_path, exc)

    return examples


def bank_path_for_profile(profile_name: str, base_dir: str | Path = ".") -> Path:
    """Return the canonical JSONL bank file path for a given profile name."""
    return Path(base_dir) / f"{profile_name}_examples.jsonl"


def export_decision_to_bank(
    decision: Any,
    bank_path: str | Path,
    max_examples: int = _DEFAULT_MAX_EXAMPLES,
) -> int:
    """Export a :class:`~riverbank.reviewers.label_studio.ReviewDecision` to the bank.

    Only accepted or corrected decisions are exported; rejected decisions are
    silently ignored (they carry no useful positive signal for few-shot learning).

    Returns the new bank size, or 0 when the decision was rejected.
    """
    if not (getattr(decision, "accepted", False) or getattr(decision, "corrected", False)):
        return 0

    return append_example(
        bank_path=bank_path,
        subject=getattr(decision, "subject", ""),
        predicate=getattr(decision, "predicate", ""),
        object_value=getattr(decision, "object_value", ""),
        excerpt="",  # excerpt not available on the decision object directly
        reviewer_note=getattr(decision, "reviewer_note", ""),
        max_examples=max_examples,
    )
