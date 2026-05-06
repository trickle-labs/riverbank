"""Unit tests for the procedural-v1 compiler profile (v0.8.0)."""
from __future__ import annotations

from pathlib import Path


PROCEDURAL_PROFILE_PATH = Path(__file__).parent.parent.parent / "examples" / "profiles" / "procedural-v1.yaml"


def test_procedural_profile_file_exists() -> None:
    """procedural-v1.yaml exists in examples/profiles/."""
    assert PROCEDURAL_PROFILE_PATH.exists(), (
        f"procedural-v1.yaml not found at {PROCEDURAL_PROFILE_PATH}"
    )


def test_procedural_profile_is_valid_yaml() -> None:
    """procedural-v1.yaml is valid YAML."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict)


def test_procedural_profile_has_required_fields() -> None:
    """procedural-v1.yaml has all required profile fields."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    assert data["name"] == "procedural-v1"
    assert data["version"] == 1
    assert "prompt_text" in data
    assert "editorial_policy" in data
    assert "competency_questions" in data


def test_procedural_profile_run_mode_sequence() -> None:
    """procedural-v1 declares run_mode_sequence: [vocabulary, full]."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    assert "run_mode_sequence" in data
    sequence = data["run_mode_sequence"]
    assert "vocabulary" in sequence
    assert "full" in sequence


def test_procedural_profile_competency_questions_count() -> None:
    """procedural-v1 has at least 5 standard competency questions."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    cqs = data.get("competency_questions", [])
    assert len(cqs) >= 5


def test_procedural_profile_competency_questions_have_sparql() -> None:
    """All competency questions in procedural-v1 have a sparql key."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    for cq in data["competency_questions"]:
        assert "sparql" in cq, f"CQ {cq.get('id', '?')} has no sparql key"
        assert cq["sparql"].strip().upper().startswith("ASK"), (
            f"CQ {cq.get('id', '?')} SPARQL must be an ASK query"
        )


def test_procedural_profile_covers_pko_predicates() -> None:
    """procedural-v1 prompt references PKO predicates."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    prompt = data["prompt_text"]
    assert "pko:nextStep" in prompt or "nextStep" in prompt
    assert "pko:hasPrecondition" in prompt or "hasPrecondition" in prompt


def test_procedural_profile_absence_rules_present() -> None:
    """procedural-v1 declares absence_rules for error-handling path."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    assert "absence_rules" in data
    rules = data["absence_rules"]
    assert len(rules) >= 1
    predicates = [r["predicate"] for r in rules]
    assert any("error" in p.lower() or "Error" in p for p in predicates)


def test_procedural_profile_standard_cq_topics() -> None:
    """procedural-v1 competency questions cover failure, access, rollback topics."""
    import yaml

    with PROCEDURAL_PROFILE_PATH.open() as f:
        data = yaml.safe_load(f)

    descriptions = " ".join(
        cq.get("description", "") for cq in data["competency_questions"]
    ).lower()

    assert "fail" in descriptions  # "What happens if a step fails?"
    assert "admin" in descriptions or "access" in descriptions  # "Which steps require admin access?"
    assert "rollback" in descriptions  # "What is the rollback path?"


def test_procedural_profile_can_be_loaded_as_compiler_profile() -> None:
    """procedural-v1.yaml can be loaded via CompilerProfile.from_yaml."""
    from riverbank.pipeline import CompilerProfile

    profile = CompilerProfile.from_yaml(PROCEDURAL_PROFILE_PATH)
    assert profile.name == "procedural-v1"
    assert profile.version == 1
