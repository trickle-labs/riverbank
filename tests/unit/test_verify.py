"""Unit tests for Post-2: Self-Critique Verification Pass."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest import mock


# ---------------------------------------------------------------------------
# Minimal profile fixture
# ---------------------------------------------------------------------------


@dataclass
class _Profile:
    name: str = "test"
    model_name: str = "llama3.2"
    named_graph: str = "http://riverbank.example/graph/trusted"
    verification: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "confidence_threshold": 0.75,
            "drop_below": 0.4,
            "boost_above": 0.8,
        }
    )


@dataclass
class _ProfileDisabled:
    name: str = "noop"
    verification: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


def test_verification_outcome_dataclass() -> None:
    from riverbank.postprocessors.verify import VerificationOutcome

    outcome = VerificationOutcome(
        triple_id="(ex:pipe, schema:isPartOf, ex:system)",
        supported=True,
        verifier_confidence=0.9,
        action="boosted",
    )
    assert outcome.supported is True
    assert outcome.action == "boosted"


def test_verification_result_defaults() -> None:
    from riverbank.postprocessors.verify import VerificationResult

    result = VerificationResult()
    assert result.triples_examined == 0
    assert result.boosted == 0
    assert result.kept == 0
    assert result.quarantined == 0
    assert result.errors == 0
    assert result.outcomes == []


# ---------------------------------------------------------------------------
# VerificationPass — disabled profile
# ---------------------------------------------------------------------------


def test_verify_returns_empty_when_disabled() -> None:
    """When verification is disabled in the profile, verify() returns an empty result."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    conn = mock.MagicMock()
    result = verifier.verify(conn, "http://ex.org/graph/trusted", _ProfileDisabled())

    assert result.triples_examined == 0
    assert result.boosted == 0
    assert result.quarantined == 0


# ---------------------------------------------------------------------------
# VerificationPass — no candidates
# ---------------------------------------------------------------------------


def test_verify_returns_empty_when_no_candidates() -> None:
    """When there are no low-confidence triples, verify() returns an empty result."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    with mock.patch.object(verifier, "_fetch_candidates", return_value=[]):
        conn = mock.MagicMock()
        result = verifier.verify(conn, "http://ex.org/graph/trusted", _Profile())

    assert result.triples_examined == 0


# ---------------------------------------------------------------------------
# VerificationPass — LLM unavailable
# ---------------------------------------------------------------------------


def test_verify_returns_empty_when_llm_unavailable() -> None:
    """When the LLM client cannot be constructed, verify() falls back gracefully."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    candidates = [
        {
            "subject": "http://ex.org/entities/pipe",
            "predicate": "http://schema.org/isPartOf",
            "object_value": "http://ex.org/entities/system",
            "confidence": 0.6,
            "evidence": "The pipe is part of the system.",
        }
    ]
    with mock.patch.object(verifier, "_fetch_candidates", return_value=candidates):
        with mock.patch.object(
            verifier,
            "_get_llm_client",
            side_effect=ImportError("instructor not installed"),
        ):
            conn = mock.MagicMock()
            result = verifier.verify(conn, "http://ex.org/graph/trusted", _Profile())

    # triples_examined is set from the candidate count; no outcomes are produced
    assert result.triples_examined == 1
    assert result.boosted == 0
    assert result.quarantined == 0
    assert result.outcomes == []


# ---------------------------------------------------------------------------
# VerificationPass — LLM verifies triple as supported (boost path)
# ---------------------------------------------------------------------------


