# Installation

riverbank supports multiple installation paths depending on your use case.

## Python package (development)

=== "uv (recommended)"

    ```bash
    uv venv && source .venv/bin/activate
    uv pip install -e ".[dev]"
    ```

=== "pip"

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    ```

## Extras groups

riverbank uses optional dependency groups to keep the core package lightweight:

| Extra | Purpose | When to install |
|-------|---------|----------------|
| `dev` | pytest, ruff, mypy, testcontainers | Local development and testing |
| `docs` | mkdocs-material, mkdocstrings, mike | Building the documentation site |
| `ingest` | Docling, Instructor, spaCy, sentence-transformers | Real LLM extraction (production) |
| `review` | Label Studio SDK | Human review loop |
| `orchestration` | APScheduler, Prefect | Workflow orchestration |
| `hardening` | prometheus-client, aiobreaker, hvac | Production metrics, circuit breakers, Vault |

Install multiple extras at once:

```bash
pip install -e ".[dev,ingest,hardening]"
```

## Docker

The project ships a production `Dockerfile`:

```bash
docker build -t riverbank .
```

Or use the pre-built image:

```bash
docker pull ghcr.io/trickle-labs/riverbank:latest
```

## Docker Compose (full stack)

The `docker-compose.yml` at the repo root brings up the complete stack for local development:

```bash
docker compose up -d
```

Services included:

| Service | Purpose |
|---------|---------|
| `postgres` | PostgreSQL with pg-ripple, pg-trickle, pgvector |
| `pg_tide` | CDC relay sidecar |
| `ollama` | Local LLM runtime |
| `langfuse` | LLM observability dashboard |
| `riverbank` | Worker container |

## Kubernetes (Helm)

For production deployments, use the Helm chart:

```bash
helm install riverbank ./helm/riverbank \
  --set dbDsn="postgresql://..." \
  --set llmProvider=openai \
  --set llmApiKey="sk-..."
```

See the [Helm chart reference](../operations/helm-chart.md) for the full `values.yaml` documentation.

## Verify your installation

After any installation path:

```bash
riverbank version
riverbank config
```

If you have a running PostgreSQL instance with the required extensions:

```bash
riverbank health
```
