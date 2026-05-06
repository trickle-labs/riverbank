# Deploy on Kubernetes

Production deployment using the riverbank Helm chart.

## Prerequisites

- Kubernetes 1.27+
- Helm 3.x
- PostgreSQL with pg-ripple, pg-trickle, and pgvector extensions
- A container registry with the riverbank image

## Install the chart

```bash
helm install riverbank ./helm/riverbank \
  --namespace riverbank \
  --create-namespace \
  --set dbDsn="postgresql://riverbank:secret@postgres:5432/riverbank" \
  --set llmProvider=openai \
  --set existingSecret=riverbank-secrets
```

## Production `values.yaml`

```yaml
replicaCount: 3

image:
  repository: ghcr.io/trickle-labs/riverbank
  tag: "0.9.0"

resources:
  limits:
    cpu: 2000m
    memory: 4Gi
  requests:
    cpu: 500m
    memory: 1Gi

# Database
dbDsn: ""  # Set via existingSecret
existingSecret: "riverbank-secrets"

# LLM provider
llmProvider: openai
llmApiBase: "https://api.openai.com/v1"

# Observability
langfuseEnabled: true
langfuseHost: "https://langfuse.internal.example.com"
otelExporterOtlpEndpoint: "http://tempo:4317"

# Metrics
metrics:
  enabled: true
  port: 8000
  path: /metrics
  serviceMonitor:
    enabled: true
    interval: 30s

# Circuit breakers
circuitBreakers:
  openai:
    failMax: 5
    resetTimeoutSeconds: 60
    maxConcurrency: 10
  anthropic:
    failMax: 5
    resetTimeoutSeconds: 60
    maxConcurrency: 5

# Pod annotations for Prometheus scraping
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/metrics"
```

## Create the secret

```bash
kubectl create secret generic riverbank-secrets \
  --namespace riverbank \
  --from-literal=RIVERBANK_DB__DSN="postgresql://..." \
  --from-literal=RIVERBANK_LLM__API_KEY="sk-..."
```

## Upgrade

```bash
helm upgrade riverbank ./helm/riverbank \
  --namespace riverbank \
  --reuse-values \
  --set image.tag="0.10.0"
```

## Rollback

```bash
helm rollback riverbank 1 --namespace riverbank
```

## Health checks

The chart configures liveness and readiness probes via `riverbank health`. The health endpoint checks:

- pg-trickle preflight (7 system checks)
- pg-tide availability
- Circuit breaker states

See the [Helm chart reference](../operations/helm-chart.md) for full `values.yaml` documentation.
