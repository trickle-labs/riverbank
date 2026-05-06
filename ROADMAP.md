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
| v0.8.0 | Epistemic layer — negative knowledge records, argument graphs, assumption registry, all 9 epistemic status labels, model ensemble, contradiction explanation, coverage maps | **Done** | Very Large |

### Multi-tenant and Prose Generation (v0.9.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.9.0 | Multi-tenant and rendering — tenant_id RLS activation, federated compilation (SPARQL SERVICE), Markdown/JSON-LD page rendering, streaming render via SSE | **Done** | Very Large |

### Release Infrastructure (v0.10.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.10.0 | Release infrastructure — PyPI package, `riverbank sbom` command, documentation site auto-publish on every release | **Done** | Medium |

### Extraction Quality (v0.11.x – v0.13.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.11.0 | Preprocessing & post-processing — LLM document preprocessing, corpus-level clustering, few-shot injection, validate-graph, entity deduplication, self-critique verification | **Done** | Large |
| v0.11.1 | Token efficiency — per-fragment entity catalog filtering, adaptive preprocessing for small documents, Phase 2 pre-scan deduplication, Ollama keep-alive prompt caching, noise section filtering | **Done** | Small |
| v0.12.0 | Permissive extraction (Phase A) — ontology-grounded & CQ-guided prompts, permissive extraction prompt, per-triple confidence routing, `graph/tentative`, two-tier query model, safety cap, pre-write structural filtering, overlapping fragments, literal normalization | **Done** | Large |
| v0.12.1 | Permissive extraction (Phase B) — confidence consolidation (noisy-OR) with source diversity scoring, `riverbank promote-tentative`, functional predicate hints, `riverbank explain-rejections` | Planned | Medium |
| v0.13.0 | Entity convergence — predicate normalization, incremental entity linking with synonym ring extraction, `riverbank induce-schema`, contradiction detection, tentative cleanup, quality regression tracking | Planned | Large |
| v0.13.1 | Extraction feedback loops — auto few-shot expansion, semantic few-shot selection, batched verification, knowledge-prefix adapter | Planned | Medium |

### Structural Improvements & Stable Release (v0.14.x – v1.0.0)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.14.0 | Structural improvements — constrained decoding, semantic chunking, SHACL shape validation, SPARQL CONSTRUCT rules, OWL 2 RL inference | Planned | Large |
| v1.0.0 | Stable — full API stability guarantee, signed artifacts, Helm chart stability, SLOs in CI | Planned | Medium |

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
| `owlrl` (OWL 2 RL reasoner) | PyPI | v0.14.0 | OWL inference deferred; SPARQL CONSTRUCT rules still ship and cover most derivations |
| `pyshacl` (SHACL validation) | PyPI | v0.14.0 | SHACL shape validation deferred; ontology-grounded predicate allowlist still enforces structural constraints |

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

- [x] **Negative knowledge.** `pgc:NegativeKnowledge` records for explicit denials,
  exhaustive search failures, and superseded facts. Compiler profiles can
  declare "search-and-record-absence" rules per predicate.
- [x] **Argument graphs.** `pgc:ArgumentRecord` extractor with a Label Studio
  annotation template for `{claim, evidence, objection, rebuttal}` spans. SPARQL
  navigation: "which policy conclusions have a recorded objection but no
  rebuttal?"
- [x] **Assumption registry.** Extracted assumptions attached as RDF-star
  annotations to facts and entity pages; surfaced by `rag_context()` alongside
  answers.
- [x] **Epistemic status layer.** Every fact gets a `pgc:epistemicStatus`
  annotation from the full set: `observed`, `extracted`, `inferred`,
  `verified`, `deprecated`, `normative`, `predicted`, `disputed`,
  `speculative`. Status flows from compiler outcome, Datalog inference, and
  Label Studio decisions.
- [x] **Model ensemble compilation.** Per-profile opt-in; runs N model variants
  and routes disagreements to Label Studio with a side-by-side template. Hard
  cost cap configurable per profile.
- [x] **Minimal contradiction explanation.** `riverbank explain-conflict <iri>`
  is a CLI wrapper around `pg_ripple.explain_contradiction()` — the
  minimal-cause reasoning engine (SAT-style hitting-set over the inference
  dependency graph) lives in pg-ripple and requires no Python implementation
  in riverbank.
