# Scaling

How to scale riverbank horizontally and what bottlenecks to watch for.

## Horizontal scaling

Increase `replicaCount` in the Helm chart:

```yaml
replicaCount: 5
```

Throughput scales linearly with replicas until you hit:

1. **LLM provider rate limits** — the circuit breaker will open if you exceed the provider's concurrency limit
2. **PostgreSQL connection limits** — each replica holds a connection pool
3. **Advisory lock contention** — negligible in practice (locks are fragment-level)

## Vertical scaling

For memory-intensive corpora (large PDFs via Docling):

```yaml
resources:
  limits:
    cpu: 4000m
    memory: 8Gi
  requests:
    cpu: 1000m
    memory: 2Gi
```

## Bottleneck identification

| Symptom | Likely bottleneck | Fix |
|---------|-------------------|-----|
| High `run_duration_seconds` | LLM latency | Switch provider or model |
| Runs completing but `triples_written` = 0 | Editorial policy too strict | Lower `min_fragment_length` |
| Circuit breaker opening frequently | Provider rate limit | Reduce `maxConcurrency` or add replicas (distributes load) |
| PostgreSQL CPU saturated | SHACL validation overhead | Reduce SHACL shape complexity |
| Memory OOM on workers | Large fragments in memory | Reduce `max_fragment_tokens` |

## Connection pooling

For >5 replicas, consider PgBouncer between workers and PostgreSQL:

```yaml
dbDsn: "postgresql://riverbank:pass@pgbouncer:6432/riverbank"
```

## Corpus-size guidelines

| Corpus size | Recommended replicas | Notes |
|-------------|---------------------|-------|
| < 100 documents | 1 | Single replica sufficient |
| 100–1000 documents | 3 | Default Helm configuration |
| 1000–10000 documents | 5–10 | Consider provider-level rate limits |
| > 10000 documents | 10+ | Use PgBouncer, monitor lock contention |
