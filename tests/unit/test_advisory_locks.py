"""Unit tests for multi-replica advisory lock support (v0.7.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_try_acquire_returns_true_on_success() -> None:
    """try_acquire returns True when pg_try_advisory_lock returns True."""
    from riverbank.advisory_locks import try_acquire

    conn = mock.MagicMock()
    mock_row = (True,)
    conn.execute.return_value.fetchone.return_value = mock_row

    result = try_acquire(conn, "file:///data/intro.md#intro")
    assert result is True


def test_try_acquire_returns_false_when_lock_held() -> None:
    """try_acquire returns False when another session holds the lock."""
    from riverbank.advisory_locks import try_acquire

    conn = mock.MagicMock()
    mock_row = (False,)
    conn.execute.return_value.fetchone.return_value = mock_row

    result = try_acquire(conn, "file:///data/intro.md#intro")
    assert result is False


def test_try_acquire_returns_true_on_db_error() -> None:
    """try_acquire returns True (fallback: no locking) when the function is unavailable."""
    from riverbank.advisory_locks import try_acquire

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("function pg_try_advisory_lock does not exist")

    result = try_acquire(conn, "file:///data/intro.md#intro")
    assert result is True


def test_release_does_not_raise_on_success() -> None:
    """release() silently succeeds."""
    from riverbank.advisory_locks import release

    conn = mock.MagicMock()
    release(conn, "file:///data/intro.md#intro")
    conn.execute.assert_called_once()


def test_release_does_not_raise_on_error() -> None:
    """release() silently swallows errors (lock may not be held)."""
    from riverbank.advisory_locks import release

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("pg_advisory_unlock error")

    # Must not raise
    release(conn, "file:///data/intro.md#intro")


def test_advisory_lock_context_manager_acquires_and_releases() -> None:
    """advisory_lock context manager acquires the lock and releases it on exit."""
    from riverbank.advisory_locks import advisory_lock

    conn = mock.MagicMock()
    # Acquire returns True
    conn.execute.return_value.fetchone.return_value = (True,)

    with advisory_lock(conn, "frag:001") as acquired:
        assert acquired is True
        acquire_count = conn.execute.call_count  # should be 1 (acquire)

    # Release must have been called after the context exits
    assert conn.execute.call_count == acquire_count + 1


def test_advisory_lock_context_manager_yields_false_when_busy() -> None:
    """advisory_lock yields False when another worker holds the lock."""
    from riverbank.advisory_locks import advisory_lock

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = (False,)

    with advisory_lock(conn, "frag:001") as acquired:
        assert acquired is False

    # Release should NOT be called when lock was never acquired
    assert conn.execute.call_count == 1  # only the try_acquire call


def test_advisory_lock_releases_even_on_exception() -> None:
    """advisory_lock releases the lock even when the body raises an exception."""
    from riverbank.advisory_locks import advisory_lock

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = (True,)

    with mock.patch("riverbank.advisory_locks.release") as mock_release:
        try:
            with advisory_lock(conn, "frag:002") as acquired:
                assert acquired is True
                raise RuntimeError("processing failed")
        except RuntimeError:
            pass

    mock_release.assert_called_once_with(conn, "frag:002")


def test_run_already_completed_returns_false_when_no_row() -> None:
    """run_already_completed returns False when no matching run exists."""
    from riverbank.advisory_locks import run_already_completed

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = None

    result = run_already_completed(conn, "intro_h1", profile_id=1, content_hash=b"\x00")
    assert result is False


def test_run_already_completed_returns_true_when_row_exists() -> None:
    """run_already_completed returns True when a successful run already exists."""
    from riverbank.advisory_locks import run_already_completed

    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)

    result = run_already_completed(conn, "intro_h1", profile_id=1, content_hash=b"\xab\xcd")
    assert result is True


def test_run_already_completed_returns_false_on_db_error() -> None:
    """run_already_completed returns False gracefully on DB errors."""
    from riverbank.advisory_locks import run_already_completed

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("table does not exist")

    result = run_already_completed(conn, "intro_h1", profile_id=1, content_hash=b"\x00")
    assert result is False
