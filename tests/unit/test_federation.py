"""Unit tests for federated compilation via SPARQL SERVICE (v0.9.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_federation_endpoint_fields() -> None:
    """FederationEndpoint stores all required fields."""
    from riverbank.federation import FederationEndpoint

    ep = FederationEndpoint(
        name="peer-alpha",
        sparql_url="https://peer.example.com/sparql",
        named_graph="http://peer.example.com/graph/trusted",
        confidence_weight=0.75,
        timeout_seconds=45,
    )

    assert ep.name == "peer-alpha"
    assert ep.sparql_url == "https://peer.example.com/sparql"
    assert ep.named_graph == "http://peer.example.com/graph/trusted"
    assert ep.confidence_weight == 0.75
    assert ep.timeout_seconds == 45


def test_federation_endpoint_defaults() -> None:
    """FederationEndpoint has sensible defaults."""
    from riverbank.federation import FederationEndpoint

    ep = FederationEndpoint(name="test", sparql_url="https://test.example.com/sparql")

    assert ep.confidence_weight == 0.8
    assert ep.timeout_seconds == 30
    assert "trusted" in ep.named_graph


def test_federation_result_fields() -> None:
    """FederationResult stores all required fields."""
    from riverbank.federation import FederationResult

    res = FederationResult(
        endpoint_name="peer-alpha",
        triples_fetched=42,
        triples_written=42,
        success=True,
    )

    assert res.endpoint_name == "peer-alpha"
    assert res.triples_fetched == 42
    assert res.triples_written == 42
    assert res.success is True
    assert res.error == ""


def test_build_service_query_contains_service_keyword() -> None:
    """build_service_query produces a SPARQL query with SERVICE keyword."""
    from riverbank.federation import FederationEndpoint, build_service_query

    ep = FederationEndpoint(
        name="peer",
        sparql_url="https://peer.example.com/sparql",
    )
    query = build_service_query(ep)

    assert "SERVICE" in query
    assert "peer.example.com" in query
    assert "?subject" in query
    assert "?predicate" in query
    assert "?object" in query


def test_build_service_query_includes_named_graph() -> None:
    """build_service_query includes GRAPH clause with the remote named graph."""
    from riverbank.federation import FederationEndpoint, build_service_query

    ep = FederationEndpoint(
        name="peer",
        sparql_url="https://peer.example.com/sparql",
        named_graph="http://peer.example.com/graph/trusted",
    )
    query = build_service_query(ep)

    assert "GRAPH" in query
    assert "http://peer.example.com/graph/trusted" in query


def test_build_service_query_respects_limit() -> None:
    """build_service_query includes the LIMIT clause."""
    from riverbank.federation import FederationEndpoint, build_service_query

    ep = FederationEndpoint(name="peer", sparql_url="https://peer.example.com/sparql")
    query = build_service_query(ep, limit=250)

    assert "LIMIT 250" in query


def test_register_federation_endpoint_calls_db() -> None:
    """register_federation_endpoint calls CREATE TABLE + INSERT/UPSERT."""
    from riverbank.federation import FederationEndpoint, register_federation_endpoint

    conn = mock.MagicMock()
    ep = FederationEndpoint(name="peer-alpha", sparql_url="https://peer.example.com/sparql")
    result = register_federation_endpoint(conn, ep)

    assert result is True
    assert conn.execute.call_count == 2


def test_register_federation_endpoint_upserts_by_name() -> None:
    """register_federation_endpoint uses ON CONFLICT (name) DO UPDATE."""
    from riverbank.federation import FederationEndpoint, register_federation_endpoint

    conn = mock.MagicMock()
    ep = FederationEndpoint(name="peer", sparql_url="https://peer.example.com/sparql")
    register_federation_endpoint(conn, ep)

    insert_call = conn.execute.call_args_list[1][0][0]
    assert "ON CONFLICT" in insert_call
    assert "DO UPDATE" in insert_call


def test_register_federation_endpoint_returns_false_on_error() -> None:
    """register_federation_endpoint returns False when DB call fails."""
    from riverbank.federation import FederationEndpoint, register_federation_endpoint

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("connection refused")
    ep = FederationEndpoint(name="peer", sparql_url="https://peer.example.com/sparql")

    result = register_federation_endpoint(conn, ep)
    assert result is False


def test_list_federation_endpoints_returns_empty_on_error() -> None:
    """list_federation_endpoints returns [] when table does not exist."""
    from riverbank.federation import list_federation_endpoints

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("relation does not exist")

    result = list_federation_endpoints(conn)
    assert result == []


def test_list_federation_endpoints_returns_endpoint_objects() -> None:
    """list_federation_endpoints converts DB rows to FederationEndpoint objects."""
    from riverbank.federation import FederationEndpoint, list_federation_endpoints

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        ("peer-alpha", "https://peer.example.com/sparql",
         "http://peer.example.com/graph/trusted", 0.8, 30),
    ]

    endpoints = list_federation_endpoints(conn)
    assert len(endpoints) == 1
    assert endpoints[0].name == "peer-alpha"
    assert endpoints[0].sparql_url == "https://peer.example.com/sparql"
    assert endpoints[0].confidence_weight == 0.8


def test_federated_compile_returns_success_with_empty_rows() -> None:
    """federated_compile returns success with 0 triples when remote is empty."""
    from riverbank.federation import FederationEndpoint, federated_compile

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    ep = FederationEndpoint(name="peer", sparql_url="https://peer.example.com/sparql")
    result = federated_compile(conn, ep)

    assert result.success is True
    assert result.triples_fetched == 0
    assert result.triples_written == 0


def test_federated_compile_writes_remote_triples_locally() -> None:
    """federated_compile calls load_triples_with_confidence for fetched triples."""
    from riverbank.federation import FederationEndpoint, federated_compile

    conn = mock.MagicMock()
    # First execute call (SERVICE query) returns rows
    # Second execute call (load_triples_with_confidence) returns nothing
    conn.execute.return_value.fetchall.return_value = [
        ("http://example.org/entity/A", "http://example.org/ns/name", "Alice"),
        ("http://example.org/entity/B", "http://example.org/ns/name", "Bob"),
    ]

    ep = FederationEndpoint(name="peer", sparql_url="https://peer.example.com/sparql")
    result = federated_compile(conn, ep)

    assert result.success is True
    assert result.triples_fetched == 2
    assert result.triples_written == 2
    # Second call should be load_triples_with_confidence
    write_call = conn.execute.call_args_list[1][0]
    assert "load_triples_with_confidence" in write_call[0]


def test_federated_compile_applies_confidence_weight() -> None:
    """federated_compile applies endpoint.confidence_weight to remote triples."""
    import json

    from riverbank.federation import FederationEndpoint, federated_compile

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        ("http://example.org/A", "http://example.org/p", "value"),
    ]

    ep = FederationEndpoint(
        name="peer", sparql_url="https://peer.example.com/sparql", confidence_weight=0.6
    )
    federated_compile(conn, ep)

    write_call = conn.execute.call_args_list[1][0]
    # write_call is (sql, params_tuple); params_tuple[0] is the JSON string
    params = write_call[1]
    payload = json.loads(params[0])
    assert payload[0]["confidence"] == 0.6


def test_federated_compile_returns_failure_on_service_query_error() -> None:
    """federated_compile returns FederationResult(success=False) when SERVICE query fails."""
    from riverbank.federation import FederationEndpoint, federated_compile

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("SPARQL SERVICE not available")

    ep = FederationEndpoint(name="peer", sparql_url="https://peer.example.com/sparql")
    result = federated_compile(conn, ep)

    assert result.success is False
    assert "SERVICE" in result.error or "not available" in result.error
