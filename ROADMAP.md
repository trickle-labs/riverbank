# riverbank Roadmap

> **Audience:** Product managers, stakeholders, and technically curious readers
> who want to understand what each release delivers and why it matters — without
> needing to read Python code or SQL specifications.
>
> **Dependencies:** riverbank is built on top of
> [pg-ripple](https://github.com/grove/pg-ripple) ≥ 0.98.0,
> [pg-trickle](https://github.com/grove/pg-trickle) ≥ 0.48.0, and
> [pg-tide](https://github.com/trickle-labs/pg-tide) ≥ 0.14.0.
> The implementation blueprint lives in
> [plans/riverbank-implementation.md](plans/riverbank-implementation.md);
> the strategy document lives in [plans/riverbank.md](plans/riverbank.md).

---

## Versions

### Skeleton and MVP (v0.1.x – v0.3.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.1.0 | Skeleton — `docker compose up` proves the deployment story: CLI scaffolding, catalog migrations, no-op extractor, Langfuse wired | **Done** | Small |
| v0.2.0 | MVP ingestion — Markdown corpus → triples with citation grounding, confidence scores, and fragment-level skip on re-ingest | **Done** | Large |
| v0.3.0 | MVP completion — `riverbank query`, `riverbank runs`, cost accounting, Langfuse traces, golden corpus CI gate | **Done** | Medium |

### Incremental Compilation (v0.4.x – v0.5.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.4.0 | Incremental compilation core — artifact dependency graph, `riverbank explain`, recompile flow, vocabulary pass, SKOS integrity shape bundle, `tenant_id` schema scaffold | **Done** | Large |
| v0.5.0 | Multi-format parsing and enrichment — Docling, spaCy NER + vocabulary lookup, fuzzy entity matching, embedding generation, Singer tap configuration (pg-tide ≥ 0.14.0) | **Done** | Large |

### Quality Gates and Review (v0.6.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.6.0 | Quality gates and human review loop — Label Studio integration, active-learning queue, example bank, Langfuse evals, lint flow, Prefect introduced | **Done** | Large |

### Production Hardening (v0.7.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.7.0 | Production hardening — Helm chart, multi-replica workers, Prometheus/Perses dashboards, secret management, circuit breakers, audit trail, bulk reprocessing | **Done** | Very Large |

### Advanced Epistemic Features (v0.8.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.8.0 | Epistemic layer — negative knowledge records, argument graphs, assumption registry, all 9 epistemic status labels, model ensemble, contradiction explanation, coverage maps | Planned | Very Large |

### Multi-tenant and Prose Generation (v0.9.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.9.0 | Multi-tenant and rendering — tenant_id RLS activation, federated compilation (SPARQL SERVICE), Markdown/JSON-LD page rendering, streaming render via SSE | Planned | Very Large |

### Stable Release (v1.0.0)

| Version | Description | Status | Size |
|---|---|---|---|
| v1.0.0 | Stable — full API stability guarantee, PyPI package, signed artifacts, SBOM, Helm chart stability, complete documentation site | Planned | Large |

---

## External dependency risk

Several planned versions delegate implementation to pg-ripple or pg-tide rather than owning the capability in Python. The table below identifies the features at risk and the mitigation if a dependency is unavailable at the start of a release cycle.

| Capability | Owned by | First needed | Mitigation if delayed |
|---|---|---|---|
| `pg:fuzzy_match()`, `pg:token_set_ratio()`, `suggest_sameas()`, `pagerank_find_duplicates()` | pg-ripple | v0.5.0 | Fuzzy entity matching deferred; spaCy pre-resolution still ships |
| `pg_ripple.explain_contradiction()` | pg-ripple | v0.8.0 | `riverbank explain-conflict` deferred; contradiction detection via SHACL still works |
| `pg_ripple.refresh_coverage_map()` | pg-ripple | v0.8.0 | Coverage map generation deferred; competency-question coverage computed locally |
| SPARQL `SERVICE` federation | pg-ripple | v0.9.0 | Federated compilation deferred; local compilation unaffected |
| Relay circuit breakers, DLQ, backpressure | pg-tide | v0.7.0 | Relay health visible in `riverbank health`; manual configuration fallback |

**Policy:** if a dependency is unavailable at the start of a release cycle, the affected feature moves to the following minor version. All core ingestion, extraction, catalog, and provenance features are riverbank-owned and carry no upstream dependency.

---

## What each release delivers

### v0.1.0 — Skeleton

Goal: prove the deployment story end-to-end with no LLM calls.

- [x] `riverbank/` repo with `pyproject.toml`, `Dockerfile`, `docker-compose.yml`
- [x] `riverbank` CLI with `init`, `version`, `health` subcommands
- [x] `health` calls `pgtrickle.preflight()` (7 system checks) and
  `pg_ripple.pg_tide_available()` to verify the full extension stack before
  any ingest attempt
- [x] Catalog schema migrations (Alembic) for `sources`, `fragments`, `profiles`,
  `runs`, `artifact_deps`, `log` tables in `_riverbank`
- [x] CI workflow: `pytest` against an ephemeral PostgreSQL with pg_ripple,
  pg_trickle, and pg_tide installed via `testcontainers-python`
- [x] No-op extractor: records a run, emits an OTel span, writes nothing to the
  graph — verifying orchestration plumbing end-to-end
- [x] `docker compose up` brings up: PostgreSQL with pg_ripple ≥ 0.98 + pg_trickle
  ≥ 0.48, pg-tide v0.14, riverbank worker, Langfuse, Ollama

**Exit criterion:** `docker compose up -d && riverbank health` prints
"all systems nominal" on a clean checkout.

---

### v0.2.0 — MVP Ingestion

Goal: ingest a Markdown corpus, extract atomic facts, write them to pg_ripple
with confidence and provenance, and demonstrate fragment-level skip on
re-ingest.

- [x] `markdown` parser + `heading` fragmenter plugin
- [x] `instructor` extractor: OpenAI-compatible endpoint (Ollama for local/CI),
  `EvidenceSpan` validator, Pydantic retry loop
- [x] `docs-policy-v1` example compiler profile (YAML → `_riverbank.profiles`)
- [x] Editorial policy ingest gate: minimum heading depth, fragment length, language
  check
- [x] Citation grounding: every triple must carry a `prov:wasDerivedFrom` edge with
  character-range evidence; fabricated quotes rejected by the type system
- [x] `load_triples_with_confidence()` writes facts to a named graph in pg_ripple
- [x] `shacl_score()` gate routes low-quality output to `<draft>` graph, not
  `<trusted>`
- [x] Fragment hash check (`xxh3_128`): re-ingesting an unchanged file produces
  0 LLM calls
- [x] Filesystem connector with `watchdog` directory-watcher mode
- [x] `riverbank ingest <path>` command
- [x] Token counts and cost estimate recorded in `_riverbank.runs`
- [x] OTel spans wrap every pipeline stage; Langfuse receives LLM call traces

**Exit criterion:** `riverbank ingest examples/markdown-corpus/` produces
triples in pg_ripple, all with `pgc:fromFragment` edges and confidence scores.
Re-running produces 0 LLM calls.

---

### v0.3.0 — MVP Completion

Goal: close out the MVP with query access, run inspection, cost visibility, and
a reproducible CI gate.

- [x] `riverbank query <sparql>` — execute SPARQL against the compiled graph
- [x] `riverbank runs --since 1h` — inspect recent compiler runs with outcome,
  token counts, and Langfuse deep-links
- [x] Cost accounting: per-source and per-profile cost dashboards via
  `_riverbank.runs.cost_usd`; cost tables in `riverbank/cost_tables/`
- [x] Schema rejection and citation enforcement acceptance tests
- [x] Golden corpus: `tests/golden/` with SPARQL `ASK`/`SELECT` assertions over a
  fixed Markdown corpus; profile or model changes that break a golden assertion
  fail CI
- [x] Full test suite runs in under 10 minutes in CI against `ollama/llama3.2:3b`
- [x] `riverbank profile register` and `riverbank source set-profile` commands
- [x] **`riverbank lint --shacl-only`** — thin SHACL quality report against the trusted named graph; exits non-zero if score falls below the profile threshold. No Prefect required. Establishes governance as a first-class operation from day one, before the full lint pass lands in v0.6.0.
- [x] **Competency question CI gate** — golden corpus assertions are generated from the `competency_questions` array in each compiler profile. CI validates not just that triples were written, but that the compiled graph answers what the profile was built to answer.

**Exit criterion:** end-to-end demo on pg_ripple's own `docs/src/**/*.md`:
≥ 80% fragment skip rate on re-ingest, ≥ 95% of facts with valid evidence
spans, full compile cost < $5 with `gpt-4o-mini` or $0 with Ollama.

---

### v0.4.0 — Incremental Compilation

Goal: prove the system rebuilds *only* what changed when a source updates, establish vocabulary hygiene as an upstream constraint before relationship extraction, and scaffold the multi-tenant catalog schema.

- [x] **Artifact dependency graph.** Every compiled artifact records
  `(fragment, profile_version, rule_set)` dependencies in
  `_riverbank.artifact_deps`; queryable in SQL and SPARQL.
- [x] **`riverbank explain <artifact-iri>`** — dumps the dependency tree of any
  compiled artifact: fragments, profile version, rules that contributed.
- [x] **Recompile flow.** Changed fragments → invalidate dependent artifacts →
  re-extract → re-derive → emit semantic diff event via pg-trickle +
  `pgtrickle.attach_outbox()`.
- [x] **Vocabulary pass.** `riverbank ingest --mode vocabulary` (or
  `run_mode_sequence: ['vocabulary', 'full']` in the profile) processes the
  corpus with the `ExtractedEntity` schema first, writing `skos:Concept`
  triples (preferred label, alternate labels, scope note) into `<vocab>` before
  any relationship extraction. Subsequent full passes are given the compiled
  vocabulary as a structured context constraint, snapping entity references to
  canonical preferred-label IRIs before writing facts — upstream vocabulary
  hygiene rather than downstream deduplication.
- [x] **SKOS structural integrity shape bundle.** `riverbank init` activates the
  built-in `pg:skos-integrity` shape bundle via
  `pg_ripple.load_shape_bundle('skos-integrity')` (pg-ripple ≥ 0.98.0). The
  six shapes (prefLabel required, scopeNote recommended, broader-cycle
  detection, conflicting match-type check, orphan concept warning, altLabel
  collision check) are defined and maintained in pg-ripple — riverbank ships
  no Turtle files for these rules. `riverbank lint --layer vocab` runs the
  bundle against the `<vocab>` named graph. This is the machine-executable
  form of the Ontology Pipeline output quality contract.
- [x] **`tenant_id` schema scaffold.** A nullable `tenant_id` column is added to
  all `_riverbank` tables via Alembic migration (0002). Row-level security is
  not activated yet — that lands in v0.9.0 — but the column is present so that
  all downstream migrations are additive-only.

**Exit criterion:** modify one paragraph in one Markdown file, re-run
`riverbank ingest`, exactly one fragment re-extracted, semantic diff event
arrives on the pg_trickle outbox. `riverbank explain entity:Acme` prints a
complete dependency tree.

---

### v0.5.0 — Multi-format Parsing and Enrichment

Goal: extend ingestion beyond Markdown to office documents and web content, and add the enrichment layer (NER, fuzzy matching, embeddings) that quality gates and epistemic features depend on.

- [x] **Docling integration.** PDF, DOCX, PPTX, HTML, and image OCR via Docling ≥
  2.92. `Docling` becomes the default parser for non-Markdown sources.
- [x] **spaCy NER pre-resolution + vocabulary lookup.** Named entities extracted
  before the LLM call; when a vocabulary pass has run, the pre-resolution step
  also queries the `skos:prefLabel` / `skos:altLabel` index and injects matched
  preferred-label IRIs into the structured context block.
- [x] **Fuzzy entity matching.** pg_ripple `pg:fuzzy_match()` and
  `pg:token_set_ratio()` (GIN trigram index) for query-time matching;
  `suggest_sameas()` and `pagerank_find_duplicates()` for dedup; RapidFuzz for
  pre-LLM Python-side candidate preparation.
- [x] **Embedding generation.** sentence-transformers produces embeddings for each
  compiled summary. Entity-cluster centroid views are maintained as
  `avg(embedding)::vector` pg_trickle stream tables (pgVector IVM, v0.37+):
  centroid updates incrementally with no full scan on each new fact.
- [x] **Singer tap configuration.** pg-tide ≥ 0.14.0 ships native Singer tap
  mode: tap invocation, STATE checkpoint persistence (resumable taps across
  restarts), and SCHEMA drift detection are all handled by the pg-tide sidecar.
  riverbank's contribution is profile-side: a `singer_taps` block in the
  compiler profile YAML maps each tap (`tap-github`, `tap-slack-search`, etc.)
  to a `tide.relay_inlet_config` row, which pg-tide picks up via `NOTIFY` hot
  reload. No Python tap-invocation code lives in riverbank.

**Exit criterion:** a PDF and a DOCX file ingest successfully alongside the
existing Markdown corpus; entity-cluster centroid views are queryable via SQL;
`riverbank query` returns vector-similar results for a test entity; fuzzy match
suggestions appear in `riverbank explain` output for a known near-duplicate pair.

---

### v0.6.0 — Quality Gates and Review Loop

Goal: a running human-in-the-loop pipeline that converts low-confidence
extractions into reviewed, high-confidence facts.

- [x] **Label Studio integration.** `LabelStudioReviewer` plugin creates one task
  per review-queue item; pre-labels with LLM extraction; webhook posts
  decisions back; corrections enter `<human-review>` named graph.
  Custom labeling templates: atomic-fact correction, span-based evidence
  annotation, ensemble disagreement arbitration.
- [x] **Active-learning review queue.** `riverbank review queue` runs the
  centrality × uncertainty SPARQL query and refreshes Label Studio task
  priorities — maximum leverage per review hour.
- [x] **Editorial policy example bank.** Each Label Studio decision exports to the
  profile's example bank; next compile run uses these as few-shot examples.
- [x] **SHACL score history.** Daily Prefect flow snapshots `shacl_score()` per
  named graph into Prometheus. **Prefect is introduced here**; the APScheduler
  job from v0.2.0 is replaced.
- [x] **Langfuse evaluations.** Generated Q&A pairs run as Langfuse dataset
  evaluations on every recompile; regressions surface as alerts.
- [x] **Lint flow.** `riverbank lint` runs a full lint pass and writes findings to
  `pgc:LintFinding` triples; Prefect schedules it nightly.
- [x] **Thesaurus layer activation.** `riverbank query` expands query terms via the
  `<thesaurus>` named graph before dispatching BM25, vector, and graph traversal
  streams. `skos:altLabel` provides synonym coverage; `skos:related` provides
  associative coverage; `skos:exactMatch` / `skos:closeMatch` provide cross-corpus
  alignment. The expansion is a SPARQL lookup — sub-millisecond, no LLM call.
  This is the release where the thesaurus layer transitions from a compilation
  artifact to an active query-time asset.

**Exit criterion:** reviewer receives a Label Studio task within 60 seconds of
a low-confidence extraction; correction is reflected in the next SPARQL query;
example bank has ≥ 20 entries after a one-week pilot.

---

### v0.7.0 — Production Hardening

Goal: deployable in a regulated production environment with multi-replica
workers, secret management, backups, and SLOs.

- [x] **Helm chart.** `riverbank/helm/` deploys the worker, Prefect server,
  Langfuse, and Label Studio onto Kubernetes; depends on the existing
  pg_ripple chart.
- [x] **Multi-replica workers.** Fragment-level advisory locks
  (`pg_try_advisory_lock(hashtext(fragment_iri)::bigint)`) + run idempotency
  key (fragment_id + profile_id + content_hash) prevent duplicate work without
  an external coordinator.
- [x] **Prometheus metrics + Perses dashboard.** `/metrics` exposes
  `riverbank_runs_total`, `riverbank_run_duration_seconds`,
  `riverbank_llm_cost_usd_total`, `riverbank_shacl_score`,
  `riverbank_review_queue_depth`, `riverbank_context_efficiency_ratio` (graph
  tokens vs estimated naive-RAG tokens per `rag_context()` call). Perses panels
  ship in `riverbank/perses/` and import the pg-tide relay health sub-dashboard
  (relay throughput, error rate, DLQ depth, circuit breaker state, forward
  latency) from pg-tide's own Perses definition — relay metrics are not
  re-implemented in riverbank. The context efficiency panel shows the running
  ratio trend per profile, making the token-cost justification for graph-based
  retrieval quantitatively visible to operators and stakeholders.
- [x] **Secret management.** LLM API keys from environment variables, Kubernetes
  Secrets, or HashiCorp Vault (`hvac`). Keys route through pg-tide's
  `${env:VAR}` / `${file:/path}` secret interpolation for relay credentials;
  no secret is ever logged.
- [x] **Rate limiting + circuit breakers.** Per-provider concurrency limits and a
  circuit breaker (`aiobreaker`) protect against runaway LLM costs during API
  misbehaviour — this covers OpenAI, Anthropic, and Ollama provider calls only.
  Relay pipeline circuit breakers (pg-tide transport layer) are configured via
  `tide.relay_outbox_config` and do not require Python code in riverbank.
  `riverbank health` surfaces open relay circuits from
  `tide.relay_circuit_breaker_status` alongside the existing extension stack
  checks.
- [x] **Audit trail.** Every graph-mutating operation writes to `_riverbank.log`;
  append-only at the database level (`REVOKE UPDATE, DELETE`).
- [x] **Bulk reprocessing.** `riverbank recompile --profile docs-policy-v1
  --version 2` queues all v1 sources for recompilation and produces a semantic
  diff report.
- [x] **OpenTelemetry export.** `OTEL_EXPORTER_OTLP_ENDPOINT` routes traces to any
  collector (Jaeger, Tempo, Honeycomb-OSS).
- [x] **Cost dashboard.** Perses panels: cost per source, cost per profile, cost
  trend, projected monthly spend.

**Load test exit criteria:** three worker replicas process 10,000
fragments/hour; a simulated 1-hour LLM outage triggers the circuit breaker and
recovers without manual intervention; Helm upgrade rolls workers without
dropping in-flight runs.

---

### v0.8.0 — Advanced Epistemic Features

Goal: implement the features that distinguish riverbank from a generic compiler:
explicit absence, structured reasoning, and ensemble verification.

- **Negative knowledge.** `pgc:NegativeKnowledge` records for explicit denials,
  exhaustive search failures, and superseded facts. Compiler profiles can
  declare "search-and-record-absence" rules per predicate.
- **Argument graphs.** `pgc:ArgumentRecord` extractor with a Label Studio
  annotation template for `{claim, evidence, objection, rebuttal}` spans. SPARQL
  navigation: "which policy conclusions have a recorded objection but no
  rebuttal?"
- **Assumption registry.** Extracted assumptions attached as RDF-star
  annotations to facts and entity pages; surfaced by `rag_context()` alongside
  answers.
- **Epistemic status layer.** Every fact gets a `pgc:epistemicStatus`
  annotation from the full set: `observed`, `extracted`, `inferred`,
  `verified`, `deprecated`, `normative`, `predicted`, `disputed`,
  `speculative`. Status flows from compiler outcome, Datalog inference, and
  Label Studio decisions.
- **Model ensemble compilation.** Per-profile opt-in; runs N model variants
  and routes disagreements to Label Studio with a side-by-side template. Hard
  cost cap configurable per profile.
- **Minimal contradiction explanation.** `riverbank explain-conflict <iri>`
  is a CLI wrapper around `pg_ripple.explain_contradiction()` — the
  minimal-cause reasoning engine (SAT-style hitting-set over the inference
  dependency graph) lives in pg-ripple and requires no Python implementation
  in riverbank.
- **Coverage maps.** `pg_ripple.refresh_coverage_map()` computes per-topic
  source density, mean confidence, contradiction count, and recency into the
  `<coverage>` named graph. A Prefect flow joins the result against
  `_riverbank.profiles.competency_questions` to compute the unanswered-question
  count (the one join that requires riverbank's catalog), then writes enriched
  `pgc:CoverageMap` triples surfaced by `rag_context()`.
- **Procedural knowledge compiler profile.** A built-in profile template
  (`procedural-v1`) for runbooks, SOPs, incident-response guides, and onboarding
  flows. The vocabulary pass extracts step names and tool/resource names;
  the full pass extracts step sequences (`pko:nextStep`, `pko:previousStep`),
  decision points (`pko:nextAlternativeStep`), preconditions, required expertise
  levels, and error-handling paths — aligned with the Procedural Knowledge
  Ontology (PKO) from Cefriel. Standard competency questions are generated
  automatically: "What happens if step X fails?", "Which steps require admin
  access?", "What is the rollback path?". This expands riverbank's applicability
  to operational knowledge that currently lives as tribal practice in undocumented
  runbooks.

**Exit criterion:** an argument graph in Label Studio produces a
`pgc:ArgumentRecord` with claim, two evidence nodes, one objection, and one
rebuttal — all queryable in SPARQL. A test-corpus contradiction produces a
hand-verified minimal explanation. Ensemble compilation with 3 models shows
measurable error reduction over a single-model baseline.

---

### v0.9.0 — Multi-tenant and Prose Generation

Goal: deploy as shared infrastructure across multiple knowledge bases; render
compiled knowledge back to prose.

- **Multi-tenant RLS activation.** Row-level security is enabled on all
  `_riverbank` tables using the `tenant_id` column scaffolded in v0.4.0.
  Per-tenant editorial policies, profiles, and named graphs. Tenant lifecycle
  API (create, suspend, delete with GDPR erasure).
- **Tenant-scoped Label Studio.** One Label Studio organisation per tenant;
  reviewer assignments respect tenant boundaries.
- **Federated compilation.** A "remote profile" type pulls SERVICE-federated
  triples from a peer pg_ripple instance into a local compilation context,
  applies confidence weighting, and writes the result locally. The SPARQL
  `SERVICE` keyword is implemented in pg-ripple's query engine; riverbank
  configures a `federation_endpoints` entry via SQL and issues a standard
  SPARQL query — no federation protocol code lives in riverbank.
- **Markdown / JSON-LD page rendering.** `riverbank render` generates entity
  pages, topic surveys, comparison tables, and change digests from compiled
  artifacts. Output formats: Markdown (Obsidian/MkDocs), JSON-LD, HTML.
- **Render scheduling.** Pages stored as `pgc:RenderedPage` artifacts with
  dependency edges to their source facts. When facts change, pages are flagged
  stale and regenerated in the next render flow.
- **Streaming render.** SSE endpoint emits page updates as the underlying graph
  changes, for live documentation sites.

**Exit criteria:** two tenants compile independently on shared PostgreSQL with
no data leakage (verified by RLS tests); `riverbank render --format markdown
--target docs/` produces a navigable MkDocs site with citations linking back to
source fragments; modifying one fact regenerates exactly the pages that depend
on it.

---

### v1.0.0 — Stable Release

Goal: full API stability guarantee; self-service deployment; production SLOs.

- API stability: all public Python APIs, CLI commands, and SPARQL vocabulary
  (`pgc:` ontology) follow semantic versioning; no breaking changes without a
  major version bump.
- PyPI package: `pip install riverbank` installs the worker and CLI; optional
  extras `[ollama]`, `[docling]`, `[labelstudio]`.
- Signed release artifacts and SBOM (`riverbank sbom`) for supply-chain
  compliance.
- Helm chart stability: `helm install riverbank riverbank/riverbank` works
  on any Kubernetes 1.28+ cluster with the pg_ripple chart as a dependency.
- Complete documentation site: MkDocs site generated by `riverbank render`
  from the pg_ripple docs corpus, auto-published on each release.
- SLOs verified in CI: worker availability ≥ 99.5% (rolling 30 days),
  p95 fragment-to-graph latency < 30 s, MTTR from LLM outage < 5 min.

---

## How these releases fit together

```
v0.1.0  ─── Skeleton: CLI, catalog migrations, no-op extractor, docker compose up
    │
v0.2.0  ─── MVP ingestion: Markdown → triples with citations, confidence, fragment skip
    │
v0.3.0  ─── MVP completion: query, runs, cost dashboards, golden corpus CI gate
    │
v0.4.0  ─── Incremental compilation core: dependency graph, explain, recompile flow,
    │        vocabulary pass, SKOS shape bundle, tenant_id schema scaffold
    │
v0.5.0  ─── Multi-format parsing and enrichment: Docling, spaCy NER, fuzzy matching,
    │        embeddings, Singer/pg-tide connector
    │
v0.6.0  ─── Quality gates: Label Studio review loop, active-learning queue,
    │        example bank, Langfuse evals, lint flow, Prefect introduced
    │
v0.7.0  ─── Production hardening: Helm chart, multi-replica workers, Prometheus,
    │        Perses dashboards, audit trail, secret management, circuit breakers
    │
v0.8.0  ─── Advanced epistemic: negative knowledge, argument graphs, assumptions,
    │        9 epistemic statuses, model ensemble, contradiction explanation
    │
v0.9.0  ─── Multi-tenant + rendering: RLS activation, federated compilation,
    │        Markdown/JSON-LD page rendering, streaming SSE render
    │
v1.0.0  ─── Stable: PyPI, signed artifacts, SBOM, Helm stability, SLOs in CI
```

v0.1.0 through v0.3.0 build and close out the MVP. v0.2.0 is the first
release worth demoing to external eyes: a real Markdown corpus compiles into
a governed knowledge graph in under 10 minutes from a clean checkout. v0.3.0
adds the query and inspection surface that makes the MVP useful day-to-day and
closes the CI gate that prevents regressions across pg_ripple/pg_trickle
version bumps.

v0.4.0 is the structural turning point. Fragment-level incremental compilation
is what separates riverbank from a batch re-indexer. The demo for v0.4.0 exit
is the clearest possible: change one paragraph, watch exactly one fragment
recompile, observe the affected facts update in SPARQL, see the semantic event
arrive on the pg_trickle outbox — end-to-end in under a second. This release
also scaffolds the `tenant_id` column on all catalog tables so that the
multi-tenancy migration in v0.9.0 is additive-only.

v0.5.0 extends the ingest surface to office documents and web content, and adds
the enrichment layer (Docling, spaCy, embeddings) that quality gates and
epistemic features in v0.6.0 and later depend on. Splitting this from the
incremental compilation core keeps both releases at a size that can ship
independently.

v0.6.0 closes the human-in-the-loop gap. A knowledge graph without a review
loop is a confidence claim without evidence. Label Studio integration, the
active-learning review queue, and the example bank together enable the quality
feedback cycle that makes extraction quality measurably improve over time.
Prefect is introduced here rather than earlier because it is an operational
dependency (it needs the pipeline to be stable before it adds value).

v0.7.0 is the production gate. Nothing before v0.7.0 is appropriate for
a regulated production environment. The Helm chart, multi-replica workers,
audit trail, and secret management form the minimum deployable production unit.
This release is deliberately large; every item in it is non-negotiable for
production readiness. LLM provider circuit breakers (aiobreaker) protect
against runaway API costs; relay pipeline circuit breakers, DLQ, and backpressure
are configured in pg-tide and do not add Python code to riverbank.

v0.8.0 addresses the epistemic features that distinguish riverbank from a
generic RAG pipeline. Negative knowledge (explicit absences), argument graphs
(structured reasoning), and model ensemble (verification by disagreement) are
all features that generic pipelines do not provide. These are deferred to v0.8.0
because they require a working review loop (v0.6.0) and stable production
infrastructure (v0.7.0) to be useful in practice.

v0.9.0 is additive infrastructure: multi-tenancy RLS activation and rendering.
Both can be developed in parallel with v0.8.0 work. Multi-tenancy is
straightforward because the `tenant_id` column has been present since v0.4.0 —
activating RLS is a policy change, not a schema migration. Rendering is the
last mile between a compiled knowledge graph and a documentation site that
humans can read without a SPARQL client.

v1.0.0 completes the API stability contract. The goal is not to add features at
1.0 but to guarantee that v0.x adopters can upgrade to v1.0 without breaking
changes, with a PyPI package, signed artifacts, and SLOs that an operations team
can reference in a service-level agreement.
