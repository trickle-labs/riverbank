# Metrics reference

All Prometheus metrics emitted by the riverbank `/metrics` endpoint.

## Metrics

### `riverbank_runs_total`

**Type:** Counter

Total number of compiler runs completed.

| Label | Values | Description |
|-------|--------|-------------|
| `profile` | profile name | Which compiler profile was used |
| `outcome` | `success`, `error`, `skipped` | Run result |

**Alert on:** Sudden spike in `outcome="error"`.

---

### `riverbank_run_duration_seconds`

**Type:** Histogram

Duration of each compiler run in seconds.

| Label | Values | Description |
|-------|--------|-------------|
| `profile` | profile name | Which compiler profile was used |

**Buckets:** 0.1, 0.5, 1, 5, 10, 30, 60, 120, 300

**Alert on:** p99 exceeding 60s for interactive workloads.

---

### `riverbank_llm_cost_usd_total`

**Type:** Counter

Cumulative LLM cost in USD.

| Label | Values | Description |
|-------|--------|-------------|
| `profile` | profile name | Which compiler profile was used |
| `provider` | `ollama`, `openai`, `anthropic`, etc. | LLM provider |

**Alert on:** Daily spend exceeding budget threshold.

---

### `riverbank_shacl_score`

**Type:** Gauge

Current SHACL quality score for a named graph.

| Label | Values | Description |
|-------|--------|-------------|
| `named_graph` | graph IRI | Which named graph the score applies to |

**Alert on:** Score dropping below 0.7 (or your profile threshold).

---

### `riverbank_review_queue_depth`

**Type:** Gauge

Number of extractions pending human review.

| Label | Values | Description |
|-------|--------|-------------|
| `named_graph` | graph IRI | Which named graph the queue draws from |

**Alert on:** Depth exceeding 100 (reviewers falling behind).

---

### `riverbank_context_efficiency_ratio`

**Type:** Gauge

Ratio of useful context (facts that contributed to answers) vs. total context retrieved.

| Label | Values | Description |
|-------|--------|-------------|
| `profile` | profile name | Which compiler profile was used |

**Alert on:** Ratio dropping below 0.5 (most retrieved context is irrelevant).

## Endpoint

Metrics are served at:

```
GET http://localhost:8000/metrics
```

The endpoint returns Prometheus text exposition format.

## Scrape configuration

### Kubernetes (ServiceMonitor)

```yaml
metrics:
  enabled: true
  port: 8000
  path: /metrics
  serviceMonitor:
    enabled: true
    interval: 30s
```

### Prometheus scrape config

```yaml
scrape_configs:
  - job_name: riverbank
    static_configs:
      - targets: ["riverbank:8000"]
    metrics_path: /metrics
    scrape_interval: 30s
```

## Graceful degradation

When `prometheus-client` is not installed (i.e., `[hardening]` extras are not present), all metric functions are replaced with no-op stubs. No errors, no metrics emitted.
