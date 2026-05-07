"""Unit tests for graph helpers: emit_outbox_event, load_shape_bundle, run_shape_bundle (v0.4.0)."""
from __future__ import annotations

import unittest.mock as mock

from riverbank.catalog.graph import (
    _normalise_iri_local,
    _to_ntriples_term,
    emit_outbox_event,
    load_shape_bundle,
    run_shape_bundle,
)


def test_emit_outbox_event_calls_pgtrickle() -> None:
    conn = mock.MagicMock()
    result = emit_outbox_event(conn, "semantic_diff", {"fragment_iri": "file:///doc.md#s"})
    assert conn.execute.called


def test_emit_outbox_event_falls_back_when_pgtrickle_missing() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pgtrickle.attach_outbox does not exist")
    # Must not raise
    result = emit_outbox_event(conn, "semantic_diff", {"fragment_iri": "x"})
    assert result is False


def test_emit_outbox_event_raises_on_unexpected_error() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = RuntimeError("connection refused")
    import pytest
    with pytest.raises(RuntimeError):
        emit_outbox_event(conn, "semantic_diff", {"x": "y"})


def test_load_shape_bundle_calls_pg_ripple() -> None:
    conn = mock.MagicMock()
    loaded = load_shape_bundle(conn, "skos-integrity")
    assert conn.execute.called
    assert loaded is True


def test_load_shape_bundle_falls_back_when_pg_ripple_missing() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pg_ripple.load_shape_bundle does not exist")
    result = load_shape_bundle(conn, "skos-integrity")
    assert result is False


def test_run_shape_bundle_returns_empty_when_pg_ripple_missing() -> None:
    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pg_ripple.run_shape_bundle does not exist")
    results = run_shape_bundle(conn, "skos-integrity", "http://test/vocab")
    assert results == []


def test_run_shape_bundle_returns_rows_as_dicts() -> None:
    row = mock.MagicMock()
    row._mapping = {"focus_node": "entity:X", "message": "prefLabel missing"}
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [row]
    results = run_shape_bundle(conn, "skos-integrity", "http://test/vocab")
    assert len(results) == 1
    assert results[0]["focus_node"] == "entity:X"


# ---------------------------------------------------------------------------
# _normalise_iri_local
# ---------------------------------------------------------------------------

def test_normalise_iri_local_no_spaces() -> None:
    assert _normalise_iri_local("createdBy") == "createdBy"


def test_normalise_iri_local_single_space() -> None:
    assert _normalise_iri_local("links back to") == "links_back_to"


def test_normalise_iri_local_multiple_spaces() -> None:
    assert _normalise_iri_local("is  part  of") == "is_part_of"


def test_normalise_iri_local_leading_trailing_space() -> None:
    assert _normalise_iri_local(" hasState ") == "_hasState_"


# ---------------------------------------------------------------------------
# _to_ntriples_term — IRI local part normalisation
# ---------------------------------------------------------------------------

def test_to_ntriples_term_prefixed_no_spaces() -> None:
    assert _to_ntriples_term("ex:createdBy") == "<http://riverbank.example/entities/createdBy>"


def test_to_ntriples_term_prefixed_with_spaces() -> None:
    # Multi-word predicate from LLM: spaces must become underscores
    result = _to_ntriples_term("ex:links back to")
    assert result == "<http://riverbank.example/entities/links_back_to>"
    assert " " not in result


def test_to_ntriples_term_already_bracketed_iri_unchanged() -> None:
    # Pre-existing <…> IRIs with spaces are passed through unchanged
    # (they were already invalid; we don't touch them)
    iri = "<http://riverbank.example/entities/links back to>"
    assert _to_ntriples_term(iri) == iri


def test_to_ntriples_term_plain_literal() -> None:
    assert _to_ntriples_term("Apache 2.0") == '"Apache 2.0"'


def test_to_ntriples_term_rdf_prefix() -> None:
    assert _to_ntriples_term("rdf:type") == "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
