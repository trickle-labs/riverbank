# Audit trail

Every significant operation is logged in `_riverbank.audit_log`.

## What's logged

| Operation | Trigger | Data recorded |
|-----------|---------|---------------|
| `source_registered` | `riverbank ingest` | Source IRI, content hash |
| `fragment_created` | `riverbank ingest` | Fragment key, source reference |
| `extraction_completed` | `riverbank ingest` | Run ID, outcome, cost |
| `triple_written` | `riverbank ingest` | Subject IRI, named graph |
| `profile_registered` | `riverbank profile register` | Profile name, version |
| `tenant_created` | `riverbank tenant create` | Tenant ID, display name |
| `tenant_suspended` | `riverbank tenant suspend` | Tenant ID |
| `tenant_deleted` | `riverbank tenant delete` | Tenant ID, GDPR flag |
| `review_decision` | `riverbank review collect` | Task ID, decision type |
| `rls_activated` | `riverbank tenant activate-rls` | Tables affected |

## Schema

```sql
CREATE TABLE _riverbank.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT NOT NULL DEFAULT current_user,
    operation   TEXT NOT NULL,
    entity_iri  TEXT,
    tenant_id   TEXT,
    details     JSONB,
    session_id  TEXT
);
```

## Querying the audit trail

```sql
SELECT timestamp, actor, operation, entity_iri, details
FROM _riverbank.audit_log
WHERE tenant_id = 'acme'
ORDER BY timestamp DESC
LIMIT 50;
```

## RLS protection

The audit log is RLS-protected: each tenant sees only their own audit entries. System-level operations (e.g., `rls_activated`) have a null `tenant_id` and are visible only to superusers.

## Retention

The audit log is append-only. For retention management, use PostgreSQL partitioning by timestamp or a periodic archival job:

```sql
-- Archive entries older than 90 days
INSERT INTO _riverbank.audit_log_archive
SELECT * FROM _riverbank.audit_log
WHERE timestamp < now() - INTERVAL '90 days';

DELETE FROM _riverbank.audit_log
WHERE timestamp < now() - INTERVAL '90 days';
```
