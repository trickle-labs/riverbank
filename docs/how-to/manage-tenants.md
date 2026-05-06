# Manage tenants

Full lifecycle for multi-tenant deployments: create, configure, suspend, and delete tenants.

## Create a tenant

```bash
riverbank tenant create acme --name "Acme Corp" --ls-org 42
```

This creates a tenant with:

- A unique slug (`acme`)
- A display name
- An optional Label Studio organisation ID for review routing
- A named graph prefix (`http://riverbank.example/graph/acme/`)

## List tenants

```bash
riverbank tenant list
```

## Activate RLS

Before tenants are isolated at the database level:

```bash
riverbank tenant activate-rls
```

This enables Row-Level Security policies on all `_riverbank` catalog tables. Safe to call multiple times (idempotent).

## Ingest per-tenant data

Set the tenant context:

```bash
export RIVERBANK_TENANT_ID=acme
riverbank ingest /path/to/acme-docs/
```

All sources, fragments, and runs are tagged with `tenant_id = 'acme'`.

## Suspend a tenant

```bash
riverbank tenant suspend acme
```

Suspended tenants cannot run queries or ingestion. Their data remains intact.

## Delete a tenant

Soft-delete (data preserved):

```bash
riverbank tenant delete acme
```

GDPR erasure (all data destroyed):

```bash
riverbank tenant delete acme --gdpr
```

!!! danger
    `--gdpr` is irreversible. It cascades through the provenance graph and deletes all sources, fragments, runs, compiled triples, and audit log entries belonging to the tenant.

## Verify isolation

Query as the tenant and confirm you only see tenant-scoped data:

```bash
export RIVERBANK_TENANT_ID=acme
riverbank query "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```

Switch to another tenant — different count:

```bash
export RIVERBANK_TENANT_ID=other
riverbank query "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```
