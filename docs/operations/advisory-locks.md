# Advisory locks

riverbank uses PostgreSQL advisory locks to coordinate multi-replica fragment processing.

## Lock key

The lock key is derived from the fragment's `xxh3_128` content hash, truncated to a 64-bit integer for `pg_try_advisory_lock()`.

```sql
SELECT pg_try_advisory_lock(hash_bigint);
```

## What the lock protects

- **Duplicate extraction:** prevents two replicas from extracting the same fragment simultaneously
- **Write conflicts:** ensures only one replica writes triples for a given fragment

## Lock lifecycle

1. **Acquire** — `pg_try_advisory_lock(key)` returns `true` if acquired, `false` if held by another session
2. **Process** — extract triples, validate, write to graph
3. **Release** — `pg_advisory_unlock(key)` or automatic release on session disconnect

## Crash recovery

If a worker crashes mid-extraction:

- The PostgreSQL session terminates
- All advisory locks held by that session are released automatically
- No manual intervention required
- The fragment is available for processing on the next run

## Diagnosing stuck locks

In normal operation, locks are held for seconds (one extraction). If you suspect stuck locks:

```sql
SELECT pid, granted, objid
FROM pg_locks
WHERE locktype = 'advisory' AND granted = true;
```

To identify the holding session:

```sql
SELECT pid, usename, application_name, state, query_start
FROM pg_stat_activity
WHERE pid IN (
  SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted = true
);
```

## Clearing stuck locks

If a session is truly stuck (should not happen in normal operation):

```sql
SELECT pg_terminate_backend(<pid>);
```

!!! danger
    Only terminate sessions you have confirmed are stuck. Terminating an active extraction will lose that fragment's work (but not corrupt data — the transaction is rolled back).

## Lock granularity

Locks are **fragment-level**, not source-level. This means:

- Two replicas can process different fragments from the same document simultaneously
- Maximum parallelism = number of fragments in the corpus
- Fine-grained locking minimizes contention
