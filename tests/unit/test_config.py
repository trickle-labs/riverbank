from __future__ import annotations

import os

import pytest


def test_default_settings_load() -> None:
    from riverbank.config import get_settings

    s = get_settings()
    assert s.llm.provider == "ollama"
    assert s.llm.api_base.startswith("http")
    assert s.db.dsn.startswith("postgresql+psycopg://")
    assert s.langfuse.enabled is False


def test_env_override_llm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVERBANK_LLM__MODEL", "mistral")
    from riverbank.config import Settings

    s = Settings()
    assert s.llm.model == "mistral"


def test_env_override_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVERBANK_LLM__PROVIDER", "openai")
    monkeypatch.setenv("RIVERBANK_LLM__API_KEY", "sk-test")
    from riverbank.config import Settings

    s = Settings()
    assert s.llm.provider == "openai"
    assert s.llm.api_key == "sk-test"
