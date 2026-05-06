from __future__ import annotations

"""Secret management for riverbank (v0.7.0).

Resolves LLM API keys and other sensitive values from three sources, in order:

1. Environment variables (always available)
2. HashiCorp Vault via ``hvac`` (optional — falls back gracefully)
3. Kubernetes Secret files (``/var/run/secrets/…``)

The ``${env:VAR}`` and ``${file:/path}`` interpolation patterns are also
supported for relay credentials passed to pg-tide via
``tide.relay_inlet_config``.

Usage::

    from riverbank.secrets import resolve_secret

    api_key = resolve_secret("${env:OPENAI_API_KEY}")
    api_key = resolve_secret("${file:/var/run/secrets/openai-key}")
    api_key = resolve_secret("${vault:secret/riverbank#openai_key}")

All sources are resolved at call time (no caching of secret values) to
ensure rotation takes effect without a worker restart.

No secret value is ever logged.  DEBUG log lines reference only the secret
*reference string*, not the resolved value.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vault client (optional)
# ---------------------------------------------------------------------------

try:
    import hvac  # type: ignore[import-untyped]

    _HVAC_AVAILABLE = True
except ImportError:
    _HVAC_AVAILABLE = False
    hvac = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Resolution patterns
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"^\$\{env:([^}]+)\}$")
_FILE_PATTERN = re.compile(r"^\$\{file:([^}]+)\}$")
_VAULT_PATTERN = re.compile(r"^\$\{vault:([^#}]+)#([^}]+)\}$")


def resolve_secret(reference: str, *, vault_addr: Optional[str] = None,
                   vault_token: Optional[str] = None) -> str:
    """Resolve a secret reference string to its plaintext value.

    Supported reference formats:

    * ``${env:VAR}`` — read ``VAR`` from the process environment.
    * ``${file:/path/to/secret}`` — read the file contents (strip trailing
      newline).
    * ``${vault:secret/path#key}`` — read ``key`` from the HashiCorp Vault KV
      secret at ``secret/path``.
    * Any other string is returned as-is (allows plain text values alongside
      reference strings in config files).

    Raises ``ValueError`` if the referenced environment variable is not set,
    the file does not exist, or Vault is unreachable and the fallback chain
    is exhausted.
    """
    ref = reference.strip()

    # --- env: ---
    m = _ENV_PATTERN.match(ref)
    if m:
        var_name = m.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(
                f"Secret reference {ref!r} references env var {var_name!r} "
                "which is not set."
            )
        logger.debug("secret resolved via env: ref=%r var=%r", ref, var_name)
        return value

    # --- file: ---
    m = _FILE_PATTERN.match(ref)
    if m:
        path = Path(m.group(1))
        if not path.exists():
            raise ValueError(
                f"Secret reference {ref!r} references file {path} which does not exist."
            )
        value = path.read_text(encoding="utf-8").rstrip("\n")
        logger.debug("secret resolved via file: ref=%r path=%s", ref, path)
        return value

    # --- vault: ---
    m = _VAULT_PATTERN.match(ref)
    if m:
        secret_path = m.group(1)
        key = m.group(2)
        return _resolve_vault(ref, secret_path, key,
                              vault_addr=vault_addr, vault_token=vault_token)

    # Plain text value — return as-is
    logger.debug("secret ref is a plain value (no interpolation pattern): ref=%r", ref)
    return ref


def _resolve_vault(ref: str, secret_path: str, key: str,
                   vault_addr: Optional[str] = None,
                   vault_token: Optional[str] = None) -> str:
    """Read a key from a HashiCorp Vault KV secret."""
    if not _HVAC_AVAILABLE:
        raise ValueError(
            f"Secret reference {ref!r} requires the 'hvac' package. "
            "Install it with: pip install hvac"
        )

    addr = vault_addr or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
    token = vault_token or os.environ.get("VAULT_TOKEN", "")

    client = hvac.Client(url=addr, token=token)
    if not client.is_authenticated():
        raise ValueError(
            f"Vault authentication failed for secret reference {ref!r}. "
            f"Check VAULT_ADDR ({addr!r}) and VAULT_TOKEN."
        )

    # Support both KV v1 and v2; try v2 first
    try:
        response = client.secrets.kv.v2.read_secret_version(path=secret_path)
        data = response["data"]["data"]
    except Exception:  # noqa: BLE001
        try:
            response = client.secrets.kv.v1.read_secret(path=secret_path)
            data = response["data"]
        except Exception as exc:
            raise ValueError(
                f"Could not read Vault secret at {secret_path!r}: {exc}"
            ) from exc

    if key not in data:
        raise ValueError(
            f"Key {key!r} not found in Vault secret at {secret_path!r}. "
            f"Available keys: {list(data.keys())}"
        )

    logger.debug("secret resolved via vault: ref=%r path=%r key=%r", ref, secret_path, key)
    return data[key]


def resolve_llm_api_key(settings_api_key: str, *,
                        vault_addr: Optional[str] = None,
                        vault_token: Optional[str] = None) -> str:
    """Resolve the LLM API key from settings, supporting all secret reference formats.

    This is the integration point between ``riverbank.config.LLMSettings``
    and the secret management layer.  The ``api_key`` field in the settings
    object may itself be a reference string (``${env:OPENAI_API_KEY}`` etc.)
    rather than a literal key.
    """
    return resolve_secret(settings_api_key,
                          vault_addr=vault_addr, vault_token=vault_token)
