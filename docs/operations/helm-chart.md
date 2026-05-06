# Helm chart

The riverbank Helm chart deploys the worker, configures secrets, and wires up Prometheus scraping.

## Location

```
helm/riverbank/
├── Chart.yaml
├── values.yaml
└── templates/
```

## Install

```bash
helm install riverbank ./helm/riverbank \
  --namespace riverbank \
  --create-namespace \
  --set existingSecret=riverbank-secrets
```

## `values.yaml` reference

### Worker

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `replicaCount` | int | `3` | Number of worker replicas |
| `image.repository` | string | `ghcr.io/trickle-labs/riverbank` | Container image |
| `image.tag` | string | chart `appVersion` | Image tag |

### Database

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dbDsn` | string | `""` | PostgreSQL DSN (prefer secret) |
| `existingSecret` | string | `""` | K8s secret name containing `RIVERBANK_DB__DSN` and `RIVERBANK_LLM__API_KEY` |

### LLM

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `llmProvider` | string | `ollama` | LLM provider |
| `llmApiBase` | string | `http://ollama:11434/v1` | Provider API base |

### Observability

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `langfuseEnabled` | bool | `false` | Enable Langfuse tracing |
| `langfuseHost` | string | `http://langfuse:3000` | Langfuse URL |
| `otelExporterOtlpEndpoint` | string | `""` | OTLP endpoint |

### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `metrics.enabled` | bool | `true` | Enable Prometheus endpoint |
| `metrics.port` | int | `8000` | Metrics port |
| `metrics.path` | string | `/metrics` | Metrics path |
| `metrics.serviceMonitor.enabled` | bool | `false` | Create ServiceMonitor CR |
| `metrics.serviceMonitor.interval` | string | `30s` | Scrape interval |

### Circuit breakers

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `circuitBreakers.<provider>.failMax` | int | `5` | Failures before opening |
| `circuitBreakers.<provider>.resetTimeoutSeconds` | int | `60` | Seconds before half-open |
| `circuitBreakers.<provider>.maxConcurrency` | int | `10` | Max parallel LLM calls |

### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `resources.limits.cpu` | string | `2000m` | CPU limit |
| `resources.limits.memory` | string | `4Gi` | Memory limit |
| `resources.requests.cpu` | string | `500m` | CPU request |
| `resources.requests.memory` | string | `1Gi` | Memory request |

### Pod annotations

| Key | Default | Description |
|-----|---------|-------------|
| `podAnnotations."prometheus.io/scrape"` | `"true"` | Enable Prometheus scraping |
| `podAnnotations."prometheus.io/port"` | `"8000"` | Scrape port |
| `podAnnotations."prometheus.io/path"` | `"/metrics"` | Scrape path |

## Upgrade

```bash
helm upgrade riverbank ./helm/riverbank --reuse-values --set image.tag="0.10.0"
```

## Rollback

```bash
helm rollback riverbank <revision>
```

## Dependencies

The chart can optionally deploy sub-charts:

| Sub-chart | Default | Purpose |
|-----------|---------|---------|
| PostgreSQL | disabled | Database (prefer managed service) |
| Prefect server | disabled | Workflow orchestration |
| Label Studio | disabled | Human review UI |
| Langfuse | disabled | LLM observability |