- [x] **Coverage maps.** `pg_ripple.refresh_coverage_map()` computes per-topic
  source density, mean confidence, contradiction count, and recency into the
  `<coverage>` named graph. A Prefect flow joins the result against
  `_riverbank.profiles.competency_questions` to compute the unanswered-question
  count (the one join that requires riverbank's catalog), then writes enriched
  `pgc:CoverageMap` triples surfaced by `rag_context()`.
- [x] **Procedural knowledge compiler profile.** A built-in profile template
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

- [x] **Multi-tenant RLS activation.** Row-level security is enabled on all
  `_riverbank` tables using the `tenant_id` column scaffolded in v0.4.0.
  Per-tenant editorial policies, profiles, and named graphs. Tenant lifecycle
  API (create, suspend, delete with GDPR erasure).
- [x] **Tenant-scoped Label Studio.** One Label Studio organisation per tenant;
  reviewer assignments respect tenant boundaries.
- [x] **Federated compilation.** A "remote profile" type pulls SERVICE-federated
  triples from a peer pg_ripple instance into a local compilation context,
  applies confidence weighting, and writes the result locally. The SPARQL
  `SERVICE` keyword is implemented in pg-ripple's query engine; riverbank
  configures a `federation_endpoints` entry via SQL and issues a standard
  SPARQL query — no federation protocol code lives in riverbank.
- [x] **Markdown / JSON-LD page rendering.** `riverbank render` generates entity
  pages, topic surveys, comparison tables, and change digests from compiled
  artifacts. Output formats: Markdown (Obsidian/MkDocs), JSON-LD, HTML.
- [x] **Render scheduling.** Pages stored as `pgc:RenderedPage` artifacts with
  dependency edges to their source facts. When facts change, pages are flagged
  stale and regenerated in the next render flow.
- [x] **Streaming render.** SSE endpoint emits page updates as the underlying graph
  changes, for live documentation sites.

**Exit criteria:** two tenants compile independently on shared PostgreSQL with
no data leakage (verified by RLS tests); `riverbank render --format markdown
--target docs/` produces a navigable MkDocs site with citations linking back to
source fragments; modifying one fact regenerates exactly the pages that depend
on it.

---

### v0.10.0 — Release Infrastructure

Goal: make riverbank self-installable from PyPI, ship a machine-readable SBOM,
and automate the documentation site — so that adopters can onboard without
cloning the repository.

- [x] **PyPI package.** `pip install riverbank` installs the worker and CLI.
  Optional extras: `[ollama]`, `[docling]`, `[labelstudio]`. `pyproject.toml`
  build metadata, `MANIFEST.in`, and a GitHub Actions release workflow that
  publishes to PyPI on every version tag.
- [x] **`riverbank sbom`** — new CLI command that generates a CycloneDX SBOM for
  the installed package using `cyclonedx-python`. Output formats: JSON (default)
  and XML. Exits non-zero if any dependency has a known CVE (via `pip-audit`
  integration). Designed for supply-chain compliance workflows.
- [x] **Documentation site auto-publish.** The existing `riverbank render` capability
  is wired to a release workflow: on each tag, `riverbank render --format markdown
  --target docs/` generates the MkDocs site from the pg_ripple docs corpus and
  publishes it to GitHub Pages. No new rendering logic — purely CI plumbing.

**Exit criterion:** `pip install riverbank` on a clean machine runs
`riverbank health` successfully; `riverbank sbom` produces a valid CycloneDX
JSON file; the documentation site updates automatically on the next version tag.

---

### v0.11.0 — Preprocessing & Post-Processing

Goal: enrich extraction with document-level and corpus-level context, and add
post-extraction quality passes that clean and verify the compiled graph.

- [x] **LLM document preprocessing (Phase 1).** `DocumentPreprocessor` generates
  a structured summary and entity catalog per document before extraction. The
  catalog (label, type, aliases) is injected into the extraction prompt via
  `build_extraction_prompt()`, giving the LLM entity-aware context. Token counts
  tracked separately (`preprocessing_prompt_tokens`, `preprocessing_completion_tokens`).
- [x] **Corpus-level clustering (Phase 2).** `CorpusPreprocessor` embeds document
  summaries via sentence-transformers, clusters with K-Means, and generates
  per-cluster and corpus-wide summaries. `CorpusAnalysis` (cluster map, entity
  vocabulary, predicate vocabulary) is prepended to extraction prompts via
  `build_context()`, providing cross-document awareness.
- [x] **Few-shot injection.** `FewShotInjector` loads golden examples from YAML
  files in `examples/golden/` and prepends them to the extraction prompt.
  Configurable per profile via the `few_shot` block.
- [x] **`riverbank validate-graph`.** Evaluates competency-question coverage
  against the compiled graph via SPARQL ASK queries. Exits non-zero if
  coverage falls below the profile threshold.
- [x] **Entity deduplication (Post-1).** `EntityDeduplicator` embeds entity IRI
  labels via sentence-transformers, clusters by cosine similarity (default
  threshold 0.92), promotes the shortest IRI as canonical, and writes
  `owl:sameAs` links for aliases.
  CLI: `riverbank deduplicate-entities --graph --threshold --dry-run`.
- [x] **Self-critique verification (Post-2).** `VerificationPass` issues a second
  LLM call per low-confidence triple. Confirmed triples receive a confidence
  boost; rejected triples are quarantined to `<draft>`. Configurable via
  the `verification` block in the compiler profile.
  CLI: `riverbank verify-triples --profile --graph --dry-run`.

**Exit criterion:** a 3-document corpus ingested with Phase 1 + Phase 2
preprocessing shows measurably higher CQ coverage than without. Entity
deduplication reduces unique IRI count by ≥ 15%. Verification pass quarantines
at least one low-confidence triple in a test run.

---

### v0.11.1 — Token Efficiency

Goal: offset the token cost increase from v0.12.0's permissive extraction
features before they ship. The four items below deliver a **32% token
reduction** from the v0.11.0 baseline in ≤ 1 day of implementation, ensuring
the net impact of v0.12.0 stays within 20% of today's token baseline.

- [ ] **Per-fragment entity catalog filtering.** Before injecting the entity
  catalog into an extraction prompt, filter it to only include entries whose
  `label` or `aliases` appear in the fragment text. A `min_entities_to_inject`
  floor (default 3) ensures the LLM always has some context even for fragments
  that don't surface entity names explicitly. Saves ~300–400 input tokens per
  fragment (50 entities → ~10 relevant). Controlled by
  `token_optimization.filter_entities_by_mention: true` in the profile.
- [ ] **Adaptive preprocessing skip for small documents.** Skip Phase 1
  preprocessing entirely for single-fragment documents shorter than
  `skip_preprocessing_below_chars: 2000`. For these documents the fragment IS
  the document — there is no inter-fragment terminology drift to resolve.
  Eliminates 2 LLM calls (~2 500 tokens) per small document.
- [ ] **Deduplicate Phase 2 pre-scan.** Cache the Phase 1 document summary so
  the Phase 2 corpus pre-scan does not recompute summaries that Phase 1 will
  compute anyway. Pass summaries from Phase 1 to the Phase 2 analyser via a
  shared `{source_iri: summary}` dict. Saves N × ~2 000 tokens —
  **20 000 tokens for a 10-document corpus** — at zero quality cost.
- [ ] **Ollama keep-alive prompt caching.** Set `keep_alive: "5m"` on all
  Ollama calls so the model KV cache persists across the fragments of an ingest
  run. The static system prompt (~200 tokens) is re-processed only once per
  run instead of once per fragment. For cloud providers (OpenAI / Anthropic)
  prompt caching is already active automatically.
- [ ] **Noise section filtering.** Wire up the `noise_sections` field in
  `PreprocessingResult` (the data model already exists but is never populated).
  Add an LLM call in `DocumentPreprocessor.preprocess()` that asks:
  "Identify headings that are pure boilerplate and carry no domain facts
  (navigation, disclaimers, change logs, legal notices). Return a JSON array
  of heading paths." Fragments whose heading path matches a noise section are
  skipped before extraction entirely. Saves one full LLM extraction call per
  boilerplate fragment. Controlled by `preprocessing.noise_filtering: true`.

**Exit criterion:** a 10-document corpus ingested with all v0.11.0 features
enabled uses ≤ 100 000 total tokens (down from ~144 600 baseline). Phase 2
pre-scan produces zero duplicate LLM summary calls. Small documents
(< 2 000 chars) are processed without any preprocessing LLM calls. At least
one corpus document has boilerplate sections correctly identified and skipped.

---

### v0.12.0 — Permissive Extraction

Goal: dramatically increase triple yield — especially for small corpora — by
extracting broadly within ontology-bounded constraints and routing per-triple by
confidence. For small corpora (< 20 documents), the primary win is immediate:
higher single-pass recall from the permissive prompt, not deferred accumulation.
Ontology grounding and permissive extraction are **codependent** and must ship
together — permissive extraction without vocabulary constraints floods the
tentative graph with hallucinated predicates; ontology grounding without
permissive extraction still skips implied facts.

- [x] **Ontology-grounded extraction.** `allowed_predicates` and
  `allowed_classes` fields in the compiler profile YAML. Injected into the
  extraction prompt as a closed-world constraint: "use ONLY these predicates;
  if a relationship does not fit, SKIP it." Triples with non-conforming
  predicates are rejected before writing (`triple_rejected_ontology` stat).
  Required companion to permissive extraction — prevents vocabulary explosion.
- [x] **CQ-guided extraction.** Competency questions from the profile are
  transformed into "EXTRACTION OBJECTIVES" and prepended to the extraction
  prompt, making extraction goal-directed rather than exhaustive. CQs also
  drive auto few-shot expansion (v0.13.0) and benchmark evaluation (v0.13.0),
  so this is the first step in making CQs a first-class quality driver.
- [x] **Permissive extraction prompt.** New `extraction_strategy.mode: permissive`
  option replaces the conservative "only extract claims directly supported by
  the text" instruction with a tiered guidance: EXPLICIT (0.9–1.0), STRONG
  (0.7–0.9), IMPLIED (0.5–0.7), WEAK (0.35–0.5). The four tiers correct the
  LLM's systematic mis-calibration — it over-scores hallucinations and
  under-scores true implied facts. Confidence at extraction time is treated
  as a routing signal, not a truth probability.
- [x] **Per-triple confidence routing.** Replace batch-level SHACL routing with
  per-triple confidence routing: ≥ 0.75 → trusted graph, 0.35–0.75 →
  `graph/tentative`, < 0.35 → discarded. New `tentative_graph` field in
  `CompilerProfile`. This is Phase A — independently shippable, delivering the
  full single-pass recall improvement without requiring Phase B (accumulation).
- [x] **Pre-write structural filtering.** Reuse the ontology allowlist as a fast
  write-time filter: before any triple enters the tentative graph, check that
  the predicate is in `allowed_predicates` and that subject/object types match
  declared domain/range (if specified). Zero graph queries, microsecond latency.
  Prevents structurally invalid triples from entering the tentative graph and
  polluting noisy-OR calculations.
- [x] **Extraction safety cap.** `max_triples_per_fragment: 50` in the
  `extraction_strategy` profile block. If the LLM produces more, keep the top-N
  by confidence and log a `triples_capped` warning. Prevents runaway token usage
  on dense documents with permissive extraction. Track `triples_capped` in stats.
- [x] **Two-tier query model.** `riverbank query` (default): trusted graph only
  — strict, fast, conservative. `riverbank query --include-tentative`: unions
  trusted + tentative graphs, results ordered by confidence descending —
  discovery-focused. Documented as a first-class CLI feature pair, not an
  implementation detail.
- [x] **Rejected triple analysis.** `riverbank explain-rejections --profile
  --since 1h` shows triples discarded in the last run: evidence span not found,
  below noise floor, or ontology mismatch. Feeds back into prompt improvement
  and surfaces which implied facts the conservative prompt was silently losing.
- [x] **Coreference resolution.** Before fragmentation, run a lightweight
  coreference resolution pass on the full document text to replace pronouns
  and anaphoric references with their resolved entity names: "it" →
  "the Pipeline", "this component" → "the Dataset Writer". Two modes
  controlled by `preprocessing.coreference: llm | spacy | disabled`:
  (a) LLM call with prompt "Replace all pronouns and anaphoric references
  in the following text with the entity they refer to. Return the full
  resolved text."; (b) spaCy `neuralcoref` or `coreferee` model (no extra
  LLM call). Only high-confidence resolutions applied — ambiguous pronouns
  left unchanged. Fragment-boundary coreference breaks are the primary reason
  procedural corpora produce phantom entities like `ex:_it`. Significant yield
  improvement on procedure, runbook, and tutorial corpora.
