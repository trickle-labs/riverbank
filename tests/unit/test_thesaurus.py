"""Unit tests for thesaurus-based query expansion (v0.6.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_expand_query_terms_returns_original_when_pg_ripple_unavailable() -> None:
    """expand_query_terms returns the original terms when pg_ripple is absent."""
    from riverbank.catalog.graph import expand_query_terms

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple does not exist")

    result = expand_query_terms(conn, ["Acme", "Corporation"])
    assert result == ["Acme", "Corporation"]


def test_expand_query_terms_returns_empty_for_empty_input() -> None:
    """expand_query_terms returns [] for empty term list."""
    from riverbank.catalog.graph import expand_query_terms

    conn = mock.MagicMock()
    result = expand_query_terms(conn, [])
    assert result == []


def test_expand_query_terms_adds_synonyms() -> None:
    """expand_query_terms includes synonyms from the thesaurus."""
    from riverbank.catalog.graph import expand_query_terms

    conn = mock.MagicMock()
    # Simulate sparql_query returning synonym rows
    synonym_rows = [{"term": "Acme Corp"}, {"term": "Acme Inc"}]

    with mock.patch(
        "riverbank.catalog.graph.sparql_query", return_value=synonym_rows
    ):
        result = expand_query_terms(conn, ["Acme"])

    assert "Acme" in result
    assert "Acme Corp" in result
    assert "Acme Inc" in result


def test_expand_query_terms_deduplicates() -> None:
    """expand_query_terms does not add duplicates."""
    from riverbank.catalog.graph import expand_query_terms

    conn = mock.MagicMock()
    # Return a term that is already in the input
    synonym_rows = [{"term": "Acme"}]  # duplicate of seed

    with mock.patch(
        "riverbank.catalog.graph.sparql_query", return_value=synonym_rows
    ):
        result = expand_query_terms(conn, ["Acme"])

    assert result.count("Acme") == 1


def test_expand_query_terms_uses_thesaurus_graph() -> None:
    """expand_query_terms passes the thesaurus_graph to sparql_query."""
    from riverbank.catalog.graph import expand_query_terms

    conn = mock.MagicMock()
    custom_thesaurus = "http://example.com/graph/my-thesaurus"

    with mock.patch(
        "riverbank.catalog.graph.sparql_query", return_value=[]
    ) as mock_sparql:
        expand_query_terms(conn, ["term"], thesaurus_graph=custom_thesaurus)

    call_kwargs = mock_sparql.call_args
    # named_graph is passed as keyword or positional arg
    assert custom_thesaurus in str(call_kwargs)


def test_sparql_query_with_thesaurus_passthrough_when_no_expand() -> None:
    """sparql_query_with_thesaurus delegates to sparql_query when expand_terms is None."""
    from riverbank.catalog.graph import sparql_query_with_thesaurus

    conn = mock.MagicMock()
    sparql = "SELECT * WHERE { ?s ?p ?o }"

    with mock.patch(
        "riverbank.catalog.graph.sparql_query", return_value=[{"s": "a", "p": "b", "o": "c"}]
    ) as mock_sparql:
        result = sparql_query_with_thesaurus(conn, sparql)

    assert result == [{"s": "a", "p": "b", "o": "c"}]
    assert mock_sparql.called


def test_sparql_query_with_thesaurus_expands_terms() -> None:
    """sparql_query_with_thesaurus expands provided terms and queries with them."""
    from riverbank.catalog.graph import sparql_query_with_thesaurus

    conn = mock.MagicMock()
    sparql = "SELECT * WHERE { ?s ?p ?o }"

    expanded_terms = ["Acme", "Acme Corp", "Acme Inc"]

    with mock.patch(
        "riverbank.catalog.graph.expand_query_terms", return_value=expanded_terms
    ):
        with mock.patch(
            "riverbank.catalog.graph.sparql_query", return_value=[]
        ) as mock_sparql:
            sparql_query_with_thesaurus(conn, sparql, expand_terms=["Acme"])

    # sparql_query should have been called (with augmented query)
    assert mock_sparql.called


def test_thesaurus_expansion_sparql_template_contains_skos_predicates() -> None:
    """The expansion SPARQL template references skos:altLabel and related predicates."""
    from riverbank.catalog.graph import _THESAURUS_EXPANSION_SPARQL

    assert "skos/core#altLabel" in _THESAURUS_EXPANSION_SPARQL
    assert "skos/core#related" in _THESAURUS_EXPANSION_SPARQL
    assert "skos/core#exactMatch" in _THESAURUS_EXPANSION_SPARQL
    assert "skos/core#closeMatch" in _THESAURUS_EXPANSION_SPARQL


def test_thesaurus_graph_constant() -> None:
    """The default thesaurus graph IRI is correct."""
    from riverbank.catalog.graph import _THESAURUS_GRAPH

    assert _THESAURUS_GRAPH == "http://riverbank.example/graph/thesaurus"
