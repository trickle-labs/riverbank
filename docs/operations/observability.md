# Observability

riverbank has three observability layers: LLM traces (Langfuse), pipeline spans (OpenTelemetry), and aggregate metrics (Prometheus).

## Layer 1: Langfuse (LLM observability)

Every LLM extraction call is traced in Langfuse with:

- Input prompt (fragment text + system prompt)
- Output (extracted triples)
- Token counts (prompt + completion)
- Latency
- Cost estimate

Access traces via `riverbank runs`:

```bash
riverbank runs --since 1h
```

The "Langfuse" column contains deep-links to individual trace views.

### Configuration

```bash
export RIVERBANK_LANGFUSE__ENABLED=true
export RIVERBANK_LANGFUSE__PUBLIC_KEY="pk-lf-..."
export RIVERBANK_LANGFUSE__SECRET_KEY="sk-lf-..."
export RIVERBANK_LANGFUSE__HOST="http://langfuse:3000"
```

## Layer 2: OpenTelemetry (pipeline spans)

The pipeline emits spans for each stage:

- `riverbank.ingest` — top-level span for an ingest run
- `riverbank.parse` — document parsing
- `riverbank.fragment` — fragmentation
- `riverbank.extract` — LLM extraction
- `riverbank.validate` — SHACL validation
- `riverbank.write` — graph write

### Configuration

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://tempo:4317"
export OTEL_SERVICE_NAME="riverbank"
```

Supports gRPC and HTTP exporters. Compatible with Jaeger, Tempo, Honeycomb, and any OTLP-compatible backend.

### Viewing traces

In Jaeger/Tempo, search for service `riverbank` to see the full span tree for a single fragment compilation.

## Layer 3: Prometheus metrics

Six metrics are emitted at `/metrics`:

| Metric | Type | What to monitor |
|--------|------|-----------------|
| `riverbank_runs_total` | Counter | Error rate, throughput |
| `riverbank_run_duration_seconds` | Histogram | Latency percentiles |
| `riverbank_llm_cost_usd_total` | Counter | Daily spend |
| `riverbank_shacl_score` | Gauge | Quality regression |
| `riverbank_review_queue_depth` | Gauge | Reviewer backlog |
| `riverbank_context_efficiency_ratio` | Gauge | RAG relevance |

See [Metrics reference](../reference/metrics.md) for full details.

### Alert rules (example)

```yaml
groups:
  - name: riverbank
    rules:
      - alert: SHACLScoreDrop
        expr: riverbank_shacl_score < 0.7
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "SHACL score dropped below threshold"

      - alert: ReviewQueueBacklog
        expr: riverbank_review_queue_depth > 100
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Review queue has >100 pending items"

      - alert: HighErrorRate
        expr: rate(riverbank_runs_total{outcome="error"}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High extraction error rate"
```

## Perses dashboards

The `perses/riverbank-overview.json` file contains a pre-built dashboard showing:

- Runs per hour (success vs. error)
- LLM cost accumulation
- SHACL scores over time
- Review queue depth
- Run duration percentiles

Import into Perses or convert to Grafana format.

## Nightly flows

Two Prefect flows run on schedule:

1. **`snapshot_shacl_scores()`** — records SHACL scores for all named graphs into `_riverbank.shacl_score_history`
2. **`run_nightly_lint()`** — runs the full lint pass and records findings as `pgc:LintFinding` triples
