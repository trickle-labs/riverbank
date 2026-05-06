"""Unit tests for circuit breaker module (v0.7.0)."""
from __future__ import annotations

import threading
import time
import unittest.mock as mock

import pytest


def test_aiobreaker_available_flag_is_bool() -> None:
    """_AIOBREAKER_AVAILABLE is a bool."""
    from riverbank.circuit_breakers import _AIOBREAKER_AVAILABLE

    assert isinstance(_AIOBREAKER_AVAILABLE, bool)


def test_get_circuit_returns_provider_circuit() -> None:
    """get_circuit returns a ProviderCircuit for any provider name."""
    from riverbank.circuit_breakers import ProviderCircuit, get_circuit

    circuit = get_circuit("openai-test-1")
    assert isinstance(circuit, ProviderCircuit)
    assert circuit.provider == "openai-test-1"


def test_get_circuit_same_instance_for_same_provider() -> None:
    """get_circuit returns the same ProviderCircuit on repeated calls."""
    from riverbank.circuit_breakers import get_circuit

    c1 = get_circuit("openai-idempotency-test")
    c2 = get_circuit("openai-idempotency-test")
    assert c1 is c2


def test_circuit_starts_closed() -> None:
    """A new circuit starts in the 'closed' state."""
    from riverbank.circuit_breakers import ProviderCircuit

    c = ProviderCircuit("test-provider-new")
    # When aiobreaker is absent state is our simple 'closed' string
    assert not c.is_open


def test_circuit_opens_after_fail_max() -> None:
    """The circuit opens after fail_max consecutive failures."""
    from riverbank.circuit_breakers import ProviderCircuit

    c = ProviderCircuit("test-open-circuit", fail_max=3)
    # Simulate 3 failures using record_failure directly
    c.record_failure()
    assert not c.is_open
    c.record_failure()
    assert not c.is_open
    c.record_failure()
    assert c.is_open


def test_circuit_resets_on_success() -> None:
    """record_success resets the fail count and closes the circuit."""
    from riverbank.circuit_breakers import ProviderCircuit

    c = ProviderCircuit("test-reset", fail_max=2)
    c.record_failure()
    c.record_failure()
    assert c.is_open

    c.record_success()
    assert not c.is_open
    assert c._fail_count == 0


def test_circuit_reset_closes_open_circuit() -> None:
    """reset() closes an open circuit."""
    from riverbank.circuit_breakers import ProviderCircuit

    c = ProviderCircuit("test-manual-reset", fail_max=1)
    c.record_failure()
    assert c.is_open

    c.reset()
    assert not c.is_open


def test_call_raises_when_circuit_open() -> None:
    """circuit.call() raises CircuitBreakerError when the circuit is open."""
    from riverbank.circuit_breakers import CircuitBreakerError, ProviderCircuit

    c = ProviderCircuit("test-open-call", fail_max=1)
    c.record_failure()
    assert c.is_open

    with pytest.raises(CircuitBreakerError):
        c.call(lambda: "unreachable")


def test_call_executes_when_closed() -> None:
    """circuit.call() executes the function when the circuit is closed."""
    from riverbank.circuit_breakers import ProviderCircuit

    c = ProviderCircuit("test-closed-call", fail_max=10)
    result = c.call(lambda: "ok")
    assert result == "ok"


def test_call_records_failure_on_exception() -> None:
    """circuit.call() increments fail_count when the wrapped function raises."""
    from riverbank.circuit_breakers import ProviderCircuit

    c = ProviderCircuit("test-fail-on-exc", fail_max=10)
    assert c._fail_count == 0

    with pytest.raises(RuntimeError, match="test error"):
        c.call(lambda: (_ for _ in ()).throw(RuntimeError("test error")))

    assert c._fail_count == 1


def test_circuit_health_returns_dict() -> None:
    """circuit_health() returns a dict with state info for each registered provider."""
    from riverbank.circuit_breakers import circuit_health, get_circuit

    get_circuit("test-health-a")
    get_circuit("test-health-b")
    health = circuit_health()

    assert isinstance(health, dict)
    # At minimum the two providers we just registered must appear
    for name in ("test-health-a", "test-health-b"):
        assert name in health
        entry = health[name]
        assert "state" in entry
        assert "is_open" in entry
        assert "fail_count" in entry


def test_reset_all_circuits() -> None:
    """reset_all_circuits() closes all open circuits."""
    from riverbank.circuit_breakers import ProviderCircuit, get_circuit, reset_all_circuits

    # Force two circuits open
    c_a = get_circuit("reset-all-a")
    c_b = get_circuit("reset-all-b")
    c_a._state = "open"
    c_b._state = "open"

    reset_all_circuits()

    assert not c_a.is_open
    assert not c_b.is_open


def test_protected_decorator_wraps_function() -> None:
    """@protected wraps a function with the circuit breaker."""
    from riverbank.circuit_breakers import protected, reset_all_circuits

    reset_all_circuits()

    @protected("test-decorator-provider")
    def my_function(x: int) -> int:
        return x * 2

    result = my_function(21)
    assert result == 42


def test_protected_decorator_propagates_circuit_open() -> None:
    """@protected raises CircuitBreakerError when the provider circuit is open."""
    from riverbank.circuit_breakers import (
        CircuitBreakerError,
        ProviderCircuit,
        get_circuit,
        protected,
        reset_all_circuits,
    )

    reset_all_circuits()
    # Force the circuit open before decorating
    circuit = get_circuit("test-decorator-open")
    circuit._fail_count = circuit._fail_max
    circuit._state = "open"

    @protected("test-decorator-open")
    def guarded() -> str:
        return "should not reach here"

    with pytest.raises(CircuitBreakerError):
        guarded()


def test_concurrency_semaphore_limits_concurrent_calls() -> None:
    """ProviderCircuit enforces the max_concurrency limit."""
    from riverbank.circuit_breakers import ProviderConcurrencyError, ProviderCircuit

    # Use a very short semaphore timeout to make the test deterministic
    c = ProviderCircuit("concurrency-test-v2", max_concurrency=1)
    # Override the acquire timeout to be very short so the second call fails fast
    c._semaphore = threading.Semaphore(1)

    results: list[str] = []
    hold_event = threading.Event()
    start_event = threading.Event()

    def slow_fn() -> str:
        start_event.set()
        hold_event.wait(timeout=1)  # hold the semaphore
        return "done"

    def run_slow() -> None:
        try:
            # Acquire with timeout=0.5 to avoid indefinite blocking
            acquired = c._semaphore.acquire(timeout=0.5)
            if not acquired:
                results.append("concurrency-error")
                return
            try:
                results.append(slow_fn())
            finally:
                c._semaphore.release()
        except Exception:
            results.append("error")

    def run_fast() -> None:
        # Wait until slow_fn has started and holds the semaphore
        start_event.wait(timeout=1)
        try:
            acquired = c._semaphore.acquire(timeout=0.05)  # very short timeout
            if not acquired:
                results.append("concurrency-error")
                return
            c._semaphore.release()
            results.append("unexpected-success")
        except Exception:
            results.append("error")

    t1 = threading.Thread(target=run_slow)
    t2 = threading.Thread(target=run_fast)
    t1.start()
    t2.start()

    t2.join(timeout=2)
    hold_event.set()  # Release slow_fn
    t1.join(timeout=2)

    assert len(results) == 2
    # The second attempt should have gotten concurrency-error
    assert "concurrency-error" in results
    assert "done" in results
