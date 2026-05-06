# Backup and restore

riverbank's state lives entirely in PostgreSQL. Standard PostgreSQL backup strategies apply.

## What to back up

- The `_riverbank` schema (catalog: sources, fragments, profiles, runs, audit log)
- The pg-ripple graph store (compiled triples, SHACL shapes, provenance)
- pg-trickle materialized views (can be regenerated, but backup avoids downtime)

## pg_dump (logical backup)

```bash
pg_dump -h localhost -U riverbank -d riverbank \
  --schema=_riverbank \
  --schema=pg_ripple \
  -F custom -f riverbank_backup.dump
```

Restore:

```bash
pg_restore -h localhost -U riverbank -d riverbank \
  --clean --if-exists \
  riverbank_backup.dump
```

## Point-in-time recovery (PITR)

For production, use continuous WAL archiving:

1. Configure `archive_mode = on` and `archive_command` in `postgresql.conf`
2. Take periodic base backups with `pg_basebackup`
3. Restore to any point in time with `recovery_target_time`

## Kubernetes (volume snapshots)

If using a CSI driver that supports volume snapshots:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: riverbank-db-snapshot
spec:
  volumeSnapshotClassName: csi-snapclass
  source:
    persistentVolumeClaimName: data-postgres-0
```

## What can be regenerated

If you lose the backup, these can be reconstructed:

- **Compiled triples** — re-ingest the corpus (`riverbank ingest`)
- **pg-trickle views** — refresh automatically after graph writes
- **Rendered pages** — re-render (`riverbank render`)

What **cannot** be regenerated:

- **Audit log** — append-only history is lost
- **Run history** — cost/token accounting is lost
- **Review decisions** — human judgments from Label Studio are lost