- [x] **Overlapping fragment windows.** `overlap_sentences` config in the
  fragmenter block prepends the last N sentences of the previous fragment to
  recover facts split across boundaries. Duplicate triples from overlap regions
  deduplicated by content hash.
- [x] **Literal normalization.** Normalize string literals (lowercase + trim),
  dates (ISO 8601 canonical form), and IRIs before writing. Deduplicate on
  normalized form; keep the highest-confidence instance.
- [x] **Compact output schema.** Replace verbose `_TripleIn` JSON field names
  with short keys (`s`, `p`, `o`, `c`, `e`, `cs`, `ce`) to save ~20 output
  tokens per triple. Mapped back to full field names in `ExtractionResult`.
  Saves ~300 output tokens per fragment (15 triples × 20 tokens), partially
  offsetting the input token increase from ontology and CQ injection.
  Controlled by `token_optimization.compact_output_schema: true` in profile.
- [x] **Token budget manager.** `max_input_tokens_per_fragment: 3000` in the
  `token_optimization` profile block. When the assembled prompt (system +
  entity catalog + few-shot + corpus context + fragment) exceeds the budget,
  components are trimmed in priority order: few-shot → corpus context → entity
  catalog → doc summary. Fragment text is never truncated. Uses byte-length
  approximation (`÷ 4`) for Ollama where tiktoken is unavailable. Mandatory
  companion to v0.13.0's knowledge-prefix adapter, which adds +100–300 tokens
  per fragment.
