"""Unit tests for FewShotInjector (Strategy 6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from riverbank.preprocessors import FewShotConfig, FewShotExample, FewShotInjector


# ---------------------------------------------------------------------------
# Minimal profile stand-in
# ---------------------------------------------------------------------------


@dataclass
class _Profile:
    name: str = "test"
    prompt_text: str = "Extract triples."
    few_shot: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# FewShotExample dataclass
# ---------------------------------------------------------------------------


def test_few_shot_example_fields() -> None:
    ex = FewShotExample(
        subject="ex:sesam-pipe",
        predicate="schema:isPartOf",
        object_value="ex:sesam-system",
        confidence=0.95,
    )
    assert ex.subject == "ex:sesam-pipe"
    assert ex.source == ""


# ---------------------------------------------------------------------------
# FewShotConfig dataclass
# ---------------------------------------------------------------------------


def test_few_shot_config_defaults() -> None:
    cfg = FewShotConfig()
    assert cfg.enabled is False
    assert cfg.max_examples == 3
    assert cfg.selection == "random"


# ---------------------------------------------------------------------------
# FewShotInjector.from_profile()
# ---------------------------------------------------------------------------


def test_from_profile_disabled_when_no_few_shot_key() -> None:
    injector = FewShotInjector.from_profile(_Profile())
    assert injector._cfg.enabled is False


def test_from_profile_disabled_when_enabled_false() -> None:
    profile = _Profile(few_shot={"enabled": False})
    injector = FewShotInjector.from_profile(profile)
    assert injector._cfg.enabled is False


def test_from_profile_enabled() -> None:
    profile = _Profile(few_shot={
        "enabled": True,
        "source": "tests/golden/",
        "max_examples": 2,
        "selection": "fixed",
    })
    injector = FewShotInjector.from_profile(profile)
    assert injector._cfg.enabled is True
    assert injector._cfg.max_examples == 2
    assert injector._cfg.selection == "fixed"


# ---------------------------------------------------------------------------
# inject() when disabled
# ---------------------------------------------------------------------------


def test_inject_returns_prompt_unchanged_when_disabled() -> None:
    injector = FewShotInjector(FewShotConfig(enabled=False))
    prompt = "Extract triples."
    assert injector.inject(prompt) == prompt


# ---------------------------------------------------------------------------
# inject() with examples loaded from a temp YAML file
# ---------------------------------------------------------------------------


@pytest.fixture
def golden_dir(tmp_path: Path) -> Path:
    """Create a temporary golden examples directory with a YAML file."""
    examples_file = tmp_path / "test-corpus.yaml"
    examples_file.write_text(
        "triples:\n"
        "  - subject: ex:Pipe\n"
        "    predicate: schema:isPartOf\n"
        "    object_value: ex:System\n"
        "    confidence: 0.95\n"
        "  - subject: ex:Dataset\n"
        "    predicate: rdf:type\n"
        "    object_value: ex:Concept\n"
        "    confidence: 0.90\n"
        "  - subject: ex:Dataset\n"
        "    predicate: rdfs:label\n"
        "    object_value: 'Dataset'\n"
        "    confidence: 0.98\n"
    )
    return tmp_path


def test_inject_prepends_examples_block(golden_dir: Path) -> None:
    cfg = FewShotConfig(enabled=True, source=str(golden_dir), max_examples=3, selection="fixed")
    injector = FewShotInjector(cfg)
    result = injector.inject("Extract triples.")
    assert "FEW-SHOT EXAMPLES" in result
    assert "Extract triples." in result
    assert result.index("FEW-SHOT EXAMPLES") < result.index("Extract triples.")


def test_inject_includes_triple_content(golden_dir: Path) -> None:
    cfg = FewShotConfig(enabled=True, source=str(golden_dir), max_examples=3, selection="fixed")
    injector = FewShotInjector(cfg)
    result = injector.inject("Extract triples.")
    assert "ex:Pipe" in result
    assert "schema:isPartOf" in result
    assert "ex:System" in result


def test_inject_respects_max_examples(golden_dir: Path) -> None:
    cfg = FewShotConfig(enabled=True, source=str(golden_dir), max_examples=1, selection="fixed")
    injector = FewShotInjector(cfg)
    result = injector.inject("Extract triples.")
    # Only 1 example should appear — count the confidence annotations
    assert result.count("confidence:") == 1


def test_inject_with_nonexistent_source() -> None:
    cfg = FewShotConfig(enabled=True, source="/no/such/path", max_examples=3, selection="fixed")
    injector = FewShotInjector(cfg)
    result = injector.inject("Extract triples.")
    # Falls back gracefully — prompt unchanged
    assert result == "Extract triples."


def test_inject_examples_cached_after_first_load(golden_dir: Path) -> None:
    cfg = FewShotConfig(enabled=True, source=str(golden_dir), max_examples=3, selection="fixed")
    injector = FewShotInjector(cfg)
    _ = injector.inject("prompt A")
    assert injector._examples is not None  # cache populated
    _ = injector.inject("prompt B")
    # Still the same list object (not re-loaded)
    assert len(injector._examples) == 3


def test_inject_random_selection_returns_max_examples(golden_dir: Path) -> None:
    cfg = FewShotConfig(enabled=True, source=str(golden_dir), max_examples=2, selection="random")
    injector = FewShotInjector(cfg)
    result = injector.inject("prompt")
    assert result.count("confidence:") == 2


def test_load_examples_ignores_invalid_yaml(tmp_path: Path) -> None:
    """Malformed YAML in the source directory must be skipped gracefully."""
    (tmp_path / "bad.yaml").write_text("not: valid: yaml: [unclosed")
    (tmp_path / "good.yaml").write_text(
        "triples:\n  - subject: ex:A\n    predicate: ex:B\n    object_value: ex:C\n    confidence: 0.8\n"
    )
    cfg = FewShotConfig(enabled=True, source=str(tmp_path), max_examples=3, selection="fixed")
    injector = FewShotInjector(cfg)
    examples = injector._load_examples()
    # Only the good.yaml triple should load
    assert len(examples) == 1
    assert examples[0].subject == "ex:A"


# ---------------------------------------------------------------------------
# Integration: FewShotInjector with the real examples/golden/ directory
# ---------------------------------------------------------------------------


def test_real_golden_examples_load() -> None:
    """The shipped examples/golden/docs-policy-v1.yaml must load without errors."""
    import os  # noqa: PLC0415

    golden_path = Path(__file__).parent.parent.parent / "examples" / "golden"
    if not golden_path.exists():
        pytest.skip("examples/golden/ not present")

    cfg = FewShotConfig(enabled=True, source=str(golden_path), max_examples=3, selection="fixed")
    injector = FewShotInjector(cfg)
    examples = injector._load_examples()
    assert len(examples) >= 1
    for ex in examples:
        assert ex.subject
        assert ex.predicate
        assert ex.object_value
        assert 0.0 <= ex.confidence <= 1.0
