# Rotate secrets

Update LLM API keys, database credentials, or Langfuse tokens without downtime.

## Kubernetes (recommended)

### 1. Update the secret

```bash
kubectl create secret generic riverbank-secrets \
  --namespace riverbank \
  --from-literal=RIVERBANK_DB__DSN="postgresql://new-password@..." \
  --from-literal=RIVERBANK_LLM__API_KEY="sk-new-key" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2. Restart the workers

```bash
kubectl rollout restart deployment/riverbank -n riverbank
```

Workers pick up new environment variables on restart. Advisory locks are released automatically when the old pods terminate.

## HashiCorp Vault integration

If using the `[hardening]` extras with Vault:

1. Update the secret in Vault
2. The `hvac` client refreshes the lease on the next health check cycle
3. No pod restart required — the Vault agent sidecar injects updated secrets

## Docker Compose

```bash
# Update .env file with new credentials
docker compose up -d --force-recreate riverbank
```

## Verify

After rotation:

```bash
riverbank health
```

All checks should pass with the new credentials.

!!! warning
    If you rotate the database DSN, ensure the new credentials have the same permissions (including RLS policy ownership if multi-tenant is active).
