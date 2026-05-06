"""Unit tests for the epistemic status layer — all 9 status values (v0.8.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_epistemic_status_has_nine_values() -> None:
    """EpistemicStatus enum has exactly 9 values."""
    from riverbank.epistemic import EpistemicStatus

    statuses = list(EpistemicStatus)
    assert len(statuses) == 9


def test_all_nine_status_values_present() -> None:
    """All 9 epistemic status labels are present."""
    from riverbank.epistemic import EpistemicStatus

    expected = {
        "observed", "extracted", "inferred", "verified",
        "deprecated", "normative", "predicted", "disputed", "speculative",
    }
    actual = {s.value for s in EpistemicStatus}
    assert actual == expected


def test_is_valid_transition_extracted_to_verified() -> None:
    """extracted → verified is a valid transition."""
    from riverbank.epistemic import EpistemicStatus, is_valid_transition

    assert is_valid_transition(EpistemicStatus.EXTRACTED, EpistemicStatus.VERIFIED) is True


def test_is_valid_transition_deprecated_is_terminal() -> None:
    """deprecated has no valid outgoing transitions."""
    from riverbank.epistemic import EpistemicStatus, is_valid_transition

    for target in EpistemicStatus:
        assert is_valid_transition(EpistemicStatus.DEPRECATED, target) is False


def test_is_valid_transition_extracted_to_disputed() -> None:
    """extracted → disputed is a valid transition."""
    from riverbank.epistemic import EpistemicStatus, is_valid_transition

    assert is_valid_transition(EpistemicStatus.EXTRACTED, EpistemicStatus.DISPUTED) is True


def test_is_valid_transition_verified_to_deprecated() -> None:
    """verified → deprecated is a valid transition."""
    from riverbank.epistemic import EpistemicStatus, is_valid_transition

    assert is_valid_transition(EpistemicStatus.VERIFIED, EpistemicStatus.DEPRECATED) is True


def test_is_valid_transition_observed_to_predicted_is_invalid() -> None:
    """observed → predicted is NOT a valid transition."""
    from riverbank.epistemic import EpistemicStatus, is_valid_transition

    assert is_valid_transition(EpistemicStatus.OBSERVED, EpistemicStatus.PREDICTED) is False


def test_annotate_epistemic_status_calls_pg_ripple() -> None:
    """annotate_epistemic_status calls pg_ripple.load_triples_with_confidence."""
    from riverbank.epistemic import EpistemicStatus, annotate_epistemic_status

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    result = annotate_epistemic_status(
        conn,
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        status=EpistemicStatus.EXTRACTED,
    )

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "load_triples_with_confidence" in sql


def test_annotate_epistemic_status_writes_correct_status_value() -> None:
    """annotate_epistemic_status writes the correct status literal."""
    import json

    from riverbank.epistemic import (
        EpistemicStatus,
        _PGC_EPISTEMIC_STATUS,
        annotate_epistemic_status,
    )

    conn = mock.MagicMock()
    conn.execute.return_value = mock.MagicMock()

    annotate_epistemic_status(
        conn,
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        status=EpistemicStatus.VERIFIED,
    )

    params = conn.execute.call_args[0][1]
    triples = json.loads(params[0])
    status_triples = [t for t in triples if t["predicate"] == _PGC_EPISTEMIC_STATUS]
    assert len(status_triples) == 1
    assert status_triples[0]["object"] == "verified"


def test_annotate_epistemic_status_returns_false_on_pg_ripple_missing() -> None:
    """annotate_epistemic_status returns False when pg_ripple is unavailable."""
    from riverbank.epistemic import EpistemicStatus, annotate_epistemic_status

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = annotate_epistemic_status(
        conn,
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        status=EpistemicStatus.EXTRACTED,
    )

    assert result is False


def test_get_epistemic_status_returns_none_without_pg_ripple() -> None:
    """get_epistemic_status returns None when pg_ripple is unavailable."""
    from riverbank.epistemic import get_epistemic_status

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = get_epistemic_status(conn, "http://example.org/entity/Acme", "http://example.org/ns/hasCEO")
    assert result is None


def test_get_epistemic_status_returns_status_from_db() -> None:
    """get_epistemic_status parses the status from a pg_ripple row."""
    from riverbank.epistemic import EpistemicStatus, get_epistemic_status

    conn = mock.MagicMock()
    row = mock.MagicMock()
    row._mapping = {"status": "verified"}
    conn.execute.return_value.fetchall.return_value = [row]

    result = get_epistemic_status(
        conn,
        "http://example.org/entity/Acme",
        "http://example.org/ns/hasCEO",
    )

    assert result == EpistemicStatus.VERIFIED


def test_get_epistemic_status_returns_none_when_no_rows() -> None:
    """get_epistemic_status returns None when no annotation exists."""
    from riverbank.epistemic import get_epistemic_status

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    result = get_epistemic_status(
        conn,
        "http://example.org/entity/Acme",
        "http://example.org/ns/hasCEO",
    )

    assert result is None


def test_transition_status_blocks_invalid_transition() -> None:
    """transition_status returns (False, reason) for invalid transitions."""
    from riverbank.epistemic import EpistemicStatus, transition_status

    conn = mock.MagicMock()
    # Return 'deprecated' as current status
    row = mock.MagicMock()
    row._mapping = {"status": "deprecated"}
    conn.execute.return_value.fetchall.return_value = [row]

    ok, reason = transition_status(
        conn,
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        to_status=EpistemicStatus.VERIFIED,  # deprecated → verified is invalid
    )

    assert ok is False
    assert "invalid transition" in reason


def test_transition_status_allows_valid_transition() -> None:
    """transition_status returns (True, '') for valid transitions."""
    from riverbank.epistemic import EpistemicStatus, transition_status

    conn = mock.MagicMock()
    # Mock: current status is 'extracted'
    fetch_row = mock.MagicMock()
    fetch_row._mapping = {"status": "extracted"}

    call_count = [0]

    def side_effect(*args, **kwargs):
        result = mock.MagicMock()
        if call_count[0] == 0:
            # First call: get_epistemic_status SPARQL query
            result.fetchall.return_value = [fetch_row]
        else:
            # Second call: annotate_epistemic_status write
            result.fetchall.return_value = []
        call_count[0] += 1
        return result

    conn.execute.side_effect = side_effect

    ok, reason = transition_status(
        conn,
        subject="http://example.org/entity/Acme",
        predicate="http://example.org/ns/hasCEO",
        to_status=EpistemicStatus.VERIFIED,  # extracted → verified is valid
    )

    assert ok is True
    assert reason == ""


def test_epistemic_status_values_are_strings() -> None:
    """All EpistemicStatus values are plain lowercase strings."""
    from riverbank.epistemic import EpistemicStatus

    for status in EpistemicStatus:
        assert status.value == status.value.lower()
        assert " " not in status.value
