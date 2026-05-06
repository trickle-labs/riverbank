# Changelog

All notable changes to riverbank, organized by release.

## v0.9.0 — Multi-tenant and prose generation

- Multi-tenant lifecycle: `riverbank tenant create/suspend/delete/list/activate-rls`
- Row-Level Security (RLS) on all `_riverbank` catalog tables
- GDPR erasure via `--gdpr` flag (cascading provenance-graph deletion)
- Federated compilation: `riverbank federation register/compile`
- Rendering engine: `riverbank render` (Markdown, JSON-LD, HTML)
- `pgc:RenderedPage` artifacts with dependency tracking
- Tenant-scoped named graph prefixes

## v0.8.0 — Epistemic layer

- Negative knowledge (`pgc:NegativeKnowledge`) with absence rules in profiles
- Argument graphs (`pgc:ArgumentRecord` with claim, evidence, objection, rebuttal)
- Assumption registry (`pgc:AssumptionRecord`)
- Full epistemic status layer (all 9 values)
- Model ensemble compilation (`weighted_merge`, `majority_vote`)
- `riverbank explain-conflict` command
- Coverage maps (`pgc:CoverageMap`)
- `procedural-v1` compiler profile

## v0.7.0 — Production hardening

- Helm chart (`helm/riverbank/`)
- Multi-replica advisory locking (fragment-level, no duplicate work)
- Circuit breakers per LLM provider (via `aiobreaker`)
- Prometheus metrics endpoint (`/metrics`)
- HashiCorp Vault secret management (via `hvac`)
- Kubernetes health probes
- Pod annotations for Prometheus scraping
- ServiceMonitor for operator-based scraping

## v0.6.0 — Quality gates and review

- Label Studio integration (`riverbank review queue/collect`)
- Active-learning review queue (centrality × uncertainty ranking)
- Example bank: review decisions become few-shot examples
- Langfuse evaluation integration
- Full lint pass: SHACL + SKOS integrity + `pgc:LintFinding` triples
- Nightly lint Prefect flow
- SHACL score history tracking
- OpenTelemetry tracing setup

## v0.5.0 — Multi-format and vocabulary

- Docling parser (PDF, DOCX, HTML)
- SKOS vocabulary pass (`--mode vocabulary`)
- `pg:skos-integrity` shape bundle
- Thesaurus-aware query expansion (`--expand`)
- `owl:sameAs` fuzzy match suggestions in `riverbank explain`
- `run_mode_sequence` field in profiles
- Named entity recognition (NER) for entity linking

## v0.4.0 — Incremental compilation

- Artifact dependency graph (`_riverbank.artifact_deps`)
- `riverbank explain` command
- `riverbank recompile` command (bulk reprocessing)
- Semantic diff events via pg-trickle
- Audit trail (`_riverbank.audit_log`)
- Tenant ID column scaffolding (pre-RLS)
- Filesystem connector plugin

## v0.3.0 — MVP completion

- `riverbank query` — SPARQL SELECT/ASK execution
- `riverbank runs` — run inspection with Langfuse deep-links
- `riverbank lint --shacl-only` — SHACL quality gate
- Cost accounting (prompt tokens, completion tokens, USD estimate)
- Competency questions in profiles (CI gate)
- Golden corpus test suite

## v0.2.0 — Core ingestion

- Markdown parser
- Heading fragmenter
- NoOp extractor (CI/testing)
- Instructor extractor (real LLM extraction)
- Editorial policy gate
- Hash-based fragment deduplication (`xxh3_128`)
- SHACL validation (trusted vs. draft routing)
- PROV-O provenance edges
- `riverbank ingest` command
- `riverbank profile register` and `riverbank source set-profile`

## v0.1.0 — Skeleton

- Docker Compose stack (PostgreSQL, pg-tide, Ollama, Langfuse)
- `riverbank version`, `riverbank config`, `riverbank health`
- `riverbank init` (Alembic migrations)
- Plugin discovery via entry points
- Pydantic Settings configuration
