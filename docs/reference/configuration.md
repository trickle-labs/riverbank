# Configuration reference

Settings are resolved in this priority order (earlier sources win):

1. Explicit initialization arguments
2. Environment variables with `RIVERBANK_` prefix (nested with `__`)
3. TOML config file (`~/.riverbank/config.toml` or `RIVERBANK_CONFIG_FILE`)

## Environment variables

### Database

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RIVERBANK_DB__DSN` | string | `postgresql+psycopg://riverbank:riverbank@localhost:5432/riverbank` | PostgreSQL connection string |

### LLM provider

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RIVERBANK_LLM__PROVIDER` | string | `ollama` | Provider: `ollama`, `openai`, `anthropic`, `vllm`, `azure-openai` |
| `RIVERBANK_LLM__API_BASE` | string | `http://localhost:11434/v1` | Provider API base URL |
| `RIVERBANK_LLM__API_KEY` | string | `ollama` | API key |
| `RIVERBANK_LLM__MODEL` | string | `llama3.2` | Model identifier |
| `RIVERBANK_LLM__EMBED_MODEL` | string | `nomic-embed-text` | Embedding model |
| `RIVERBANK_LLM__MAX_TOKENS` | int | `4096` | Maximum tokens per LLM call |

### Langfuse (LLM observability)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RIVERBANK_LANGFUSE__ENABLED` | bool | `false` | Enable Langfuse tracing |
| `RIVERBANK_LANGFUSE__PUBLIC_KEY` | string | `""` | Langfuse public key |
| `RIVERBANK_LANGFUSE__SECRET_KEY` | string | `""` | Langfuse secret key |
| `RIVERBANK_LANGFUSE__HOST` | string | `http://localhost:3000` | Langfuse server URL |

### Tenant

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RIVERBANK_TENANT_ID` | string | `""` | Current tenant context (sets `app.current_tenant`) |

### OpenTelemetry

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | string | `""` | OTLP endpoint for spans (Jaeger, Tempo, Honeycomb) |
| `OTEL_SERVICE_NAME` | string | `riverbank` | Service name in traces |

### Config file path

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RIVERBANK_CONFIG_FILE` | string | `~/.riverbank/config.toml` | Path to TOML config file |

## TOML config file

```toml
[db]
dsn = "postgresql+psycopg://riverbank:riverbank@localhost:5432/riverbank"

[llm]
provider = "ollama"
api_base = "http://localhost:11434/v1"
api_key = "ollama"
model = "llama3.2"
embed_model = "nomic-embed-text"
max_tokens = 4096

[langfuse]
enabled = false
public_key = ""
secret_key = ""
host = "http://localhost:3000"
```

## Settings resolution

The `Settings` class uses Pydantic Settings with these sources (highest priority first):

1. **Init kwargs** — programmatic overrides
2. **Environment variables** — `RIVERBANK_` prefix, `__` as nesting separator
3. **TOML file** — `~/.riverbank/config.toml` (or `RIVERBANK_CONFIG_FILE`)

!!! warning
    The `RIVERBANK_DB__DSN` variable contains credentials. Never log it or include it in error messages. Use Kubernetes secrets or Vault in production.

## Type coercion

Pydantic handles type coercion automatically:

- `"true"` / `"false"` → `bool`
- `"4096"` → `int`
- Nested objects use `__` separator: `RIVERBANK_LLM__MODEL=gpt-4o`
