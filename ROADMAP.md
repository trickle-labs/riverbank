# riverbank Roadmap

> **Audience:** Product managers, stakeholders, and technically curious readers
> who want to understand what each release delivers and why it matters — without
> needing to read Python code or SQL specifications.
>
> **Dependencies:** riverbank is built on top of
> [pg-ripple](https://github.com/grove/pg-ripple) ≥ 0.93.0,
> [pg-trickle](https://github.com/grove/pg-trickle) ≥ 0.46.0, and
> [pg-tide](https://github.com/trickle-labs/pg-tide) ≥ 0.6.0.
> The implementation blueprint lives in
> [plans/riverbank-implementation.md](plans/riverbank-implementation.md);
> the strategy document lives in [plans/riverbank.md](plans/riverbank.md).

---

## Versions

### Skeleton and MVP (v0.1.x – v0.3.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.1.0 | Skeleton — `docker compose up` proves the deployment story: CLI scaffolding, catalog migrations, no-op extractor, Langfuse wired | Planned | Small |
| v0.2.0 | MVP ingestion — Markdown corpus → triples with citation grounding, confidence scores, and fragment-level skip on re-ingest | Planned | Large |
| v0.3.0 | MVP completion — `riverbank query`, `riverbank runs`, cost accounting, Langfuse traces, golden corpus CI gate | Planned | Medium |

### Incremental Compilation (v0.4.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.4.0 | Incremental compilation — artifact dependency graph, `riverbank explain`, Docling multi-format parser, spaCy NER, Singer connector, embedding generation | Planned | Very Large |

### Quality Gates and Review (v0.5.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.5.0 | Quality gates and human review loop — Label Studio integration, active-learning queue, example bank, Langfuse evals, lint flow, Prefect introduced | Planned | Large |

### Production Hardening (v0.6.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.6.0 | Production hardening — Helm chart, multi-replica workers, Prometheus/Perses dashboards, secret management, circuit breakers, audit trail, bulk reprocessing | Planned | Very Large |

### Advanced Epistemic Features (v0.7.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.7.0 | Epistemic layer — negative knowledge records, argument graphs, assumption registry, all 9 epistemic status labels, model ensemble, contradiction explanation, coverage maps | Planned | Very Large |

### Multi-tenant and Prose Generation (v0.8.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.8.0 | Multi-tenant and rendering — tenant_id + RLS, federated compilation (SPARQL SERVICE), Markdown/JSON-LD page rendering, streaming render via SSE | Planned | Very Large |

### Stable Release (v1.0.0)

| Version | Description | Status | Size |
|---|---|---|---|
| v1.0.0 | Stable — full API stability guarantee, PyPI package, signed artifacts, SBOM, Helm chart stability, complete documentation site | Planned | Large |

---

## What each release delivers

### v0.1.0 — Skeleton

Goal: prove the deployment story end-to-end with no LLM calls.

- `riverbank/` repo with `pyproject.toml`, `Dockerfile`, `docker-compose.yml`
- `riverbank` CLI with `init`, `version`, `health` subcommands
- `health` calls `pgtrickle.preflight()` (7 system checks) and
  `pg_ripple.pg_tide_available()` to verify the full extension stack before
  any ingest attempt
- Catalog schema migrations (Alembic) for `sources`, `fragments`, `profiles`,
  `runs`, `artifact_deps`, `log` tables in `_riverbank`
- CI workflow: `pytest` against an ephemeral PostgreSQL with pg_ripple,
  pg_trickle, and pg_tide installed via `testcontainers-python`
- No-op extractor: records a run, emits an OTel span, writes nothing to the
  graph — verifying orchestration plumbing end-to-end
- `docker compose up` brings up: PostgreSQL with pg_ripple ≥ 0.93 + pg_trickle
  ≥ 0.46, pg-tide v0.6, riverbank worker, Langfuse, Ollama

**Exit criterion:** `docker compose up -d && riverbank health` prints
"all systems nominal" on a clean checkout.

---

### v0.2.0 — MVP Ingestion

Goal: ingest a Markdown corpus, extract atomic facts, write them to pg_ripple
with confidence and provenance, and demonstrate fragment-level skip on
re-ingest.

- `markdown` parser + `heading` fragmenter plugin
- `instructor` extractor: OpenAI-compatible endpoint (Ollama for local/CI),
  `EvidenceSpan` validator, Pydantic retry loop
- `docs-policy-v1` example compiler profile (YAML → `_riverbank.profiles`)
- Editorial policy ingest gate: minimum heading depth, fragment length, language
  check
- Citation grounding: every triple must carry a `prov:wasDerivedFrom` edge with
  character-range evidence; fabricated quotes rejected by the type system
- `load_triples_with_confidence()` writes facts to a named graph in pg_ripple
- `shacl_score()` gate routes low-quality output to `<draft>` graph, not
  `<trusted>`
- Fragment hash check (`xxh3_128`): re-ingesting an unchanged file produces
  0 LLM calls
- Filesystem connector with `watchdog` directory-watcher mode
- `riverbank ingest <path>` command
- Token counts and cost estimate recorded in `_riverbank.runs`
- OTel spans wrap every pipeline stage; Langfuse receives LLM call traces

**Exit criterion:** `riverbank ingest examples/markdown-corpus/` produces
triples in pg_ripple, all with `pgc:fromFragment` edges and confidence scores.
Re-running produces 0 LLM calls.

---

### v0.3.0 — MVP Completion

Goal: close out the MVP with query access, run inspection, cost visibility, and
a reproducible CI gate.

- `riverbank query <sparql>` — execute SPARQL against the compiled graph
- `riverbank runs --since 1h` — inspect recent compiler runs with outcome,
  token counts, and Langfuse deep-links
- Cost accounting: per-source and per-profile cost dashboards via
  `_riverbank.runs.cost_usd`; cost tables in `riverbank/cost_tables/`
- Schema rejection and citation enforcement acceptance tests
- Golden corpus: `tests/golden/` with SPARQL `ASK`/`SELECT` assertions over a
  fixed Markdown corpus; profile or model changes that break a golden assertion
  fail CI
- Full test suite runs in under 10 minutes in CI against `ollama/llama3.2:3b`
- `riverbank profile register` and `riverbank source set-profile` commands
- **`riverbank lint --shacl-only`** — thin SHACL quality report against the trusted named graph; exits non-zero if score falls below the profile threshold. No Prefect required. Establishes governance as a first-class operation from day one, before the full lint pass lands in v0.5.0.
- **Competency question CI gate** — golden corpus assertions are generated from the `competency_questions` array in each compiler profile. CI validates not just that triples were written, but that the compiled graph answers what the profile was built to answer.

**Exit criterion:** end-to-end demo on pg_ripple's own `docs/src/**/*.md`:
≥ 80% fragment skip rate on re-ingest, ≥ 95% of facts with valid evidence
spans, full compile cost < $5 with `gpt-4o-mini` or $0 with Ollama.

---

### v0.4.0 — Incremental Compilation

Goal: prove the system rebuilds *only* what changed when a source updates.

- **Artifact dependency graph.** Every compiled artifact records
  `(fragment, profile_version, rule_set)` dependencies in
  `_riverbank.artifact_deps`; queryable in SQL and SPARQL.
- **`riverbank explain <artifact-iri>`** — dumps the dependency tree of any
  compiled artifact: fragments, profile version, rules that contributed.
- **Recompile flow.** Changed fragments → invalidate dependent artifacts →
  re-extract → re-derive → emit semantic diff event via pg-trickle +
  `pgtrickle.attach_outbox()`.
- **Docling integration.** PDF, DOCX, PPTX, HTML, and image OCR via Docling ≥
  2.92. `Docling` becomes the default parser for non-Markdown sources.
- **spaCy NER pre-resolution.** Named entities extracted before the LLM call;
  pre-resolved IRIs passed as structured context to reduce token usage and
  entity-confusion errors.
- **Fuzzy entity matching.** pg_ripple `pg:fuzzy_match()` and
  `pg:token_set_ratio()` (GIN trigram index) for query-time matching;
  `suggest_sameas()` and `pagerank_find_duplicates()` for dedup; RapidFuzz for
  pre-LLM Python-side candidate preparation.
- **Embedding generation.** sentence-transformers produces embeddings for each
  compiled summary. Entity-cluster centroid views are maintained as
  `avg(embedding)::vector` pg_trickle stream tables (pgVector IVM, v0.37+):
  centroid updates incrementally with no full scan on each new fact.
- **Singer-tap connector.** A `singer` connector wraps any Singer tap; ships
  with `tap-github` and `tap-slack-search`. Alternative: pipe any tap directly
  to pg-tide as a Singer target (`tap-github | pg-tide --target singer ...`),
  writing RECORD messages straight to the pg_trickle inbox table.

**Exit criterion:** modify one paragraph in one Markdown file, re-run
`riverbank ingest`, exactly one fragment re-extracted, semantic diff event
arrives on the pg_trickle outbox. `riverbank explain entity:Acme` prints a
complete dependency tree.

---

### v0.5.0 — Quality Gates and Review Loop

Goal: a running human-in-the-loop pipeline that converts low-confidence
extractions into reviewed, high-confidence facts.

- **Label Studio integration.** `LabelStudioReviewer` plugin creates one task
  per review-queue item; pre-labels with LLM extraction; webhook posts
  decisions back; corrections enter `<human-review>` named graph.
  Custom labeling templates: atomic-fact correction, span-based evidence
  annotation, ensemble disagreement arbitration.
- **Active-learning review queue.** `riverbank review queue` runs the
  centrality × uncertainty SPARQL query and refreshes Label Studio task
  priorities — maximum leverage per review hour.
- **Editorial policy example bank.** Each Label Studio decision exports to the
  profile's example bank; next compile run uses these as few-shot examples.
- **SHACL score history.** Daily Prefect flow snapshots `shacl_score()` per
  named graph into Prometheus. **Prefect is introduced here**; the APScheduler
  job from v0.2.0 is replaced.
- **Langfuse evaluations.** Generated Q&A pairs run as Langfuse dataset
  evaluations on every recompile; regressions surface as alerts.
- **Lint flow.** `riverbank lint` runs a full lint pass and writes findings to
  `pgc:LintFinding` triples; Prefect schedules it nightly.

**Exit criterion:** reviewer receives a Label Studio task within 60 seconds of
a low-confidence extraction; correction is reflected in the next SPARQL query;
example bank has ≥ 20 entries after a one-week pilot.

---

### v0.6.0 — Production Hardening

Goal: deployable in a regulated production environment with multi-replica
workers, secret management, backups, and SLOs.

- **Helm chart.** `riverbank/helm/` deploys the worker, Prefect server,
  Langfuse, and Label Studio onto Kubernetes; depends on the existing
  pg_ripple chart.
- **Multi-replica workers.** Fragment-level advisory locks
  (`pg_try_advisory_lock(hashtext(fragment_iri)::bigint)`) + run idempotency
  key (fragment_id + profile_id + content_hash) prevent duplicate work without
  an external coordinator.
- **Prometheus metrics + Perses dashboard.** `/metrics` exposes
  `riverbank_runs_total`, `riverbank_run_duration_seconds`,
  `riverbank_llm_cost_usd_total`, `riverbank_shacl_score`,
  `riverbank_review_queue_depth`. Perses panels ship in `riverbank/perses/`.
- **Secret management.** LLM API keys from environment variables, Kubernetes
  Secrets, or HashiCorp Vault (`hvac`). Keys route through pg-tide's
  `${env:VAR}` / `${file:/path}` secret interpolation for relay credentials;
  no secret is ever logged.
- **Rate limiting + circuit breakers.** Per-provider concurrency limits and a
  circuit breaker (`aiobreaker`) protect against runaway LLM costs during API
  misbehaviour.
- **Audit trail.** Every graph-mutating operation writes to `_riverbank.log`;
  append-only at the database level (`REVOKE UPDATE, DELETE`).
- **Bulk reprocessing.** `riverbank recompile --profile docs-policy-v1
  --version 2` queues all v1 sources for recompilation and produces a semantic
  diff report.
- **OpenTelemetry export.** `OTEL_EXPORTER_OTLP_ENDPOINT` routes traces to any
  collector (Jaeger, Tempo, Honeycomb-OSS).
- **Cost dashboard.** Perses panels: cost per source, cost per profile, cost
  trend, projected monthly spend.

**Load test exit criteria:** three worker replicas process 10,000
fragments/hour; a simulated 1-hour LLM outage triggers the circuit breaker and
recovers without manual intervention; Helm upgrade rolls workers without
dropping in-flight runs.

---

### v0.7.0 — Advanced Epistemic Features

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
  computes the smallest set of facts and rules producing a contradiction using
  a SAT-style minimal-cause algorithm over the inference dependency graph.
- **Coverage maps.** Daily Prefect flow computes per-topic source density,
  mean confidence, and unanswered-question count; results write to
  `pgc:CoverageMap` triples surfaced by `rag_context()`.

**Exit criterion:** an argument graph in Label Studio produces a
`pgc:ArgumentRecord` with claim, two evidence nodes, one objection, and one
rebuttal — all queryable in SPARQL. A test-corpus contradiction produces a
hand-verified minimal explanation. Ensemble compilation with 3 models shows
measurable error reduction over a single-model baseline.

---

### v0.8.0 — Multi-tenant and Prose Generation

Goal: deploy as shared infrastructure across multiple knowledge bases; render
compiled knowledge back to prose.

- **Multi-tenant catalog.** All `_riverbank` tables gain a `tenant_id` column
  with row-level security. Per-tenant editorial policies, profiles, and named
  graphs. Tenant lifecycle API (create, suspend, delete with GDPR erasure).
- **Tenant-scoped Label Studio.** One Label Studio organisation per tenant;
  reviewer assignments respect tenant boundaries.
- **Federated compilation.** A "remote profile" type pulls SERVICE-federated
  triples from a peer pg_ripple instance into a local compilation context,
  applies confidence weighting, and writes the result locally.
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
v0.4.0  ─── Incremental compilation: dependency graph, explain, Docling, embeddings,
    │        spaCy NER, Singer/pg-tide connector, semantic diff events
    │
v0.5.0  ─── Quality gates: Label Studio review loop, active-learning queue,
    │        example bank, Langfuse evals, lint flow, Prefect introduced
    │
v0.6.0  ─── Production hardening: Helm chart, multi-replica workers, Prometheus,
    │        Perses dashboards, audit trail, secret management, circuit breakers
    │
v0.7.0  ─── Advanced epistemic: negative knowledge, argument graphs, assumptions,
    │        9 epistemic statuses, model ensemble, contradiction explanation
    │
v0.8.0  ─── Multi-tenant + rendering: RLS, federated compilation, Markdown/JSON-LD
    │        page rendering, streaming SSE render for live documentation
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
also adds the full multi-format parser (Docling) and the embedding infrastructure
that v0.5.0 and later depend on.

v0.5.0 closes the human-in-the-loop gap. A knowledge graph without a review
loop is a confidence claim without evidence. Label Studio integration, the
active-learning review queue, and the example bank together enable the quality
feedback cycle that makes extraction quality measurably improve over time.
Prefect is introduced here rather than earlier because it is an operational
dependency (it needs the pipeline to be stable before it adds value).

v0.6.0 is the production gate. Nothing before v0.6.0 is appropriate for
a regulated production environment. The Helm chart, multi-replica workers,
audit trail, and secret management form the minimum deployable production unit.
This release is deliberately large; every item in it is non-negotiable for
production readiness.

v0.7.0 addresses the epistemic features that distinguish riverbank from a
generic RAG pipeline. Negative knowledge (explicit absences), argument graphs
(structured reasoning), and model ensemble (verification by disagreement) are
all features that generic pipelines do not provide. These are deferred to v0.7.0
because they require a working review loop (v0.5.0) and stable production
infrastructure (v0.6.0) to be useful in practice.

v0.8.0 is additive infrastructure: multi-tenancy and rendering. Both can be
developed in parallel with v0.7.0 work. Multi-tenancy is straightforward once
the catalog schema is stable (RLS + `tenant_id` on existing tables). Rendering
is the last mile between a compiled knowledge graph and a documentation site
that humans can read without a SPARQL client.

v1.0.0 completes the API stability contract. The goal is not to add features at
1.0 but to guarantee that v0.x adopters can upgrade to v1.0 without breaking
changes, with a PyPI package, signed artifacts, and SLOs that an operations team
can reference in a service-level agreement.