- [x] **Merged preprocessing for short documents.** For documents below
  `merge_preprocessing_below_chars: 4000`, combine the document summary and
  entity catalog into a single LLM call. Halves preprocessing LLM calls for
  short documents and saves ~2 000 input tokens per document.
- [x] **Extraction stats.** Track `triples_trusted`, `triples_tentative`,
  `triples_discarded`, `triples_rejected_ontology`, `triples_capped`.

**Exit criterion:** the 3-document example corpus produces ≥ 2x more triples
than v0.11.0 (trusted + tentative combined). CQ coverage with
`--include-tentative` exceeds 75%. Safety cap prevents any single fragment from
producing more than 50 triples. Total prompt tokens per ingest run do not
exceed the v0.11.0 baseline by more than 20% when `token_optimization` is
enabled (the permissive prompt additions are offset by compact schema,
budget trimming, and the v0.11.1 quick wins).

---

### v0.12.1 — Permissive Extraction Phase B

Goal: complete the tentative graph lifecycle by adding evidence accumulation,
explicit promotion, and the tooling to understand what the pipeline discards.

- [ ] **Confidence consolidation (noisy-OR).** When a triple `(s, p, o)` is
  extracted from multiple fragments, consolidate confidence via
  $c_{final} = 1 - \prod_i (1 - c_i)$. Multi-provenance evidence spans stored
  per triple. Source diversity scoring: corroboration from multiple fragments
  of the same document counts as one vote (prevents correlated hallucination
  promotion from templated or copied documents).
