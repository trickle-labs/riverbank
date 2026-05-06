from __future__ import annotations

"""Markdown / JSON-LD / HTML page rendering and SSE streaming (v0.9.0).

``riverbank render`` generates entity pages, topic surveys, comparison tables,
and change digests from compiled artifacts.

Output formats:
- **Markdown** (Obsidian/MkDocs) — ``--format markdown``
- **JSON-LD** — ``--format jsonld``
- **HTML** — ``--format html``

Render scheduling:
- Rendered pages are stored as ``pgc:RenderedPage`` artifacts with dependency
  edges to their source facts.
- When facts change, pages are flagged stale and regenerated in the next render
  flow.

Streaming render:
- An SSE (Server-Sent Events) generator emits page updates as the underlying
  graph changes, for live documentation sites.

The rendering logic assembles SPARQL query results into templates.  No LLM
calls are made by the render engine itself; it operates entirely on the
compiled graph.
"""

import json as _json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Generator, Iterator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pgc: vocabulary IRIs
# ---------------------------------------------------------------------------

_PGC_RENDERED_PAGE = "http://schema.pgc.example/RenderedPage"
_PGC_PAGE_FORMAT = "http://schema.pgc.example/pageFormat"
_PGC_PAGE_CONTENT = "http://schema.pgc.example/pageContent"
_PGC_PAGE_STALE = "http://schema.pgc.example/pageStale"
_PGC_SOURCE_FACT = "http://schema.pgc.example/sourceFact"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_DCT_TITLE = "http://purl.org/dc/terms/title"
_DCT_MODIFIED = "http://purl.org/dc/terms/modified"

_RENDER_GRAPH = "http://riverbank.example/graph/rendered"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RenderFormat(str, Enum):
    """Supported output formats for ``riverbank render``."""

    MARKDOWN = "markdown"
    JSONLD = "jsonld"
    HTML = "html"


class PageType(str, Enum):
    """Type of page to render."""

    ENTITY = "entity"
    TOPIC_SURVEY = "topic_survey"
    COMPARISON_TABLE = "comparison_table"
    CHANGE_DIGEST = "change_digest"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RenderRequest:
    """Parameters for a single render operation.

    Attributes:
        entity_iri:   IRI of the entity or topic to render.
        page_type:    Kind of page to produce.
        fmt:          Output format.
        named_graph:  Source named graph for fact retrieval.
        output_path:  Where to write the rendered file (None = return as string).
    """

    entity_iri: str
    page_type: PageType = PageType.ENTITY
    fmt: RenderFormat = RenderFormat.MARKDOWN
    named_graph: str = "http://riverbank.example/graph/trusted"
    output_path: str | None = None


@dataclass
class RenderedPage:
    """A rendered page artifact.

    Attributes:
        page_iri:     IRI of the ``pgc:RenderedPage`` artifact.
        entity_iri:   IRI of the entity or topic this page describes.
        fmt:          Output format.
        content:      Rendered content string.
        source_facts: IRIs of the facts this page depends on.
        stale:        Whether the page needs regeneration.
    """

    page_iri: str
    entity_iri: str
    fmt: RenderFormat
    content: str
    source_facts: list[str] = field(default_factory=list)
    stale: bool = False


# ---------------------------------------------------------------------------
# SPARQL helpers — fetch entity facts
# ---------------------------------------------------------------------------

