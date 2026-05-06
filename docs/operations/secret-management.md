# Secret management

Credentials for database access, LLM providers, and Langfuse must be managed securely.

## Secrets required

| Secret | Variable | Used for |
|--------|----------|----------|
| Database DSN | `RIVERBANK_DB__DSN` | PostgreSQL connection (includes password) |
| LLM API key | `RIVERBANK_LLM__API_KEY` | OpenAI, Anthropic, or other provider |
| Langfuse secret key | `RIVERBANK_LANGFUSE__SECRET_KEY` | Langfuse authentication |
| Label Studio API key | `--ls-key` (CLI flag) | Review queue operations |

## Kubernetes secrets

```bash
kubectl create secret generic riverbank-secrets \
  --namespace riverbank \
  --from-literal=RIVERBANK_DB__DSN="postgresql://user:pass@host:5432/db" \
  --from-literal=RIVERBANK_LLM__API_KEY="sk-..." \
  --from-literal=RIVERBANK_LANGFUSE__SECRET_KEY="sk-lf-..."
```

Reference in the Helm chart:

```yaml
existingSecret: "riverbank-secrets"
```

## HashiCorp Vault

With the `[hardening]` extras installed, riverbank can read secrets from Vault:

1. Configure the Vault Agent sidecar in your pod spec
2. Mount secrets as environment variables or files
3. The `hvac` client handles lease renewal automatically

## Rotation

See [Rotate secrets](../how-to/rotate-secrets.md) for the full rotation procedure.

Key points:

- Update the Kubernetes secret
- Restart worker pods (`kubectl rollout restart`)
- Advisory locks are released automatically on pod termination
- Verify with `riverbank health`

!!! warning
    Never store secrets in:

    - `values.yaml` committed to Git
    - Environment variables in CI logs
    - The TOML config file (unless file permissions are restricted)

## Docker Compose (development only)

For local development, secrets go in `.env` (gitignored):

```bash
RIVERBANK_DB__DSN=postgresql+psycopg://riverbank:riverbank@localhost:5432/riverbank
RIVERBANK_LLM__API_KEY=ollama
```
