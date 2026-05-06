"""Unit tests for the editorial policy example bank (v0.6.0)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_append_example_creates_file(tmp_path: Path) -> None:
    """append_example creates the JSONL file when it doesn't exist."""
    from riverbank.example_bank import append_example

    bank = tmp_path / "test_examples.jsonl"
    count = append_example(
        bank_path=bank,
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        excerpt="Acme is an organisation.",
    )
    assert count == 1
    assert bank.exists()


def test_append_example_persists_all_fields(tmp_path: Path) -> None:
    """append_example writes all fields to the JSONL file."""
    from riverbank.example_bank import append_example

    bank = tmp_path / "examples.jsonl"
    append_example(
        bank_path=bank,
        subject="entity:Acme",
        predicate="rdfs:label",
        object_value="Acme Corporation",
        excerpt="Acme Corporation is a company.",
        reviewer_note="Confirmed by reviewer.",
    )
    lines = bank.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["subject"] == "entity:Acme"
    assert entry["predicate"] == "rdfs:label"
    assert entry["object_value"] == "Acme Corporation"
    assert entry["excerpt"] == "Acme Corporation is a company."
    assert entry["reviewer_note"] == "Confirmed by reviewer."


def test_append_example_accumulates_multiple_entries(tmp_path: Path) -> None:
    """Multiple calls append multiple lines."""
    from riverbank.example_bank import append_example

    bank = tmp_path / "examples.jsonl"
    for i in range(5):
        count = append_example(
            bank_path=bank,
            subject=f"entity:E{i}",
            predicate="rdf:type",
            object_value="owl:Class",
            excerpt=f"Entity {i} is a class.",
        )
    assert count == 5


def test_append_example_trims_to_max_examples(tmp_path: Path) -> None:
    """Bank is trimmed to max_examples when it exceeds the limit."""
    from riverbank.example_bank import append_example

    bank = tmp_path / "examples.jsonl"
    for i in range(10):
        append_example(
            bank_path=bank,
            subject=f"entity:E{i}",
            predicate="rdf:type",
            object_value="owl:Class",
            excerpt=f"E{i}.",
            max_examples=5,
        )

    lines = bank.read_text().strip().splitlines()
    assert len(lines) == 5
    # The most recent entries are kept
    last_entry = json.loads(lines[-1])
    assert last_entry["subject"] == "entity:E9"


def test_load_examples_returns_empty_for_missing_file(tmp_path: Path) -> None:
    """load_examples returns [] when the bank file doesn't exist."""
    from riverbank.example_bank import load_examples

    result = load_examples(tmp_path / "nonexistent.jsonl")
    assert result == []


def test_load_examples_round_trips(tmp_path: Path) -> None:
    """load_examples returns all examples written by append_example."""
    from riverbank.example_bank import append_example, load_examples

    bank = tmp_path / "examples.jsonl"
    for i in range(3):
        append_example(
            bank_path=bank,
            subject=f"entity:E{i}",
            predicate="skos:prefLabel",
            object_value=f"Entity {i}",
            excerpt=f"Text about entity {i}.",
        )

    examples = load_examples(bank)
    assert len(examples) == 3
    assert examples[0]["subject"] == "entity:E0"
    assert examples[2]["subject"] == "entity:E2"


def test_bank_path_for_profile(tmp_path: Path) -> None:
    """bank_path_for_profile returns the expected path."""
    from riverbank.example_bank import bank_path_for_profile

    path = bank_path_for_profile("docs-policy-v1", base_dir=tmp_path)
    assert path == tmp_path / "docs-policy-v1_examples.jsonl"


def test_export_decision_to_bank_accepted(tmp_path: Path) -> None:
    """export_decision_to_bank exports accepted decisions."""
    from riverbank.example_bank import export_decision_to_bank, load_examples
    from riverbank.reviewers.label_studio import ReviewDecision

    bank = tmp_path / "examples.jsonl"
    decision = ReviewDecision(
        task_id=1,
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Organization",
        accepted=True,
        reviewer_note="Confirmed.",
    )
    size = export_decision_to_bank(decision, bank)
    assert size == 1
    examples = load_examples(bank)
    assert len(examples) == 1
    assert examples[0]["subject"] == "entity:Acme"


def test_export_decision_to_bank_rejected_not_exported(tmp_path: Path) -> None:
    """export_decision_to_bank does NOT export rejected decisions."""
    from riverbank.example_bank import export_decision_to_bank, load_examples
    from riverbank.reviewers.label_studio import ReviewDecision

    bank = tmp_path / "examples.jsonl"
    decision = ReviewDecision(
        task_id=2,
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:BadClass",
        accepted=False,
        corrected=False,
    )
    size = export_decision_to_bank(decision, bank)
    assert size == 0
    assert not bank.exists()


def test_export_decision_to_bank_corrected(tmp_path: Path) -> None:
    """export_decision_to_bank exports corrected decisions."""
    from riverbank.example_bank import export_decision_to_bank, load_examples
    from riverbank.reviewers.label_studio import ReviewDecision

    bank = tmp_path / "examples.jsonl"
    decision = ReviewDecision(
        task_id=3,
        artifact_iri="entity:Acme",
        subject="entity:Acme",
        predicate="rdf:type",
        object_value="org:Company",  # corrected value
        accepted=False,
        corrected=True,
        reviewer_note="Changed from Organization to Company.",
    )
    size = export_decision_to_bank(decision, bank)
    assert size == 1
