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
riverbank 0.15.1
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

### `riverbank download-models`

Pre-download sentence-transformer embedding models to the local Hugging Face cache. Prevents first-use latency during ingest when `embed_model` is configured.

**Exit codes:** 0

---

### `riverbank ingest <corpus>`

Ingest a document corpus into the knowledge graph.

| Option | Default | Description |
|--------|---------|-------------|
| `<corpus>` | required | Path to a corpus directory or file |
| `--profile`, `-p` | `default` | Compiler profile name or YAML file path |
| `--dry-run` | `false` | Parse and fragment only; skip extraction and graph writes |
| `--mode`, `-m` | `full` | Extraction mode: `full` or `vocabulary` |
| `--set` | — | Override profile setting, e.g. `--set llm.model=gpt-4o` |

**Exit codes:** 0 (success), 1 (errors during ingest)

---

### `riverbank clear-graph`

Delete all triples from a named graph (or every graph).

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | none | Named graph IRI to clear; omit to clear all graphs |
| `--yes` | `false` | Skip confirmation prompt |

**Exit codes:** 0

---

### `riverbank reset-database`

Reset the entire database: clear all graphs and delete all fragment metadata from the catalog.

| Option | Default | Description |
|--------|---------|-------------|
| `--yes` | `false` | Skip confirmation prompt |

**Exit codes:** 0

---

### `riverbank query <sparql>`

Execute a SPARQL SELECT or ASK query against the compiled knowledge graph.

| Option | Default | Description |
|--------|---------|-------------|
| `<sparql>` | required | SPARQL query string |
| `--graph`, `-g` | none | Restrict query to this named graph IRI |
| `--format`, `-f` | `table` | Output format: `table`, `json`, `csv` |
| `--expand`, `-e` | none | Comma-separated seed terms to expand via thesaurus |
| `--include-tentative` | `false` | Union trusted and tentative graphs; results ordered by confidence |

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

---

### `riverbank explain-rejections`

Show triples discarded in recent extraction runs, grouped by rejection reason (evidence span not found, below noise floor, ontology mismatch, safety cap).

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Filter by profile name |
| `--since`, `-s` | `1h` | Duration filter |
| `--limit`, `-n` | `50` | Maximum rows to return |

**Exit codes:** 0

---

### `riverbank promote-tentative`

Promote tentative triples whose consolidated confidence crosses the trusted threshold. Writes `pgc:PromotionEvent` provenance records.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name (determines trusted threshold) |
| `--graph`, `-g` | `http://riverbank.example/graph/tentative` | Source tentative graph |
| `--dry-run` | `false` | Print candidates without writing |

**Exit codes:** 0 (success), 1 (no candidates or error)

---

### `riverbank validate-graph`

Run the profile's competency questions against the compiled graph and report coverage.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--threshold`, `-t` | `0.7` | Minimum coverage fraction |

**Exit codes:** 0 (passed), 1 (below threshold)

---

### `riverbank build-knowledge-context`

Preview the KNOWN GRAPH CONTEXT block that would be injected for a specific fragment.

| Option | Default | Description |
|--------|---------|-------------|
| `--fragment`, `-f` | required | Fragment IRI or key |
| `--profile`, `-p` | `default` | Profile name |

**Exit codes:** 0

---

### `riverbank deduplicate-entities`

Embed entity labels and write `owl:sameAs` links for duplicates above the similarity threshold.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--threshold`, `-t` | `0.92` | Cosine similarity threshold |
| `--dry-run` | `false` | Print candidates without writing |

**Exit codes:** 0

---

### `riverbank verify-triples`

Re-evaluate low-confidence triples with a self-critique LLM call. Confirmed triples receive a confidence boost; rejected triples are quarantined to `graph/draft`.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--dry-run` | `false` | Print candidates without writing |

**Exit codes:** 0

---

### `riverbank normalize-predicates`

Cluster near-duplicate predicates and write `owl:equivalentProperty` links. Reduces predicate vocabulary by 30–50%.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--threshold`, `-t` | `0.85` | Similarity threshold |
| `--dry-run` | `false` | Print candidates without writing |

**Exit codes:** 0

---

### `riverbank detect-contradictions`

Detect triples that conflict on functional predicates and demote both below the trusted threshold.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name (supplies functional predicate annotations) |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--dry-run` | `false` | Print conflicts without writing |

**Exit codes:** 0

---

### `riverbank induce-schema`