def _fetch_entity_facts(
    conn: Any,
    entity_iri: str,
    named_graph: str,
) -> list[dict[str, str]]:
    """Fetch all facts about an entity from the named graph.

    Returns a list of ``{predicate, object}`` dicts.
    Falls back to an empty list on error.
    """
    sparql = (
        "SELECT ?predicate ?object WHERE {"
        f"  GRAPH <{named_graph}> {{"
        f"    <{entity_iri}> ?predicate ?object ."
        "  }"
        "}"
    )
    try:
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
        
        rows = sparql_query(conn, sparql)
        return [{"predicate": str(r.get("predicate", r.get(list(r.keys())[0] if r else None))), "object": str(r.get("object", r.get(list(r.keys())[1] if len(r) > 1 else None)))} for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_entity_facts failed for %s: %s", entity_iri, exc)
        return []


# ---------------------------------------------------------------------------
# Rendering functions
# ---------------------------------------------------------------------------

def render_entity_markdown(entity_iri: str, facts: list[dict[str, str]]) -> str:
    """Render an entity page in Markdown format.

    Produces a simple MkDocs/Obsidian-compatible Markdown document with:
    - H1 title from ``dct:title`` or the entity IRI.
    - A properties table listing all (predicate, object) pairs.
    - Citation back-links as footnotes.
    """
    title = entity_iri
    for f in facts:
        if f["predicate"] == _DCT_TITLE:
            title = f["object"]
            break

    lines: list[str] = [
        f"# {title}",
        "",
        f"> IRI: `{entity_iri}`",
        "",
        "## Properties",
        "",
        "| Predicate | Value |",
        "|-----------|-------|",
    ]
    for f in facts:
        pred = f["predicate"].rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        obj = f["object"]
        lines.append(f"| `{pred}` | {obj} |")

    if not facts:
        lines.append("| — | No facts found |")

    lines.extend(["", "---", f"*Generated by riverbank render from `{entity_iri}`.*", ""])
    return "\n".join(lines)


def render_entity_jsonld(entity_iri: str, facts: list[dict[str, str]]) -> str:
    """Render an entity page as JSON-LD."""
    doc: dict[str, Any] = {
        "@context": {
            "pgc": "http://schema.pgc.example/",
            "dct": "http://purl.org/dc/terms/",
            "prov": "http://www.w3.org/ns/prov#",
        },
        "@id": entity_iri,
        "@type": "pgc:RenderedPage",
    }
    for f in facts:
        pred = f["predicate"].rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        val = f["object"]
        if pred in doc:
            existing = doc[pred]
            if isinstance(existing, list):
                existing.append(val)
            else:
                doc[pred] = [existing, val]
        else:
            doc[pred] = val
    return _json.dumps(doc, indent=2, ensure_ascii=False)


def render_entity_html(entity_iri: str, facts: list[dict[str, str]]) -> str:
    """Render an entity page as minimal HTML."""
    title = entity_iri
    for f in facts:
        if f["predicate"] == _DCT_TITLE:
            title = f["object"]
            break

    rows_html = "".join(
        f"<tr><td><code>{f['predicate'].rsplit('/', 1)[-1]}</code></td>"
        f"<td>{f['object']}</td></tr>\n"
        for f in facts
    ) or "<tr><td colspan='2'>No facts found</td></tr>"

    return (
        f"<!DOCTYPE html>\n<html lang='en'>\n<head><meta charset='utf-8'>"
        f"<title>{title}</title></head>\n<body>\n"
        f"<h1>{title}</h1>\n"
        f"<p>IRI: <code>{entity_iri}</code></p>\n"
        f"<table border='1'><thead><tr><th>Predicate</th><th>Value</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>\n"
        f"<footer><em>Generated by riverbank render.</em></footer>\n"
        f"</body>\n</html>"
    )


# ---------------------------------------------------------------------------
# Render dispatch
# ---------------------------------------------------------------------------

def render_page(
    conn: Any,
    request: RenderRequest,
) -> RenderedPage:
    """Render a single entity page.

    Fetches facts from the compiled graph and renders them in the requested
    format.  Writes the result to ``output_path`` if specified.

    Returns a :class:`RenderedPage` instance.
    """
    facts = _fetch_entity_facts(conn, request.entity_iri, request.named_graph)

    content: str
    if request.fmt == RenderFormat.MARKDOWN:
        content = render_entity_markdown(request.entity_iri, facts)
    elif request.fmt == RenderFormat.JSONLD:
        content = render_entity_jsonld(request.entity_iri, facts)
    else:
        content = render_entity_html(request.entity_iri, facts)

    page_iri = f"{_RENDER_GRAPH}/{_slug(request.entity_iri)}/{request.fmt.value}"
    source_facts = [f["predicate"] for f in facts]

    page = RenderedPage(
        page_iri=page_iri,
        entity_iri=request.entity_iri,
        fmt=request.fmt,
        content=content,
        source_facts=source_facts,
    )

    if request.output_path:
        path = Path(request.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Rendered page written to %s", path)

    return page


def _slug(iri: str) -> str:
    """Produce a filesystem-safe slug from an IRI."""
    return iri.replace("://", "_").replace("/", "_").replace(":", "_").strip("_")[:80]


# ---------------------------------------------------------------------------
# Render scheduling — pgc:RenderedPage artifacts
# ---------------------------------------------------------------------------

def persist_rendered_page(conn: Any, page: RenderedPage) -> bool:
    """Persist a ``pgc:RenderedPage`` artifact with dependency edges.

    Writes four triples per page:
    1. ``<page_iri> rdf:type pgc:RenderedPage``
    2. ``<page_iri> pgc:pageFormat "<fmt>"``
    3. ``<page_iri> pgc:pageContent "<content>"``
    4. ``<page_iri> pgc:pageStale "false"``

    Plus one ``pgc:sourceFact`` triple per source fact.

    Falls back gracefully when pg_ripple is unavailable.
    """
    import json as _json  # noqa: PLC0415

    triples = [
        {
            "subject": page.page_iri,
            "predicate": _RDF_TYPE,
            "object": _PGC_RENDERED_PAGE,
            "confidence": 1.0,
        },
        {
            "subject": page.page_iri,
            "predicate": _PGC_PAGE_FORMAT,
            "object": page.fmt.value,
            "confidence": 1.0,
        },
        {
            "subject": page.page_iri,
            "predicate": _PGC_PAGE_CONTENT,
            "object": page.content,
            "confidence": 1.0,
        },
        {
            "subject": page.page_iri,
            "predicate": _PGC_PAGE_STALE,
            "object": str(page.stale).lower(),
            "confidence": 1.0,
        },
    ]
    for fact_iri in page.source_facts[:20]:  # cap to avoid huge payloads
        triples.append(
            {
                "subject": page.page_iri,
                "predicate": _PGC_SOURCE_FACT,
                "object": fact_iri,
                "confidence": 1.0,
            }
        )

    try:
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1, $2)",
            (_json.dumps(triples), _RENDER_GRAPH),
        )
        logger.info("Persisted pgc:RenderedPage %s", page.page_iri)
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if any(
            kw in msg
            for kw in ("pg_ripple", "does not exist", "load_triples_with_confidence")
        ):
            logger.warning(
                "pg_ripple not available — pgc:RenderedPage persistence skipped: %s", exc
            )
        else:
            logger.error("Failed to persist rendered page %s: %s", page.page_iri, exc)
        return False


