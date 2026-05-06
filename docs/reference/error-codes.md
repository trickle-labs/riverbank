# Error codes

CLI exit codes and error categories used by riverbank.

## Exit codes

| Code | Meaning | Commands |
|------|---------|----------|
| 0 | Success | All commands |
| 1 | Failure | All commands — operation failed, quality gate failed, or resource not found |

## Error categories

### Database errors

- **Connection failed** — cannot reach PostgreSQL at the configured DSN
- **Migration failed** — Alembic migration encountered an error
- **Extension missing** — pg-ripple or pg-trickle extension not installed

### LLM errors

- **Provider unreachable** — LLM API endpoint not responding
- **Circuit breaker open** — too many failures, provider blocked
- **Token limit exceeded** — fragment too large for model context window
- **Rate limited** — provider returned 429

### Validation errors

- **Evidence span mismatch** — excerpt does not match text at declared offset (fabricated citation rejected)
- **SHACL violation** — triple violates a registered SHACL shape
- **Quality gate failed** — SHACL score below threshold

### Resource errors

- **Profile not found** — referenced profile name/version does not exist in catalog
- **Source not found** — IRI not registered in `_riverbank.sources`
- **Tenant not found** — tenant slug does not exist

### Configuration errors

- **Invalid duration** — `--since` value does not match expected format (e.g., `1h`, `30m`, `7d`)
- **Invalid format** — `--format` value not recognized
- **Missing required option** — a required flag was not provided

## Structured error output

When `--format json` is available, errors are returned as:

```json
{
  "error": true,
  "category": "validation",
  "message": "SHACL quality gate FAILED — score 0.5234 < threshold 0.70",
  "exit_code": 1
}
```
