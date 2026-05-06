"""Unit tests for Markdown/JSON-LD/HTML page rendering (v0.9.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_render_format_enum_has_three_values() -> None:
    """RenderFormat has exactly 3 values."""
    from riverbank.rendering import RenderFormat

    assert len(list(RenderFormat)) == 3
    assert RenderFormat.MARKDOWN.value == "markdown"
    assert RenderFormat.JSONLD.value == "jsonld"
    assert RenderFormat.HTML.value == "html"


def test_page_type_enum_has_four_values() -> None:
    """PageType has exactly 4 values."""
    from riverbank.rendering import PageType

    assert len(list(PageType)) == 4


def test_render_request_defaults() -> None:
    """RenderRequest has sensible defaults."""
    from riverbank.rendering import PageType, RenderFormat, RenderRequest

    req = RenderRequest(entity_iri="http://example.org/entity/Acme")
    assert req.page_type == PageType.ENTITY
    assert req.fmt == RenderFormat.MARKDOWN
    assert "trusted" in req.named_graph
    assert req.output_path is None


def test_rendered_page_fields() -> None:
    """RenderedPage stores all required fields."""
    from riverbank.rendering import RenderFormat, RenderedPage

    page = RenderedPage(
        page_iri="http://riverbank.example/graph/rendered/acme",
        entity_iri="http://example.org/entity/Acme",
        fmt=RenderFormat.MARKDOWN,
        content="# Acme\n\nSome content.",
        source_facts=["http://example.org/ns/name"],
        stale=False,
    )

    assert page.page_iri == "http://riverbank.example/graph/rendered/acme"
    assert page.entity_iri == "http://example.org/entity/Acme"
    assert page.fmt == RenderFormat.MARKDOWN
    assert "Acme" in page.content
    assert not page.stale


def test_rendered_page_defaults_stale_false() -> None:
    """RenderedPage defaults stale=False."""
    from riverbank.rendering import RenderFormat, RenderedPage

    page = RenderedPage(
        page_iri="iri",
        entity_iri="http://example.org/entity/X",
        fmt=RenderFormat.MARKDOWN,
        content="",
    )
    assert page.stale is False
    assert page.source_facts == []


def test_render_entity_markdown_produces_heading() -> None:
    """render_entity_markdown produces an H1 heading."""
    from riverbank.rendering import render_entity_markdown

    content = render_entity_markdown(
        "http://example.org/entity/Acme",
        [{"predicate": "http://purl.org/dc/terms/title", "object": "Acme Corporation"}],
    )

    assert content.startswith("# Acme Corporation")


def test_render_entity_markdown_uses_iri_as_title_fallback() -> None:
    """render_entity_markdown falls back to the IRI when dct:title is absent."""
    from riverbank.rendering import render_entity_markdown

    content = render_entity_markdown("http://example.org/entity/Foo", [])
    assert "http://example.org/entity/Foo" in content


def test_render_entity_markdown_includes_properties_table() -> None:
    """render_entity_markdown includes a Markdown table with predicates."""
    from riverbank.rendering import render_entity_markdown

    facts = [
        {"predicate": "http://example.org/ns/status", "object": "active"},
        {"predicate": "http://example.org/ns/owner", "object": "Alice"},
    ]
    content = render_entity_markdown("http://example.org/entity/X", facts)

    assert "| Predicate | Value |" in content
    assert "status" in content
    assert "active" in content


def test_render_entity_jsonld_produces_valid_json() -> None:
    """render_entity_jsonld produces parseable JSON-LD."""
    import json

    from riverbank.rendering import render_entity_jsonld

    content = render_entity_jsonld(
        "http://example.org/entity/Acme",
        [{"predicate": "http://example.org/ns/name", "object": "Acme"}],
    )

    doc = json.loads(content)
    assert doc["@id"] == "http://example.org/entity/Acme"
    assert "@context" in doc


def test_render_entity_jsonld_includes_facts() -> None:
    """render_entity_jsonld includes fact predicates as JSON keys."""
    import json

    from riverbank.rendering import render_entity_jsonld

    facts = [{"predicate": "http://example.org/ns/status", "object": "active"}]
    content = render_entity_jsonld("http://example.org/entity/X", facts)
    doc = json.loads(content)

    assert "status" in doc
    assert doc["status"] == "active"


def test_render_entity_html_produces_html_document() -> None:
    """render_entity_html produces a valid HTML document."""
    from riverbank.rendering import render_entity_html

    content = render_entity_html(
        "http://example.org/entity/Acme",
        [{"predicate": "http://example.org/ns/name", "object": "Acme Corp"}],
    )

    assert "<!DOCTYPE html>" in content
    assert "<table" in content
    assert "Acme Corp" in content


def test_render_page_markdown_calls_fetch_and_returns_page(tmp_path) -> None:
    """render_page with format=markdown returns a RenderedPage with content."""
    from riverbank.rendering import RenderFormat, RenderRequest, render_page

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []  # no facts (graceful)

    req = RenderRequest(
        entity_iri="http://example.org/entity/Acme",
        fmt=RenderFormat.MARKDOWN,
    )
    page = render_page(conn, req)

    assert page.entity_iri == "http://example.org/entity/Acme"
    assert page.fmt == RenderFormat.MARKDOWN
    assert isinstance(page.content, str)
    assert len(page.content) > 0


def test_render_page_jsonld_format(tmp_path) -> None:
    """render_page with format=jsonld returns JSON-LD content."""
    import json

    from riverbank.rendering import RenderFormat, RenderRequest, render_page

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    req = RenderRequest(
        entity_iri="http://example.org/entity/Beta",
        fmt=RenderFormat.JSONLD,
    )
    page = render_page(conn, req)

    doc = json.loads(page.content)
    assert "@id" in doc


def test_render_page_html_format(tmp_path) -> None:
    """render_page with format=html returns HTML content."""
    from riverbank.rendering import RenderFormat, RenderRequest, render_page

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    req = RenderRequest(
        entity_iri="http://example.org/entity/Gamma",
        fmt=RenderFormat.HTML,
    )
    page = render_page(conn, req)

    assert "<!DOCTYPE html>" in page.content


def test_render_page_writes_file_when_output_path_set(tmp_path) -> None:
    """render_page writes the rendered content to output_path when specified."""
    from riverbank.rendering import RenderFormat, RenderRequest, render_page

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    output_file = tmp_path / "acme.md"
    req = RenderRequest(
        entity_iri="http://example.org/entity/Acme",
        fmt=RenderFormat.MARKDOWN,
        output_path=str(output_file),
    )
    page = render_page(conn, req)

    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == page.content


def test_persist_rendered_page_calls_pg_ripple() -> None:
    """persist_rendered_page calls pg_ripple.load_triples_with_confidence."""
    from riverbank.rendering import RenderFormat, RenderedPage, persist_rendered_page

    conn = mock.MagicMock()
    page = RenderedPage(
        page_iri="http://riverbank.example/graph/rendered/acme",
        entity_iri="http://example.org/entity/Acme",
        fmt=RenderFormat.MARKDOWN,
        content="# Acme",
        source_facts=["http://example.org/ns/name"],
    )

    result = persist_rendered_page(conn, page)

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "load_triples_with_confidence" in sql


def test_persist_rendered_page_returns_false_on_pg_ripple_missing() -> None:
    """persist_rendered_page returns False when pg_ripple is unavailable."""
    from riverbank.rendering import RenderFormat, RenderedPage, persist_rendered_page

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple.load_triples_with_confidence does not exist")
    page = RenderedPage(
        page_iri="iri",
        entity_iri="http://example.org/entity/X",
        fmt=RenderFormat.MARKDOWN,
        content="# X",
    )

    result = persist_rendered_page(conn, page)
    assert result is False


def test_persist_rendered_page_includes_pgc_rendered_page_type() -> None:
    """persist_rendered_page includes pgc:RenderedPage rdf:type triple."""
    import json

    from riverbank.rendering import (
        RenderFormat,
        RenderedPage,
        _PGC_RENDERED_PAGE,
        persist_rendered_page,
    )

    conn = mock.MagicMock()
    page = RenderedPage(
        page_iri="http://riverbank.example/graph/rendered/x",
        entity_iri="http://example.org/entity/X",
        fmt=RenderFormat.MARKDOWN,
        content="# X",
    )
    persist_rendered_page(conn, page)

    # call_args[0] is positional args tuple: (sql, (json_str, graph_iri))
    call_positional = conn.execute.call_args[0]
    params = call_positional[1]   # params is (json_str, graph_iri)
    payload = json.loads(params[0])
    types = [t for t in payload if t.get("object") == _PGC_RENDERED_PAGE]
    assert len(types) == 1


def test_mark_pages_stale_returns_zero_on_error() -> None:
    """mark_pages_stale returns 0 when pg_ripple SPARQL is unavailable."""
    from riverbank.rendering import mark_pages_stale

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_ripple not available")

    count = mark_pages_stale(conn, "http://example.org/ns/name")
    assert count == 0


def test_mark_pages_stale_updates_stale_flag() -> None:
    """mark_pages_stale calls load_triples_with_confidence for each stale page."""
    import json

    from riverbank.rendering import _PGC_PAGE_STALE, mark_pages_stale

    conn = mock.MagicMock()
    # First call: sparql_query to find pages
    # Subsequent calls: load_triples_with_confidence for each page
    first_result = mock.MagicMock()
    first_result.fetchall.return_value = [
        ("http://riverbank.example/graph/rendered/acme_markdown",),
        ("http://riverbank.example/graph/rendered/acme_html",),
    ]
    second_result = mock.MagicMock()
    second_result.fetchall.return_value = []
    conn.execute.side_effect = [first_result, second_result, second_result]

    count = mark_pages_stale(conn, "http://example.org/ns/name")
    assert count == 2


def test_slug_produces_filesystem_safe_string() -> None:
    """_slug converts an IRI to a filesystem-safe string."""
    from riverbank.rendering import _slug

    slug = _slug("http://example.org/entity/Acme Corp!")
    assert "/" not in slug
    assert ":" not in slug
    assert len(slug) <= 80
