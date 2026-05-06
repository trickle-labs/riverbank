# Multi-replica workers

riverbank supports multiple worker replicas processing fragments concurrently without duplicate work.

## How it works

When multiple replicas run `riverbank ingest` against the same corpus:

1. Each replica discovers fragments to process
2. Before extracting a fragment, the replica acquires a PostgreSQL advisory lock keyed on the fragment's content hash
3. If the lock is already held → another replica is processing it → skip
4. After extraction completes → lock is released

This provides exactly-once processing semantics without external coordination.

## Configuration

Set `replicaCount` in the Helm chart:

```yaml
replicaCount: 3
```

No additional configuration required — advisory locking is automatic.

## Throughput scaling

- Each replica processes fragments independently
- Fragments are distributed by lock contention (first to acquire wins)
- Throughput scales linearly with replica count up to the LLM provider's rate limit
- The circuit breaker prevents overwhelming the provider

## Failure handling

If a replica crashes while holding an advisory lock:

- PostgreSQL automatically releases the lock when the session disconnects
- The fragment will be picked up by another replica on the next ingest run
- No data corruption — the graph write is transactional

## Monitoring

Watch the `riverbank_runs_total` metric with the `outcome` label to track processing distribution across replicas.