- [ ] **`riverbank promote-tentative`.** Explicit CLI command — promotion is never
  automatic. Requires `--dry-run` review before committing. Promotes tentative
  triples whose consolidated confidence crosses the trusted threshold. Writes
  `pgc:PromotionEvent` provenance records. Track `triples_promoted` in stats.
- [ ] **Functional predicate hints in profile YAML.** Annotate predicates as
  functional (`max_cardinality: 1`) in the `predicate_constraints` block.
  Used in two ways: the extraction prompt says "pick the most specific value
  only" for functional predicates; contradiction detection in v0.13.0 uses the
  annotations to detect `(s, p, o₁)` vs `(s, p, o₂)` conflicts.
- [ ] **`riverbank explain-rejections`.** `--profile --since 1h` shows triples
  discarded in the last run, grouped by reason: evidence span not found,
  below noise floor, ontology mismatch, safety cap. Feeds back into prompt
  improvement and surfaces which implied facts the conservative prompt was
  silently losing.
- [ ] **`triples_promoted` stat.** Track in run stats alongside `triples_trusted`,
  `triples_tentative`, `triples_demoted`.

**Exit criterion:** `promote-tentative` successfully promotes at least one triple
after a second ingest pass. `riverbank explain-rejections` shows at least 5
correctly implied triples that Phase A discarded. Source diversity scoring
prevents a triple corroborated only by fragments of the same document from
crossing the promotion threshold.

