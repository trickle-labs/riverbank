# Multi-tenant setup

This tutorial sets up two isolated tenants with Row-Level Security, per-tenant named graphs, and demonstrates that no data leaks between them.

## Scenario

You're deploying riverbank as shared infrastructure for two teams. Each team has its own corpus, its own compiled graph, and must never see the other team's data — even if they share the same PostgreSQL instance.

## Prerequisites

- riverbank installed with `[dev]` extras
- Docker Compose stack running
- `riverbank init` completed

## Step 1: Activate Row-Level Security

```bash
riverbank tenant activate-rls
```

This enables RLS policies on all `_riverbank` catalog tables. The policies filter rows by `tenant_id`, which is set via the PostgreSQL session variable `app.current_tenant`.

## Step 2: Create tenants

```bash
riverbank tenant create team-alpha --name "Team Alpha"
riverbank tenant create team-beta --name "Team Beta"
```

Each tenant gets:

- A row in `_riverbank.tenants`
- A named graph prefix (`http://riverbank.example/graph/team-alpha/`)
- Isolation via RLS on sources, fragments, runs, and audit log entries

## Step 3: List tenants

```bash
riverbank tenant list
```

You should see both tenants with status `active`.

## Step 4: Ingest per-tenant corpora

Set the tenant context before ingesting:

```bash
export RIVERBANK_TENANT_ID=team-alpha
riverbank ingest /path/to/alpha-docs/ --profile docs-policy-v1

export RIVERBANK_TENANT_ID=team-beta
riverbank ingest /path/to/beta-docs/ --profile docs-policy-v1
```

Each ingest run writes to the tenant's named graph and tags all catalog rows with the tenant ID.

## Step 5: Verify isolation

Query as team-alpha — you should only see alpha's triples:

```bash
export RIVERBANK_TENANT_ID=team-alpha
riverbank query "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```

Query as team-beta — different count:

```bash
export RIVERBANK_TENANT_ID=team-beta
riverbank query "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```

## Step 6: Suspend a tenant

```bash
riverbank tenant suspend team-beta
```

A suspended tenant's RLS policies block all operations. Queries return empty results.

## Step 7: GDPR erasure

```bash
riverbank tenant delete team-beta --gdpr
```

!!! danger
    This is irreversible. The `--gdpr` flag cascades through the provenance graph and deletes all data rows belonging to the tenant: sources, fragments, runs, compiled triples, and audit log entries.

Without `--gdpr`, the tenant is soft-deleted (status changes to `deleted`) but data remains for archival purposes.

## What you learned

- RLS provides database-level tenant isolation without application-level filtering
- Each tenant gets its own named graph prefix for compiled knowledge
- The `RIVERBANK_TENANT_ID` environment variable sets the session context
- GDPR erasure cascades through the full provenance chain
- Suspension immediately blocks all tenant-scoped operations
