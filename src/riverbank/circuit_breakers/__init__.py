from __future__ import annotations

"""Circuit breakers for LLM provider calls (v0.7.0).

Protects OpenAI, Anthropic, and Ollama provider calls with per-provider
concurrency limits and a circuit breaker pattern.  When the circuit is open
(provider is misbehaving) new calls fail fast without blocking worker threads
or accumulating LLM costs.

``aiobreaker`` is used as the circuit breaker library.  When it is not
installed the module degrades gracefully — a pass-through wrapper is used
instead so the rest of riverbank can import and call this module
unconditionally.

Circuit state is maintained in-process.  In a multi-replica deployment each
replica maintains independent state, which is appropriate for protecting
against upstream API failures (the replica closest to the overload will open
first, others will follow as they see failures).

Relay pipeline circuit breakers (pg-tide transport layer) are configured via
``tide.relay_outbox_config`` SQL — no Python code is required in riverbank
for those.  ``riverbank health`` surfaces open relay circuits from
``tide.relay_circuit_breaker_status`` alongside the extension stack checks.
"""

import functools
import logging
import threading
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Optional aiobreaker import
# ---------------------------------------------------------------------------

try:
    from aiobreaker import CircuitBreaker, CircuitBreakerError  # type: ignore[import-untyped]

    _AIOBREAKER_AVAILABLE = True
except ImportError:
    _AIOBREAKER_AVAILABLE = False
    CircuitBreaker = None  # type: ignore[assignment,misc]

    class CircuitBreakerError(Exception):  # type: ignore[no-redef]
        """Stub raised when the circuit is open."""


# ---------------------------------------------------------------------------
# Supported provider names
# ---------------------------------------------------------------------------

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OLLAMA = "ollama"
PROVIDER_AZURE_OPENAI = "azure-openai"
PROVIDER_VLLM = "vllm"

_SUPPORTED_PROVIDERS = {
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_OLLAMA,
    PROVIDER_AZURE_OPENAI,
    PROVIDER_VLLM,
}

# ---------------------------------------------------------------------------
# Default circuit breaker configuration
# ---------------------------------------------------------------------------

_DEFAULT_FAIL_MAX = 5          # Open after 5 consecutive failures
_DEFAULT_RESET_TIMEOUT = 60    # Seconds before half-open attempt
_DEFAULT_CONCURRENCY = 10      # Max concurrent calls per provider (semaphore)


# ---------------------------------------------------------------------------
# Registry: one circuit breaker + semaphore per provider
# ---------------------------------------------------------------------------

class ProviderCircuit:
    """Combines a circuit breaker with a concurrency semaphore."""

    def __init__(
        self,
        provider: str,
        fail_max: int = _DEFAULT_FAIL_MAX,
        reset_timeout: int = _DEFAULT_RESET_TIMEOUT,
        max_concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self.provider = provider
        self._semaphore = threading.Semaphore(max_concurrency)
        self._fail_count = 0
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._state = "closed"  # closed | open | half-open
        self._lock = threading.Lock()

        # Wrap with aiobreaker if available; otherwise use our own simple impl
        if _AIOBREAKER_AVAILABLE and CircuitBreaker is not None:
            import datetime  # noqa: PLC0415

            self._breaker = CircuitBreaker(
                fail_max=fail_max,
                reset_timeout=datetime.timedelta(seconds=reset_timeout),
            )
        else:
            self._breaker = None

    @property
    def state(self) -> str:
        """Return the circuit state: 'closed', 'open', or 'half-open'."""
        if self._breaker is not None:
            return str(self._breaker.current_state)
        return self._state

    @property
    def is_open(self) -> bool:
        """True when the circuit is open (calls will be rejected)."""
        return self.state == "open"

    def record_success(self) -> None:
        """Reset failure count on success."""
        with self._lock:
            self._fail_count = 0
            self._state = "closed"

    def record_failure(self) -> None:
        """Increment failure count; open the circuit when threshold is reached."""
        with self._lock:
            self._fail_count += 1
            if self._fail_count >= self._fail_max:
                self._state = "open"
                logger.warning(
                    "circuit_breaker: circuit opened for provider=%r "
                    "after %d consecutive failures",
                    self.provider,
                    self._fail_count,
                )

    def reset(self) -> None:
        """Manually reset the circuit to closed state (for testing / admin use)."""
        with self._lock:
            self._fail_count = 0
            self._state = "closed"
        if self._breaker is not None:
            try:
                self._breaker._state_storage._failure_count = 0  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute ``fn`` under the circuit breaker and concurrency semaphore.

        Raises ``CircuitBreakerError`` when the circuit is open.
        Raises ``ProviderConcurrencyError`` when the semaphore cannot be
        acquired within a short timeout.
        """
        if self._state == "open" and self._breaker is None:
            raise CircuitBreakerError(
                f"Circuit open for provider {self.provider!r} — "
                "provider appears to be unavailable."
            )

        acquired = self._semaphore.acquire(timeout=5)
        if not acquired:
            raise ProviderConcurrencyError(
                f"Concurrency limit reached for provider {self.provider!r}."
            )
        try:
            if self._breaker is not None:
                result = self._breaker.call(fn, *args, **kwargs)
            else:
                result = fn(*args, **kwargs)
            self.record_success()
            return result
        except CircuitBreakerError:
            raise
        except Exception as exc:
            self.record_failure()
            raise
        finally:
            self._semaphore.release()


class ProviderConcurrencyError(Exception):
    """Raised when the concurrency limit for a provider is exceeded."""


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_circuits: dict[str, ProviderCircuit] = {}
_registry_lock = threading.Lock()


def get_circuit(
    provider: str,
    fail_max: int = _DEFAULT_FAIL_MAX,
    reset_timeout: int = _DEFAULT_RESET_TIMEOUT,
    max_concurrency: int = _DEFAULT_CONCURRENCY,
) -> ProviderCircuit:
    """Return (or create) the ProviderCircuit for the given provider name."""
    with _registry_lock:
        if provider not in _circuits:
            _circuits[provider] = ProviderCircuit(
                provider=provider,
                fail_max=fail_max,
                reset_timeout=reset_timeout,
                max_concurrency=max_concurrency,
            )
        return _circuits[provider]


def reset_all_circuits() -> None:
    """Reset all circuits to closed state.  Intended for tests and admin tooling."""
    with _registry_lock:
        for circuit in _circuits.values():
            circuit.reset()


def circuit_health() -> dict[str, dict[str, Any]]:
    """Return a snapshot of all circuit breaker states.

    Returns a dict keyed by provider name, with ``state``, ``fail_count``,
    and ``is_open`` fields.
    """
    with _registry_lock:
        return {
            name: {
                "provider": name,
                "state": c.state,
                "fail_count": c._fail_count,
                "is_open": c.is_open,
            }
            for name, c in _circuits.items()
        }


def protected(provider: str) -> Callable[[F], F]:
    """Decorator that wraps a function with the provider circuit breaker.

    Usage::

        @protected("openai")
        def call_openai(prompt: str) -> str:
            ...
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            circuit = get_circuit(provider)
            return circuit.call(fn, *args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