---

### v0.13.0 — Entity Convergence

Goal: make the entity and predicate vocabularies converge and stabilise, close
the cold-start problem via schema induction, and complete the tentative graph
lifecycle with contradiction detection and automatic cleanup. These are the
critical correctness foundations — without stable vocabularies, the extraction
feedback loops planned for v0.13.1 learn from noisy data.

- [ ] **Predicate normalization.** Embed predicate labels, cluster by similarity,
  map non-canonical predicates to ontology-defined canonical forms. Companion
  to entity deduplication — reduces predicate vocabulary by 30–50%.
- [ ] **Incremental entity linking with synonym rings.** Persistent
  `entity_registry` table (IRI, label, type, embedding, first_seen, doc_count)
  grows as documents are processed. Before extraction, top-K relevant entities
  are injected as "KNOWN ENTITIES — prefer these IRIs." New CLI:
  `riverbank entities list` and `riverbank entities merge`.
  The vocabulary pass now explicitly produces `skos:altLabel` triples for every
  discovered variant (synonym rings, per ANSI Z39.19): "Dataset" / "data set" /
  "datasets" → one entity with three alt-labels. The `pg:fuzzy_match()` function
  validates synonymy before writing. Synonym rings improve query recall and
  anchor the entity linker to attested surface forms rather than canonical-only
  matching.
- [ ] **Contradiction detection & demotion.** For functional predicates annotated
  in the profile YAML (from v0.12.0), detect when new `(s, p, o₂)` conflicts
  with existing `(s, p, o₁)`. Reduce confidence of both triples by 30%; demote
  below threshold. Create `pgc:ConflictRecord`. Works as an identity
  verification layer: triples that survive contradiction detection are
  demonstrably more trustworthy.
- [ ] **`riverbank induce-schema`.** Cold-start onboarding: after an initial
  unconstrained extraction pass, collect all unique predicates and entity types
  from the graph, compute frequency statistics, and ask the LLM to propose a
  minimal OWL ontology (class hierarchy, domain/range, cardinality constraints).
  Present for human review before writing to `ontology/`. A second extraction
  pass with the induced ontology as constraints produces 2x better precision.
  Removes the adoption bottleneck: users no longer need ontology expertise to
  get quality results.
- [ ] **Automatic tentative cleanup.** Track `first_seen` timestamp for tentative
  triples. Auto-run after each ingest: archive tentative triples that were
  never promoted and have not been corroborated within the configurable TTL
  (default 30 days). `riverbank gc-tentative --older-than 30d` available
  for manual invocation; `tentative_ttl_days` in profile YAML to configure.
  Without automatic cleanup, the tentative graph grows indefinitely and
  becomes noise.
- [ ] **Quality regression tracking.** `riverbank benchmark --profile <name>
  --golden tests/golden/<name>/ --fail-below-f1 0.85` re-extracts the golden
  corpus and compares against ground truth (precision, recall, F1). Runs in
  CI on every release; fails the build if quality drops.

**Exit criterion:** entity duplication rate across a 10-document corpus is
< 1.15x. Synonym ring extraction produces `skos:altLabel` triples for ≥ 80%
of entities that have attested surface variants. Contradiction detection flags
at least one functional predicate conflict in a test run. Tentative cleanup
auto-runs and archives stale triples without manual intervention.
`riverbank benchmark` CI step catches a deliberately degraded prompt.

