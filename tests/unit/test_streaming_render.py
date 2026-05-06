"""Unit tests for SSE streaming render (v0.9.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_sse_event_format() -> None:
    """sse_event produces properly formatted SSE string."""
    from riverbank.rendering import sse_event

    event = sse_event("page_update", '{"key": "value"}')

    assert event.startswith("event: page_update\n")
    assert 'data: {"key": "value"}' in event
    assert event.endswith("\n\n")


def test_sse_event_stream_end_format() -> None:
    """sse_event formats stream_end events correctly."""
    from riverbank.rendering import sse_event

    event = sse_event("stream_end", '{"iterations": 3}')
    assert "event: stream_end" in event
    assert "iterations" in event


def test_streaming_render_generator_yields_page_updates() -> None:
    """streaming_render_generator yields page_update events for each entity."""
    from riverbank.rendering import RenderFormat, streaming_render_generator

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    events = list(
        streaming_render_generator(
            conn,
            entity_iris=["http://example.org/entity/Acme"],
            fmt=RenderFormat.MARKDOWN,
            poll_interval_seconds=0,
            max_iterations=1,
        )
    )

    # Should yield one page_update + one stream_end
    page_updates = [e for e in events if e.startswith("event: page_update")]
    stream_ends = [e for e in events if e.startswith("event: stream_end")]

    assert len(page_updates) == 1
    assert len(stream_ends) == 1


def test_streaming_render_generator_yields_one_event_per_entity() -> None:
    """streaming_render_generator yields one event per entity per iteration."""
    from riverbank.rendering import RenderFormat, streaming_render_generator

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    events = list(
        streaming_render_generator(
            conn,
            entity_iris=[
                "http://example.org/entity/A",
                "http://example.org/entity/B",
                "http://example.org/entity/C",
            ],
            fmt=RenderFormat.MARKDOWN,
            poll_interval_seconds=0,
            max_iterations=1,
        )
    )

    page_updates = [e for e in events if "page_update" in e]
    assert len(page_updates) == 3


def test_streaming_render_generator_stops_at_max_iterations() -> None:
    """streaming_render_generator stops after max_iterations cycles."""
    from riverbank.rendering import RenderFormat, streaming_render_generator

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    events = list(
        streaming_render_generator(
            conn,
            entity_iris=["http://example.org/entity/X"],
            fmt=RenderFormat.MARKDOWN,
            poll_interval_seconds=0,
            max_iterations=3,
        )
    )

    page_updates = [e for e in events if "page_update" in e]
    stream_ends = [e for e in events if "stream_end" in e]

    assert len(page_updates) == 3  # 1 entity × 3 iterations
    assert len(stream_ends) == 1


def test_streaming_render_generator_emits_entity_iri_in_events() -> None:
    """streaming_render_generator includes entity_iri in each page_update event."""
    import json

    from riverbank.rendering import RenderFormat, streaming_render_generator

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    events = list(
        streaming_render_generator(
            conn,
            entity_iris=["http://example.org/entity/Acme"],
            fmt=RenderFormat.JSONLD,
            poll_interval_seconds=0,
            max_iterations=1,
        )
    )

    update_event = next(e for e in events if "page_update" in e)
    data_line = next(l for l in update_event.split("\n") if l.startswith("data: "))
    payload = json.loads(data_line[len("data: "):])

    assert payload["entity_iri"] == "http://example.org/entity/Acme"
    assert payload["format"] == "jsonld"
    assert "content" in payload


def test_streaming_render_generator_emits_render_error_on_failure() -> None:
    """streaming_render_generator emits render_error events when render_page raises."""
    import riverbank.rendering as rendering_mod

    from riverbank.rendering import RenderFormat, streaming_render_generator

    conn = mock.MagicMock()

    with mock.patch.object(rendering_mod, "render_page") as mock_render:
        mock_render.side_effect = Exception("unexpected render failure")
        events = list(
            streaming_render_generator(
                conn,
                entity_iris=["http://example.org/entity/Bad"],
                fmt=RenderFormat.MARKDOWN,
                poll_interval_seconds=0,
                max_iterations=1,
            )
        )

    error_events = [e for e in events if "render_error" in e]
    assert len(error_events) >= 1


def test_streaming_render_generator_stream_end_contains_iteration_count() -> None:
    """streaming_render_generator stream_end event contains the iteration count."""
    import json

    from riverbank.rendering import RenderFormat, streaming_render_generator

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    events = list(
        streaming_render_generator(
            conn,
            entity_iris=["http://example.org/entity/X"],
            fmt=RenderFormat.MARKDOWN,
            poll_interval_seconds=0,
            max_iterations=2,
        )
    )

    stream_end = next(e for e in events if "stream_end" in e)
    data_line = next(l for l in stream_end.split("\n") if l.startswith("data: "))
    payload = json.loads(data_line[len("data: "):])
    assert payload["iterations"] == 2
