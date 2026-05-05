"""Unit tests for the IngestGate editorial policy filter."""
from __future__ import annotations

from dataclasses import dataclass, field

from riverbank.ingest_gate import IngestGate, IngestGateConfig


@dataclass
class _FakeFragment:
    text: str = ""
    heading_depth: int = 1
    heading_path: list = field(default_factory=lambda: ["Section"])


def _gate(
    text: str,
    heading_depth: int = 1,
    heading_path: list | None = None,
    **kwargs,
) -> "bool | str":
    gate = IngestGate()
    config = IngestGateConfig(**kwargs)
    frag = _FakeFragment(
        text=text,
        heading_depth=heading_depth,
        heading_path=heading_path if heading_path is not None else ["Section"],
    )
    result = gate.check(frag, config)
    return result.accepted


def test_fragment_within_limits_is_accepted() -> None:
    text = "A" * 200
    assert _gate(text) is True


def test_fragment_too_short_is_rejected() -> None:
    assert _gate("Hi.", min_fragment_length=50) is False


def test_fragment_too_long_is_rejected() -> None:
    text = "A" * 9000
    assert _gate(text, max_fragment_length=8000) is False


def test_require_heading_with_no_heading_is_rejected() -> None:
    text = "A" * 200
    assert _gate(text, heading_path=[], require_heading=True) is False


def test_require_heading_with_heading_is_accepted() -> None:
    text = "A" * 200
    assert _gate(text, heading_path=["Sec"], require_heading=True) is True


def test_min_heading_depth_enforced() -> None:
    text = "A" * 200
    # depth 1 with min 2 → rejected
    assert _gate(text, heading_depth=1, min_heading_depth=2) is False


def test_min_heading_depth_satisfied() -> None:
    text = "A" * 200
    assert _gate(text, heading_depth=2, min_heading_depth=2) is True


def test_default_config_accepts_normal_fragment() -> None:
    gate = IngestGate()
    config = IngestGateConfig()
    frag = _FakeFragment(text="A" * 200)
    result = gate.check(frag, config)
    assert result.accepted is True
    assert result.reason is None
