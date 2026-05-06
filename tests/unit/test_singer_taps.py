"""Unit tests for Singer tap configuration (v0.5.0)."""
from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

from riverbank.pipeline import CompilerProfile


def test_compiler_profile_has_singer_taps_field() -> None:
    """CompilerProfile.singer_taps defaults to an empty list."""
    profile = CompilerProfile.default()
    assert hasattr(profile, "singer_taps")
    assert profile.singer_taps == []


def test_compiler_profile_from_yaml_loads_singer_taps(tmp_path: Path) -> None:
    """from_yaml() loads the singer_taps block from YAML."""
    yaml_path = tmp_path / "profile.yaml"
    yaml_path.write_text(
        "name: ingest-profile\n"
        "version: 1\n"
        "extractor: noop\n"
        "singer_taps:\n"
        "  - tap_name: tap-github\n"
        "    config:\n"
        "      base_url: https://api.github.com\n"
        "    stream_maps: {}\n"
        "  - tap_name: tap-slack-search\n"
        "    config:\n"
        "      workspace: myworkspace\n"
        "    stream_maps: {}\n"
    )
    profile = CompilerProfile.from_yaml(yaml_path)
    assert len(profile.singer_taps) == 2
    assert profile.singer_taps[0]["tap_name"] == "tap-github"
    assert profile.singer_taps[1]["tap_name"] == "tap-slack-search"


def test_compiler_profile_singer_taps_default_is_not_shared() -> None:
    """Each CompilerProfile instance has its own singer_taps list (not shared)."""
    p1 = CompilerProfile.default()
    p2 = CompilerProfile.default()
    p1.singer_taps.append({"tap_name": "tap-test"})
    assert p2.singer_taps == []


def test_register_singer_taps_returns_zero_for_empty_list() -> None:
    """register_singer_taps returns 0 when the tap list is empty."""
    from riverbank.catalog.graph import register_singer_taps

    conn = mock.MagicMock()
    result = register_singer_taps(conn, [], "my-profile")
    assert result == 0
    conn.execute.assert_not_called()


def test_register_singer_taps_inserts_each_tap() -> None:
    """register_singer_taps upserts one row per tap entry."""
    from riverbank.catalog.graph import register_singer_taps

    conn = mock.MagicMock()
    taps = [
        {"tap_name": "tap-github", "config": {"base_url": "https://api.github.com"}},
        {"tap_name": "tap-slack-search", "config": {"workspace": "myws"}},
    ]
    result = register_singer_taps(conn, taps, "docs-profile")
    assert result == 2
    # Should have been called twice for INSERT + twice for NOTIFY = 4 total
    assert conn.execute.call_count == 4


def test_register_singer_taps_falls_back_gracefully() -> None:
    """register_singer_taps returns 0 gracefully when tide.relay_inlet_config is absent."""
    from riverbank.catalog.graph import register_singer_taps

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception(
        "relation tide.relay_inlet_config does not exist"
    )
    taps = [{"tap_name": "tap-test", "config": {}}]
    result = register_singer_taps(conn, taps, "my-profile")
    assert result == 0


def test_register_singer_taps_skips_entries_without_tap_name() -> None:
    """Entries missing 'tap_name' are skipped."""
    from riverbank.catalog.graph import register_singer_taps

    conn = mock.MagicMock()
    taps = [
        {"config": {"base_url": "https://example.com"}},  # missing tap_name
        {"tap_name": "tap-valid", "config": {}},
    ]
    result = register_singer_taps(conn, taps, "profile")
    assert result == 1


def test_compiler_profile_has_ner_model_field() -> None:
    """CompilerProfile.ner_model defaults to 'en_core_web_sm'."""
    profile = CompilerProfile.default()
    assert hasattr(profile, "ner_model")
    assert profile.ner_model == "en_core_web_sm"
