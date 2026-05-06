# CLI reference

Every riverbank subcommand, flag, option, and exit code.

## Global options

The `riverbank` CLI is built with Typer. Global behaviour:

- `--help` on any command shows usage
- `--no-args-is-help` — running `riverbank` with no arguments shows help

## Commands

### `riverbank version`

Print the installed package version.

```
$ riverbank version
riverbank 0.9.0
```

**Exit codes:** 0 (always succeeds)

---

### `riverbank config`

Show the resolved runtime configuration (from environment variables and optional TOML config file).

```
$ riverbank config
┌────────────────────────────────────┐
│ riverbank configuration            │
├──────────────────┬─────────────────┤
│ Key              │ Value           │
├──────────────────┼─────────────────┤
│ db.dsn           │ postgresql://…  │
│ llm.provider     │ ollama          │
│ llm.api_base     │ http://…/v1     │
│ llm.model        │ llama3.2        │
│ llm.embed_model  │ nomic-embed-text│
│ langfuse.enabled │ False           │
│ langfuse.host    │ http://…:3000   │
└──────────────────┴─────────────────┘
```

**Exit codes:** 0

---

### `riverbank health`

Run health checks against the full extension stack.

Checks:

- `pgtrickle.preflight()` — 7 system checks
- `pg_ripple.pg_tide_available()` — pg-tide sidecar detection
- Circuit breaker status for all LLM providers

**Exit codes:** 0 (all healthy), 1 (any check failed)

---

### `riverbank init`

Initialise the `_riverbank` schema by running Alembic migrations.

Also activates the built-in `pg:skos-integrity` shape bundle via `pg_ripple.load_shape_bundle('skos-integrity')`.

**Exit codes:** 0 (success), 1 (migration failed)

---

### `riverbank ingest <corpus>`

Ingest a document corpus into the knowledge graph.

| Option | Default | Description |
|--------|---------|-------------|
| `<corpus>` | required | Path to a corpus directory or file |
| `--profile`, `-p` | `default` | Compiler profile name or YAML file path |
| `--dry-run` | `false` | Parse and fragment only; skip extraction and graph writes |
| `--mode`, `-m` | `full` | Extraction mode: `full` or `vocabulary` |

**Exit codes:** 0 (success), 1 (errors during ingest)

---

### `riverbank query <sparql>`

Execute a SPARQL SELECT or ASK query against the compiled knowledge graph.

| Option | Default | Description |
|--------|---------|-------------|
| `<sparql>` | required | SPARQL query string |
| `--graph`, `-g` | none | Restrict query to this named graph IRI |
| `--format`, `-f` | `table` | Output format: `table`, `json`, `csv` |
| `--expand`, `-e` | none | Comma-separated seed terms to expand via thesaurus |

**Exit codes:** 0

---

### `riverbank runs`

Inspect recent compiler runs with outcome, token counts, and Langfuse links.

| Option | Default | Description |
|--------|---------|-------------|
| `--since`, `-s` | `24h` | Duration filter (e.g., `1h`, `30m`, `7d`) |
| `--profile`, `-p` | none | Filter by profile name |
| `--limit`, `-n` | `50` | Maximum rows to return |

**Exit codes:** 0, 1 (database error)

---

### `riverbank lint`