def test_verify_boosts_confirmed_triple() -> None:
    """A triple confirmed by the verifier with high confidence is boosted."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    candidates = [
        {
            "subject": "http://ex.org/entities/pipe",
            "predicate": "http://schema.org/isPartOf",
            "object_value": "http://ex.org/entities/system",
            "confidence": 0.65,
            "evidence": "The pipe is part of the system.",
        }
    ]

    boost_confidence = 0.92

    with mock.patch.object(verifier, "_fetch_candidates", return_value=candidates):
        with mock.patch.object(
            verifier,
            "_get_llm_client",
            return_value=(mock.MagicMock(), "llama3.2"),
        ):
            with mock.patch.object(
                verifier,
                "_verify_triple",
                return_value={
                    "supported": True,
                    "verifier_confidence": boost_confidence,
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                },
            ):
                with mock.patch.object(verifier, "_update_confidence") as mock_update:
                    conn = mock.MagicMock()
                    result = verifier.verify(
                        conn,
                        "http://ex.org/graph/trusted",
                        _Profile(),
                        dry_run=False,
                    )

    assert result.boosted == 1
    assert result.kept == 0
    assert result.quarantined == 0
    mock_update.assert_called_once()


# ---------------------------------------------------------------------------
# VerificationPass — LLM rejects triple (quarantine path)
# ---------------------------------------------------------------------------


def test_verify_quarantines_rejected_triple() -> None:
    """A triple rejected by the verifier is quarantined."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    candidates = [
        {
            "subject": "http://ex.org/entities/pipe",
            "predicate": "http://schema.org/isPartOf",
            "object_value": "http://ex.org/entities/system",
            "confidence": 0.55,
            "evidence": "The pipe does NOT belong to the system.",
        }
    ]

    with mock.patch.object(verifier, "_fetch_candidates", return_value=candidates):
        with mock.patch.object(
            verifier,
            "_get_llm_client",
            return_value=(mock.MagicMock(), "llama3.2"),
        ):
            with mock.patch.object(
                verifier,
                "_verify_triple",
                return_value={
                    "supported": False,
                    "verifier_confidence": 0.3,
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                },
            ):
                with mock.patch.object(verifier, "_quarantine_triple") as mock_quarantine:
                    conn = mock.MagicMock()
                    result = verifier.verify(
                        conn,
                        "http://ex.org/graph/trusted",
                        _Profile(),
                        dry_run=False,
                    )

    assert result.quarantined == 1
    assert result.boosted == 0
    mock_quarantine.assert_called_once()


# ---------------------------------------------------------------------------
# VerificationPass — dry-run does not quarantine or boost
# ---------------------------------------------------------------------------


def test_verify_dry_run_does_not_modify_graph() -> None:
    """dry_run=True: outcomes are computed but nothing is written."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    candidates = [
        {
            "subject": "http://ex.org/entities/pipe",
            "predicate": "http://schema.org/isPartOf",
            "object_value": "http://ex.org/entities/system",
            "confidence": 0.55,
            "evidence": "Evidence text.",
        }
    ]

    with mock.patch.object(verifier, "_fetch_candidates", return_value=candidates):
        with mock.patch.object(
            verifier,
            "_get_llm_client",
            return_value=(mock.MagicMock(), "llama3.2"),
        ):
            with mock.patch.object(
                verifier,
                "_verify_triple",
                return_value={
                    "supported": False,
                    "verifier_confidence": 0.2,
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                },
            ):
                with mock.patch.object(verifier, "_quarantine_triple") as mock_quarantine:
                    with mock.patch.object(verifier, "_update_confidence") as mock_update:
                        conn = mock.MagicMock()
                        result = verifier.verify(
                            conn,
                            "http://ex.org/graph/trusted",
                            _Profile(),
                            dry_run=True,
                        )

    mock_quarantine.assert_not_called()
    mock_update.assert_not_called()
    assert result.quarantined == 1  # counted but not written


# ---------------------------------------------------------------------------
# VerificationPass — error path
# ---------------------------------------------------------------------------


def test_verify_handles_llm_error() -> None:
    """LLM call failures are counted but do not abort the pass."""
    from riverbank.postprocessors.verify import VerificationPass

    verifier = VerificationPass()
    candidates = [
        {
            "subject": "http://ex.org/entities/pipe",
            "predicate": "http://schema.org/isPartOf",
            "object_value": "http://ex.org/entities/system",
            "confidence": 0.6,
            "evidence": "Some text.",
        }
    ]

    with mock.patch.object(verifier, "_fetch_candidates", return_value=candidates):
        with mock.patch.object(
            verifier,
            "_get_llm_client",
            return_value=(mock.MagicMock(), "llama3.2"),
        ):
            with mock.patch.object(
                verifier,
                "_verify_triple",
                return_value={"error": "connection refused", "prompt_tokens": 0, "completion_tokens": 0},
            ):
                conn = mock.MagicMock()
                result = verifier.verify(
                    conn,
                    "http://ex.org/graph/trusted",
                    _Profile(),
                )

    assert result.errors == 1
    assert result.boosted == 0
    assert result.quarantined == 0


# ---------------------------------------------------------------------------
# _triple_id helper
# ---------------------------------------------------------------------------


def test_triple_id() -> None:
    from riverbank.postprocessors.verify import _triple_id

    triple = {
        "subject": "http://ex.org/a",
        "predicate": "http://schema.org/isPartOf",
        "object_value": "http://ex.org/b",
    }
    tid = _triple_id(triple)
    assert "http://ex.org/a" in tid
    assert "http://ex.org/b" in tid
