# Operations

This section is for platform engineers and SREs deploying riverbank at scale. It assumes fluency with Kubernetes, Prometheus, and PostgreSQL.

| Page | What it covers |
|------|---------------|
| [Helm chart](helm-chart.md) | Full `values.yaml` reference, upgrade, rollback |
| [Multi-replica workers](multi-replica-workers.md) | Advisory locking, no duplicate work |
| [Advisory locks](advisory-locks.md) | Lock keys, crash recovery, diagnostics |
| [Circuit breakers](circuit-breakers.md) | Per-provider config, states, recovery |
| [Audit trail](audit-trail.md) | What's logged, retention, querying |
| [Backup and restore](backup-and-restore.md) | pg_dump, point-in-time recovery |
| [Secret management](secret-management.md) | Kubernetes secrets, Vault, rotation |
| [Observability](observability.md) | Langfuse, OpenTelemetry, Prometheus, Perses |
| [Scaling](scaling.md) | Horizontal scaling, resource limits, bottlenecks |
| [Upgrading](upgrading.md) | Alembic migrations, rollback, lock durations |