Run quality checks against a named graph.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--shacl-only` | `false` | SHACL quality report only |
| `--threshold`, `-t` | `0.7` | Minimum acceptable SHACL score |
| `--layer`, `-l` | `""` | Lint layer: `""` (SHACL) or `vocab` (SKOS integrity) |

**Exit codes:** 0 (passed), 1 (failed)

---

### `riverbank explain <artifact_iri>`

Dump the dependency tree of a compiled artifact.

| Option | Default | Description |
|--------|---------|-------------|
| `<artifact_iri>` | required | IRI of the artifact to inspect |

**Exit codes:** 0, 1 (query error)

---

### `riverbank explain-conflict <iri>`

Explain contradictions for an entity or fact.

| Option | Default | Description |
|--------|---------|-------------|
| `<iri>` | required | IRI of the entity or fact |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |

**Exit codes:** 0, 1 (query error)

---

### `riverbank render <entity_iri>`

Render an entity page from the compiled knowledge graph.

| Option | Default | Description |
|--------|---------|-------------|
| `<entity_iri>` | required | IRI of the entity to render |
| `--format`, `-f` | `markdown` | Output format: `markdown`, `jsonld`, `html` |
| `--target`, `-t` | `docs/` | Directory to write rendered pages |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Source named graph |
| `--persist/--no-persist` | `--persist` | Write `pgc:RenderedPage` back to graph |

**Exit codes:** 0 (success), 1 (render failed)

---

### `riverbank recompile`

Bulk reprocess all sources compiled by a profile version.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | required | Profile name |
| `--version`, `-v` | `1` | Profile version |
| `--dry-run` | `false` | List sources without re-extracting |
| `--limit`, `-n` | `0` | Max sources to recompile (0 = all) |

**Exit codes:** 0 (success), 1 (errors)

---

### `riverbank profile register <yaml_path>`

Register a compiler profile from a YAML file into the catalog.

| Option | Default | Description |
|--------|---------|-------------|
| `<yaml_path>` | required | Path to the profile YAML file |

**Exit codes:** 0 (registered), 1 (file not found)

---

### `riverbank source set-profile <source_iri> <profile_name>`

Associate a registered source with a compiler profile.

| Option | Default | Description |
|--------|---------|-------------|
| `<source_iri>` | required | Source IRI to update |
| `<profile_name>` | required | Profile name to associate |
| `--version`, `-v` | `1` | Profile version |

**Exit codes:** 0 (success), 1 (not found)

---

### `riverbank review queue`

Queue low-confidence extractions for human review in Label Studio.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph to scan |
| `--limit`, `-n` | `50` | Maximum items to queue |
| `--dry-run` | `false` | Print candidates without submitting |
| `--ls-url` | `http://localhost:8080` | Label Studio URL |
| `--ls-key` | `""` | Label Studio API key |
| `--ls-project` | `0` | Project ID (0 = auto-create) |

**Exit codes:** 0

---

### `riverbank review collect`

Collect completed review decisions from Label Studio.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name (for example bank path) |
| `--ls-url` | `http://localhost:8080` | Label Studio URL |
| `--ls-key` | `""` | Label Studio API key |
| `--ls-project` | `0` | Project ID |
| `--write/--no-write` | `--write` | Write decisions to `<human-review>` graph |

**Exit codes:** 0

---

### `riverbank tenant activate-rls`

Enable Row-Level Security on all `_riverbank` catalog tables. Idempotent.

**Exit codes:** 0

---

### `riverbank tenant create <tenant_id>`

Create a new tenant.

| Option | Default | Description |
|--------|---------|-------------|
| `<tenant_id>` | required | Unique tenant slug |
| `--name`, `-n` | `""` | Human-readable name |
| `--ls-org` | `0` | Label Studio organisation ID |

**Exit codes:** 0 (created), 1 (failed)

---

### `riverbank tenant list`

List all registered tenants.

**Exit codes:** 0

---

### `riverbank tenant suspend <tenant_id>`

Suspend a tenant (blocks all operations via RLS).

**Exit codes:** 0 (suspended), 1 (failed)

---

### `riverbank tenant delete <tenant_id>`

Delete a tenant.

| Option | Default | Description |
|--------|---------|-------------|
| `<tenant_id>` | required | Tenant slug |
| `--gdpr` | `false` | GDPR erasure: delete all data rows |

**Exit codes:** 0 (deleted), 1 (failed)

---

### `riverbank federation register <name> <sparql_url>`

Register a remote SPARQL endpoint for federated compilation.

| Option | Default | Description |
|--------|---------|-------------|
| `<name>` | required | Logical name for the endpoint |
| `<sparql_url>` | required | Remote SPARQL endpoint URL |
| `--remote-graph` | `http://riverbank.example/graph/trusted` | Remote named graph |
| `--weight`, `-w` | `0.8` | Confidence weight [0.0–1.0] |
| `--timeout` | `30` | Query timeout in seconds |

**Exit codes:** 0 (registered), 1 (failed)

---

### `riverbank federation compile <name>`

Pull triples from a remote endpoint and write them locally.

| Option | Default | Description |
|--------|---------|-------------|
| `<name>` | required | Endpoint name |
| `--local-graph` | `http://riverbank.example/graph/trusted` | Local target graph |
| `--limit`, `-n` | `1000` | Maximum triples to fetch |

**Exit codes:** 0 (success), 1 (failed)