Cold-start schema induction: collect all unique predicates and entity types from the graph, then ask the LLM to propose a minimal OWL ontology. The proposal is written to `ontology/` after human review.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--output`, `-o` | `ontology/induced.ttl` | Output Turtle file |
| `--profile`, `-p` | `default` | Profile name |

**Exit codes:** 0

---

### `riverbank gc-tentative`

Archive stale tentative triples that were never promoted within the configured TTL.

| Option | Default | Description |
|--------|---------|-------------|
| `--older-than` | `30d` | Archive triples older than this duration |
| `--dry-run` | `false` | Print candidates without archiving |

**Exit codes:** 0

---

### `riverbank benchmark`

Re-extract a golden corpus and compare against ground truth for quality regression.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | required | Profile name |
| `--golden` | required | Path to golden corpus directory |
| `--fail-below-f1` | `0.85` | Fail build if F1 falls below this value |

**Exit codes:** 0 (passed), 1 (below threshold)

---

### `riverbank expand-few-shot`

Auto-expand the few-shot example bank with high-confidence triples that satisfy competency questions.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Named graph IRI |
| `--max-examples` | `15` | Maximum total examples per profile |
| `--dry-run` | `false` | Print candidates without writing |

**Exit codes:** 0

---

### `riverbank validate-shapes`

Validate a named graph against SHACL shapes and report violations.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | required | Named graph IRI |
| `--shapes`, `-s` | `ontology/pgc-shapes.ttl` | SHACL shapes graph file |
| `--confidence-penalty` | `0.0` | Confidence reduction for violating triples |

**Exit codes:** 0 (no violations), 1 (violations found)

---

### `riverbank run-construct-rules`

Execute SPARQL CONSTRUCT rules from the profile and write inferred triples to `graph/inferred`.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile`, `-p` | `default` | Profile name (supplies CONSTRUCT rules) |
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Source named graph |

**Exit codes:** 0

---

### `riverbank run-owl-rl`

Apply OWL 2 RL forward-chaining rules and write inferred triples to `graph/inferred`.

| Option | Default | Description |
|--------|---------|-------------|
| `--graph`, `-g` | `http://riverbank.example/graph/trusted` | Source named graph |
| `--ontology`, `-o` | `ontology/pgc.ttl` | OWL ontology file |

**Exit codes:** 0

---

### `riverbank evaluate-wikidata`

Evaluate riverbank extraction quality against Wikidata ground truth.

| Option | Default | Description |
|--------|---------|-------------|
| `--article` | — | Single article title, Wikipedia URL, or Wikidata Q-id |
| `--dataset` | — | Path to benchmark YAML (batch mode) |
| `--profile`, `-p` | `wikidata-eval-v1` | Compiler profile |
| `--no-cache` | `false` | Bypass local article cache |
| `--cache-only` | `false` | Offline mode: raise error if not cached |
| `--output`, `-o` | — | Write JSON report to this path |
| `--set` | — | Override profile setting |

Exactly one of `--article` or `--dataset` is required.

**Exit codes:** 0 (evaluation complete), 1 (error)

---

### `riverbank recall-gap-analysis`

Identify Wikidata properties where recall falls below the threshold and generate targeted extraction examples.

| Option | Default | Description |
|--------|---------|-------------|
| `--results` | required | Path to an `evaluate-wikidata` JSON result file |
| `--threshold`, `-t` | `0.50` | Per-property recall threshold |
| `--output`, `-o` | — | Write generated examples to this file |

**Exit codes:** 0

---

### `riverbank tune-extraction-prompts`

Analyse evaluation failures and generate targeted extraction prompt patches.

| Option | Default | Description |
|--------|---------|-------------|
| `--results` | required | Path to an `evaluate-wikidata` JSON result file |
| `--profile`, `-p` | `default` | Profile to patch |
| `--output`, `-o` | — | Write patch YAML to this file |

**Exit codes:** 0

---

### `riverbank sbom`

Generate a CycloneDX SBOM for the installed riverbank package.

| Option | Default | Description |
|--------|---------|-------------|
| `--format`, `-f` | `json` | Output format: `json` or `xml` |
| `--output`, `-o` | — | Write SBOM to this file (stdout if omitted) |
| `--audit` | `false` | Fail if any dependency has a known CVE |

**Exit codes:** 0 (success), 1 (CVE found when `--audit` is set)

---

### `riverbank entities list`

List all entities in the entity registry with their labels, types, and synonym rings.

| Option | Default | Description |
|--------|---------|-------------|
| `--type`, `-t` | — | Filter by entity type IRI |
| `--limit`, `-n` | `50` | Maximum rows |

**Exit codes:** 0

---

### `riverbank entities merge <source_iri> <target_iri>`

Merge two entity records: all triples referencing `<source_iri>` are rewritten to `<target_iri>` and an `owl:sameAs` link is written.

| Option | Default | Description |
|--------|---------|-------------|
| `<source_iri>` | required | Entity to merge (will become an alias) |
| `<target_iri>` | required | Canonical entity to keep |
| `--dry-run` | `false` | Print affected triples without writing |

**Exit codes:** 0 (success), 1 (not found)
