"""Unit tests for secret management module (v0.7.0)."""
from __future__ import annotations

import os
import unittest.mock as mock
from pathlib import Path

import pytest


def test_resolve_plain_value_returns_as_is() -> None:
    """A plain string (no interpolation pattern) is returned unchanged."""
    from riverbank.secrets import resolve_secret

    assert resolve_secret("my-literal-api-key") == "my-literal-api-key"


def test_resolve_env_present() -> None:
    """${env:VAR} resolves to the env var value when set."""
    from riverbank.secrets import resolve_secret

    with mock.patch.dict(os.environ, {"TEST_RB_KEY": "secret-value-xyz"}):
        result = resolve_secret("${env:TEST_RB_KEY}")
    assert result == "secret-value-xyz"


def test_resolve_env_missing_raises() -> None:
    """${env:VAR} raises ValueError when the variable is not set."""
    from riverbank.secrets import resolve_secret

    with mock.patch.dict(os.environ, {}, clear=False):
        # Ensure the variable is absent
        os.environ.pop("_RIVERBANK_NONEXISTENT_KEY_XYZ", None)
        with pytest.raises(ValueError, match="_RIVERBANK_NONEXISTENT_KEY_XYZ"):
            resolve_secret("${env:_RIVERBANK_NONEXISTENT_KEY_XYZ}")


def test_resolve_file_present(tmp_path: Path) -> None:
    """${file:/path} resolves to the file contents."""
    from riverbank.secrets import resolve_secret

    secret_file = tmp_path / "api-key.txt"
    secret_file.write_text("file-secret-abc\n")
    result = resolve_secret(f"${{file:{secret_file}}}")
    assert result == "file-secret-abc"


def test_resolve_file_strips_trailing_newline(tmp_path: Path) -> None:
    """${file:/path} strips a trailing newline from the file content."""
    from riverbank.secrets import resolve_secret

    secret_file = tmp_path / "key.txt"
    secret_file.write_text("key-with-newline\n")
    result = resolve_secret(f"${{file:{secret_file}}}")
    assert result == "key-with-newline"


def test_resolve_file_missing_raises() -> None:
    """${file:/nonexistent} raises ValueError."""
    from riverbank.secrets import resolve_secret

    with pytest.raises(ValueError, match="/nonexistent/path/to/key"):
        resolve_secret("${file:/nonexistent/path/to/key}")


def test_resolve_vault_raises_without_hvac() -> None:
    """${vault:...} raises ValueError when hvac is not installed."""
    from riverbank.secrets import _HVAC_AVAILABLE, resolve_secret

    if _HVAC_AVAILABLE:
        pytest.skip("hvac is installed; testing the no-hvac code path is not possible")

    with pytest.raises(ValueError, match="hvac"):
        resolve_secret("${vault:secret/riverbank#openai_key}")


def test_resolve_vault_with_mock_hvac() -> None:
    """${vault:path#key} resolves correctly when hvac is mocked."""
    from riverbank.secrets import resolve_secret

    mock_client = mock.MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"openai_key": "vault-secret-123"}}
    }

    with mock.patch("riverbank.secrets._HVAC_AVAILABLE", True):
        with mock.patch("riverbank.secrets.hvac") as mock_hvac:
            mock_hvac.Client.return_value = mock_client
            result = resolve_secret(
                "${vault:secret/riverbank#openai_key}",
                vault_addr="http://vault:8200",
                vault_token="test-token",
            )

    assert result == "vault-secret-123"


def test_resolve_vault_key_not_found_raises() -> None:
    """${vault:path#key} raises ValueError when the key is absent in the secret data."""
    from riverbank.secrets import resolve_secret

    mock_client = mock.MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"other_key": "value"}}
    }

    with mock.patch("riverbank.secrets._HVAC_AVAILABLE", True):
        with mock.patch("riverbank.secrets.hvac") as mock_hvac:
            mock_hvac.Client.return_value = mock_client
            with pytest.raises(ValueError, match="missing_key"):
                resolve_secret(
                    "${vault:secret/riverbank#missing_key}",
                    vault_addr="http://vault:8200",
                    vault_token="test-token",
                )


def test_resolve_llm_api_key_plain() -> None:
    """resolve_llm_api_key passes through plain keys unchanged."""
    from riverbank.secrets import resolve_llm_api_key

    assert resolve_llm_api_key("sk-plain-key") == "sk-plain-key"


def test_resolve_llm_api_key_env_pattern() -> None:
    """resolve_llm_api_key resolves ${env:VAR} patterns."""
    from riverbank.secrets import resolve_llm_api_key

    with mock.patch.dict(os.environ, {"OPENAI_API_KEY_TEST": "sk-env-resolved"}):
        result = resolve_llm_api_key("${env:OPENAI_API_KEY_TEST}")
    assert result == "sk-env-resolved"


def test_hvac_available_flag_is_bool() -> None:
    """_HVAC_AVAILABLE is a bool."""
    from riverbank.secrets import _HVAC_AVAILABLE

    assert isinstance(_HVAC_AVAILABLE, bool)