---

### v0.13.1 — Extraction Feedback Loops

Goal: close the self-improvement loop — the pipeline learns from its own
high-confidence outputs to improve future extractions. Depends on stable
vocabularies from v0.13.0; without them, feedback loops learn from noisy data.

- [ ] **Auto few-shot expansion.** After validated ingests where CQ coverage
  exceeds threshold, high-confidence triples that satisfy competency questions
  are automatically sampled and appended to the profile's golden examples file.
  Capped at 10–15 examples per profile with diversity constraints (no two
  examples with the same predicate+type combination). CQs drive selection,
  completing the CQ-as-north-star feedback cycle begun in v0.12.0.
- [ ] **Semantic few-shot selection.** Upgrade `FewShotInjector` to support
  `selection: semantic`. Embeds the fragment text and the golden examples at
  injection time and selects the top-K most similar examples by cosine
  similarity. Reduces injected examples from 3 to 1–2 highly relevant ones —
  saves ~80–150 tokens per fragment while anchoring the LLM to the most
  topically relevant examples. Falls back to random when sentence-transformers
  is unavailable.
- [ ] **Batched verification.** Upgrade `VerificationPass` to group
  low-confidence triples into batches of up to `verification.batch_size: 5`
  per LLM call instead of one call per triple. Saves ~3 400 tokens for a
  typical 20-triple verification run.
- [ ] **Knowledge-prefix adapter.** At extraction time, retrieve the local
  neighborhood of already-extracted entities from pg_ripple and inject as a
  structured "KNOWN GRAPH CONTEXT" prefix. Improves consistency of new
  extractions with the existing graph and reduces contradictory triples.
  Requires the v0.12.0 token budget manager — the graph context block is
  capped at `max_graph_context_tokens: 200` (default) to prevent prompt
  explosion.

**Exit criterion:** auto-expanded few-shot bank has ≥ 8 examples after two
full ingest cycles. Semantic few-shot selection demonstrably selects more
relevant examples than random (measured by extraction precision on held-out
corpus). Batched verification issues ≤ 4 LLM calls for a 20-triple
verification run (instead of 20). Knowledge-prefix adapter improves
entity IRI consistency across documents.

---

### v0.14.0 — Structural Improvements & Reasoning

Goal: improve fragment quality, add deductive reasoning, and support
grammar-constrained output for local models.

- [ ] **Constrained decoding.** For Ollama backends, use grammar-constrained
  decoding via the `format` parameter to force JSON schema conformance at
  decode time. Eliminates 100% of JSON parsing failures for local models.
- [ ] **Semantic chunking.** Embedding-based boundary detection: embed each
  sentence, split where cosine similarity drops below a threshold (topic
  transition). Fragments align with semantic units rather than fixed-size
  or heading-based boundaries.
- [ ] **SHACL shape validation.** Define a `pgc-shapes.ttl` shapes graph
  alongside the ontology. After ingest, validate the named graph via pyshacl.
  Report violations as diagnostics; optionally reduce confidence of violating
  triples. CLI: `riverbank validate-shapes --graph --shapes`.
- [ ] **SPARQL CONSTRUCT rules.** Profile-specific inference rules defined as
  SPARQL CONSTRUCT queries. Run after ingest, writing results to
  `graph/inferred`. Transparent, auditable, domain-specific reasoning.
- [ ] **OWL 2 RL forward-chaining.** Lightweight deductive closure via owlrl:
  `owl:inverseOf`, `rdfs:subClassOf` transitivity, domain/range type
  assertions, `owl:TransitiveProperty`. Results written to `graph/inferred`
  — never contaminates the asserted evidence base.
**Exit criterion:** constrained decoding eliminates JSON parse errors in
Ollama CI tests. Semantic chunking produces fewer orphan triples than
heading-based fragmentation on a test corpus. OWL 2 RL closure at least
doubles queryable type assertions.

---

### v1.0.0 — Stable Release

Goal: full API stability guarantee; production SLOs that an operations team
can reference in a service-level agreement.

- API stability: all public Python APIs, CLI commands, and SPARQL vocabulary
  (`pgc:` ontology) follow semantic versioning; no breaking changes without a
  major version bump.
