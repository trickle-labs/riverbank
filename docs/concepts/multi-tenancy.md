# Multi-tenancy

riverbank supports multiple tenants on shared infrastructure with strong isolation guarantees via PostgreSQL Row-Level Security.

## Isolation model

Each tenant gets:

- **A named graph prefix** — `http://riverbank.example/graph/{tenant_id}/`
- **RLS-filtered catalog rows** — sources, fragments, runs, audit logs
- **Independent quality scores** — per-tenant SHACL scores and coverage maps

## How RLS works

When RLS is activated (`riverbank tenant activate-rls`), all `_riverbank` tables gain policies that filter by `tenant_id`. The session variable `app.current_tenant` is set by the application before each query:

```sql
SET app.current_tenant = 'acme';
SELECT * FROM _riverbank.sources;
-- Only returns sources belonging to tenant 'acme'
```

## What RLS protects

- **Data access** — a tenant cannot see another tenant's sources, fragments, runs, or triples
- **Graph queries** — SPARQL queries are scoped to the tenant's named graphs
- **Audit trail** — each tenant sees only their own audit entries

## What RLS does not protect

!!! warning
    RLS does not protect against:

    - Side-channel attacks via query timing
    - Shared LLM provider rate limits (one tenant's heavy usage can slow another)
    - Shared PostgreSQL resource contention (CPU, memory, I/O)

    For full resource isolation, use separate PostgreSQL instances.

## Tenant lifecycle

| State | Meaning |
|-------|---------|
| `active` | Normal operation |
| `suspended` | All operations blocked by RLS |
| `deleted` | Soft-deleted (data preserved) or GDPR-erased (data destroyed) |

## Named graph structure

Multi-tenant graphs follow this pattern:

```
http://riverbank.example/graph/{tenant_id}/trusted
http://riverbank.example/graph/{tenant_id}/draft
http://riverbank.example/graph/{tenant_id}/vocab
http://riverbank.example/graph/{tenant_id}/human-review
```

## GDPR erasure

The `--gdpr` flag on `riverbank tenant delete` triggers cascading deletion through the provenance graph:

1. All sources belonging to the tenant
2. All fragments derived from those sources
3. All compiled triples derived from those fragments
4. All runs, audit log entries, and rendered pages
5. The tenant record itself

This is irreversible by design.
