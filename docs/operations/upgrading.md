# Upgrading

How to upgrade riverbank between versions: migrations, rollback, and known lock requirements.

## Check current version

```bash
riverbank version
```

## Check migration status

```bash
alembic current
```

## Upgrade procedure

1. **Read the changelog** — check for breaking changes in [changelog](../reference/changelog.md)
2. **Back up the database** — see [backup and restore](backup-and-restore.md)
3. **Update the image tag** (Kubernetes):
   ```bash
   helm upgrade riverbank ./helm/riverbank --set image.tag="0.10.0"
   ```
4. **Run migrations:**
   ```bash
   riverbank init
   ```
5. **Verify:**
   ```bash
   riverbank health
   ```

## Rollback

### Helm rollback

```bash
helm rollback riverbank <revision>
```

### Alembic rollback

```bash
alembic downgrade -1
```

!!! warning
    Not all migrations are reversible. Check the migration file before downgrading. Migrations that drop columns or tables cannot be rolled back automatically.

## Migration reference

| Version | Migration | Description | Lock required | Duration estimate |
|---------|-----------|-------------|---------------|-------------------|
| v0.1.0 | `0001_initial` | Create `_riverbank` schema and base tables | `ACCESS EXCLUSIVE` on new tables | < 1s |
| v0.4.0 | `0002_artifact_deps` | Add `artifact_deps` table and `tenant_id` columns | `ACCESS EXCLUSIVE` on new table; `ALTER TABLE` locks on existing | 1–5s depending on row count |
| v0.6.0 | `0003_audit_log` | Add `audit_log` table and SHACL history | New table only | < 1s |
| v0.7.0 | `0004_metrics` | Add indexes for metrics queries | `CREATE INDEX CONCURRENTLY` | No lock (concurrent) |
| v0.9.0 | `0005_tenants` | Add `tenants` table and RLS policies | New table + policy creation | < 1s |

## Zero-downtime upgrades

For most versions, upgrades are zero-downtime:

1. Deploy the new image (new pods start with new code)
2. Old pods drain gracefully (advisory locks released)
3. Run `riverbank init` from any pod (Alembic handles concurrent migration safely)

The only exception is migrations that require `ALTER TABLE` with `ACCESS EXCLUSIVE` lock on large tables. Check the migration reference above.

## Version compatibility

- Workers at version N can run against a database migrated to version N or N+1
- Workers at version N+1 **require** the database to be at version N+1
- Always migrate the database before deploying new workers