def mark_pages_stale(conn: Any, fact_iri: str) -> int:
    """Mark all rendered pages that depend on ``fact_iri`` as stale.

    Updates ``pgc:pageStale`` to ``"true"`` for all pages that list
    ``fact_iri`` as a ``pgc:sourceFact``.

    Returns the number of pages marked stale (0 when pg_ripple is unavailable).
    """
    sparql_find = (
        "SELECT ?page WHERE {"
        f"  GRAPH <{_RENDER_GRAPH}> {{"
        f"    ?page <{_PGC_SOURCE_FACT}> <{fact_iri}> ."
        "  }"
        "}"
    )
    try:
        from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
        
        rows = sparql_query(conn, sparql_find)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mark_pages_stale: could not query pages: %s", exc)
        return 0

    count = 0
    import json as _json  # noqa: PLC0415

    for row in rows:
        page_iri = str(row[0])
        payload = [
            {
                "subject": page_iri,
                "predicate": _PGC_PAGE_STALE,
                "object": "true",
                "confidence": 1.0,
            }
        ]
        try:
            conn.execute(
                "SELECT pg_ripple.load_triples_with_confidence($1, $2)",
                (_json.dumps(payload), _RENDER_GRAPH),
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("mark_pages_stale: could not update page %s: %s", page_iri, exc)

    return count


# ---------------------------------------------------------------------------
# Streaming render — SSE
# ---------------------------------------------------------------------------

def sse_event(event_type: str, data: str) -> str:
    """Format a single SSE event string."""
    return f"event: {event_type}\ndata: {data}\n\n"


def streaming_render_generator(
    conn: Any,
    entity_iris: list[str],
    named_graph: str = "http://riverbank.example/graph/trusted",
    fmt: RenderFormat = RenderFormat.MARKDOWN,
    poll_interval_seconds: float = 5.0,
    max_iterations: int = 0,
) -> Generator[str, None, None]:
    """Generate SSE events for live page updates.

    Polls the graph for stale ``pgc:RenderedPage`` artifacts and re-renders
    them, emitting one SSE event per updated page.

    This is a generator that yields SSE-formatted strings.  Mount it behind
    a web framework (FastAPI, Starlette, Flask-SSE, etc.) to serve a
    ``text/event-stream`` endpoint.

    Args:
        conn:                   Database connection.
        entity_iris:            IRIs to monitor and render.
        named_graph:            Source named graph.
        fmt:                    Render format for emitted pages.
        poll_interval_seconds:  Seconds between poll cycles.
        max_iterations:         Stop after this many cycles (0 = infinite).
                                Useful for testing.

    Yields:
        SSE-formatted strings (``event: ...\ndata: ...\n\n``).
    """
    iteration = 0
    while True:
        for entity_iri in entity_iris:
            request = RenderRequest(
                entity_iri=entity_iri,
                fmt=fmt,
                named_graph=named_graph,
            )
            try:
                page = render_page(conn, request)
                event_data = _json.dumps(
                    {
                        "entity_iri": page.entity_iri,
                        "page_iri": page.page_iri,
                        "format": page.fmt.value,
                        "content": page.content,
                    },
                    ensure_ascii=False,
                )
                yield sse_event("page_update", event_data)
            except Exception as exc:  # noqa: BLE001
                error_data = _json.dumps(
                    {"entity_iri": entity_iri, "error": str(exc)}
                )
                yield sse_event("render_error", error_data)

        iteration += 1
        if max_iterations > 0 and iteration >= max_iterations:
            yield sse_event("stream_end", _json.dumps({"iterations": iteration}))
            return

        time.sleep(poll_interval_seconds)