- Signed release artifacts: release wheel and sdist signed with Sigstore
  (`cosign`); signatures published to the Rekor transparency log.
- Helm chart stability: `helm install riverbank riverbank/riverbank` works
  on any Kubernetes 1.28+ cluster with the pg_ripple chart as a dependency;
  chart version follows the same semver contract as the Python package.
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
v0.10.0 ─── Release infrastructure: PyPI package, riverbank sbom, docs auto-publish
    │
v0.11.0 ─── Preprocessing & post-processing: document preprocessing, corpus
    │        clustering, few-shot injection, entity dedup, self-critique verification
    │
v0.11.1 ─── Token efficiency: entity catalog filtering, adaptive preprocessing,
    │        Phase 2 pre-scan dedup, Ollama keep-alive caching
    │
v0.12.0 ─── Permissive extraction Phase A: ontology-grounded prompts, per-triple
    │        routing, graph/tentative, safety cap, pre-write filtering, overlapping
    │        fragments, literal normalization
    │
v0.12.1 ─── Permissive extraction Phase B: noisy-OR accumulation, source diversity
    │        scoring, promote-tentative, functional predicate hints, explain-rejections
    │
v0.13.0 ─── Entity convergence: predicate normalization, entity linking + synonym
    │        rings, induce-schema, contradiction detection, tentative cleanup,
    │        quality benchmarks
    │
v0.13.1 ─── Extraction feedback loops: auto few-shot expansion, semantic few-shot,
    │        batched verification, knowledge-prefix adapter
    │
v0.14.0 ─── Structural improvements: constrained decoding, semantic chunking,
    │        SHACL shapes, SPARQL CONSTRUCT rules, OWL 2 RL inference
    │
v1.0.0  ─── Stable: API stability guarantee, signed artifacts, Helm stability, SLOs in CI
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

v0.10.0 is release infrastructure. `riverbank render` already exists; wiring it
to a CI publish step is straightforward. The PyPI package and SBOM command are
self-contained packaging work that does not touch the core pipeline. Separating
this from the stability declaration keeps v1.0.0 focused on the policy commitment
rather than implementation.

v0.11.0 captures the preprocessing and post-processing work done since v0.10.0:
document-level and corpus-level LLM preprocessing that gives extraction prompts
entity-aware context, few-shot injection from golden examples, entity
deduplication via embedding similarity, and self-critique verification that
quarantines low-confidence hallucinations. These are foundational capabilities
that all subsequent quality work builds on.

v0.12.0 is the extraction quality turning point. Two insights from the research
underpinning this release: first, LLM confidence scores are not probabilities
— they reflect how "explicitly stated" something sounds, not how likely it is
to be true. Models systematically over-score hallucinations and under-score
true implied facts. The four-tier extraction prompt (EXPLICIT/STRONG/IMPLIED/WEAK)
corrects this by treating confidence as a routing signal rather than a truth
claim. Second, permissive extraction and ontology grounding are codependent:
permissive extraction without vocabulary constraints floods the tentative graph
with noise; ontology constraints without permissive extraction still silently
discards implied facts. They must ship together. For small corpora, the benefit
is immediate — Phase A (permissive prompt + per-triple routing) alone delivers
higher single-pass recall before any accumulation mechanism is in place.

v0.13.0 makes the entity vocabulary self-improving. Incremental entity linking
ensures that document N knows about entities discovered in documents 1 through
N−1. Auto few-shot expansion means the system organically builds its own
training examples from high-quality extractions. The knowledge-prefix adapter
closes the feedback loop by injecting the existing graph neighborhood into
extraction prompts, so the LLM sees what's already been asserted.

v0.14.0 addresses structural quality: better fragment boundaries (semantic
chunking), deductive reasoning (OWL 2 RL, SPARQL CONSTRUCT), and output
reliability for local models (constrained decoding). These are medium-complexity
improvements that deliver the most value once the extraction pipeline itself is
producing high-quality triples.

v1.0.0 completes the API stability contract. The goal is not to add features at
1.0 but to guarantee that v0.x adopters can upgrade to v1.0 without breaking
changes, with signed artifacts and SLOs that an operations team can reference
in a service-level agreement.
