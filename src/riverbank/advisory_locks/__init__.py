from __future__ import annotations

"""Fragment-level advisory locks for multi-replica worker coordination (v0.7.0).

Uses PostgreSQL session-level advisory locks
(``pg_try_advisory_lock(hashtext(fragment_iri)::bigint)``) to prevent two
worker replicas from processing the same fragment concurrently.

Design:
* Locks are *session-level* (released automatically when the DB connection
  is closed) rather than transaction-level, so a worker crash does not leave
  a lock held indefinitely — the lock is released when the session drops.
* A fragment IRI is hashed via ``hashtext()`` to a bigint, giving a 64-bit
  lock key space with low collision probability for typical corpora.
* Run idempotency is enforced by a ``(fragment_id, profile_id, content_hash)``
  uniqueness constraint checked before acquiring the advisory lock; if a
  completed run already exists for the same content, no lock is acquired.

Usage::

    from riverbank.advisory_locks import try_acquire_fragment_lock, release_fragment_lock

    with advisory_lock(conn, fragment_iri) as acquired:
        if not acquired:
            logger.info("Skipping %s — another worker is processing it", fragment_iri)
            continue
        # process fragment here …

The context manager is the preferred interface.  The low-level
``try_acquire`` / ``release`` functions are provided for cases where the
caller manages the lock lifecycle manually (e.g. async code).
"""

import contextlib
import logging
from typing import Any, Generator

logger = logging.getLogger(__name__)

# SQL helpers — these call PostgreSQL built-ins, no pg_ripple required
_TRY_LOCK_SQL = (
    "SELECT pg_try_advisory_lock(hashtext(:frag_iri)::bigint)"
)
_RELEASE_SQL = (
    "SELECT pg_advisory_unlock(hashtext(:frag_iri)::bigint)"
)
_CHECK_EXISTING_RUN_SQL = """
    SELECT 1
    FROM _riverbank.runs r
    JOIN _riverbank.fragments f ON f.id = r.fragment_id
    WHERE f.fragment_key = :fragment_key
      AND r.profile_id   = :profile_id
      AND f.content_hash = :content_hash
      AND r.outcome      = 'success'
    LIMIT 1
"""


def try_acquire(conn: Any, fragment_iri: str) -> bool:
    """Try to acquire a session-level advisory lock for *fragment_iri*.

    Returns ``True`` when the lock was acquired (this worker may proceed),
    ``False`` when another worker already holds the lock for this fragment.

    Falls back to ``True`` (no locking) when the connection does not support
    the ``pg_try_advisory_lock`` function (e.g. plain SQLite in tests).
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        row = conn.execute(
            text(_TRY_LOCK_SQL), {"frag_iri": fragment_iri}
        ).fetchone()
        acquired = bool(row[0]) if row is not None else True
        if acquired:
            logger.debug("advisory_lock acquired: frag_iri=%r", fragment_iri)
        else:
            logger.debug("advisory_lock busy (skip): frag_iri=%r", fragment_iri)
        return acquired
    except Exception as exc:  # noqa: BLE001
        # Function not available (non-PG backend, tests, etc.) — allow work
        logger.debug("advisory_lock not available (%s) — proceeding without lock", exc)
        return True


def release(conn: Any, fragment_iri: str) -> None:
    """Release the session-level advisory lock for *fragment_iri*.

    Safe to call even if the lock is not held (pg_advisory_unlock returns
    false in that case; we ignore it).
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        conn.execute(text(_RELEASE_SQL), {"frag_iri": fragment_iri})
    except Exception as exc:  # noqa: BLE001
        logger.debug("advisory_lock release error: %s", exc)


@contextlib.contextmanager
def advisory_lock(conn: Any, fragment_iri: str) -> Generator[bool, None, None]:
    """Context manager that acquires and releases an advisory lock.

    Yields ``True`` when the lock was acquired, ``False`` otherwise.

    The lock is released in the ``finally`` block regardless of exceptions,
    ensuring that a worker that crashed mid-extraction does not hold the lock
    until its session expires.

    Example::

        with advisory_lock(conn, frag_iri) as acquired:
            if not acquired:
                stats["fragments_skipped"] += 1
                continue
            # ... process fragment ...
    """
    acquired = try_acquire(conn, fragment_iri)
    try:
        yield acquired
    finally:
        if acquired:
            release(conn, fragment_iri)


def run_already_completed(
    conn: Any,
    fragment_key: str,
    profile_id: int,
    content_hash: bytes,
) -> bool:
    """Return True if a successful run exists for this (fragment, profile, hash) triple.

    This is the idempotency check that prevents duplicate work when multiple
    replicas race to process the same fragment.  If a successful run already
    exists with the same content hash the caller should skip processing
    regardless of whether the advisory lock was acquired.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        row = conn.execute(
            text(_CHECK_EXISTING_RUN_SQL),
            {
                "fragment_key": fragment_key,
                "profile_id": profile_id,
                "content_hash": content_hash,
            },
        ).fetchone()
        return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("run_already_completed check failed: %s", exc)
        return False
