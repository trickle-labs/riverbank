# riverbank

riverbank is a knowledge compiler — a Python worker and CLI that turns raw documents into a governed, queryable knowledge graph stored entirely inside PostgreSQL. Feed it a corpus of Markdown files, PDFs, tickets, or API feeds; it parses and fragments the content, runs an LLM extraction pipeline to pull out structured facts and relationships, validates the output against quality contracts, and writes the results as a cited RDF knowledge graph that you can query with SPARQL or retrieve with plain English. The end state is not a search index you re-query every time — it is a compiled artifact you can interrogate directly and trust.

The project is at v0.15.1 — a production-grade knowledge compiler with a validated extraction quality framework. Fifteen-plus release cycles have built out the full pipeline: incremental compilation, multi-format parsing, quality gates, human review, production hardening, an epistemic modelling layer, multi-tenancy, federated compilation, extraction improvement loops, and a Wikidata-grounded evaluation benchmark. This README describes what is working today and what remains on the roadmap.

---

## The goal

Most systems that feed documents to AI models work by finding the most similar chunks and handing them to the language model at query time. That pattern is fast to set up, but it has real limits: a chunk loses the context that made it meaningful, similarity is not the same as relevance, multi-document reasoning is fragile, and the model re-interprets the same raw prose from scratch on every request.

riverbank takes a different approach, borrowed from how software compilers work. A compiler does not run source code directly — it transforms it into a form the machine can execute quickly and reliably. riverbank does the same thing for knowledge: it compiles raw documents into structured facts with citations and confidence scores, validates those facts against data-quality contracts, and stores the result in a governed graph. At query time you ask structured questions against a compiled artifact, not raw text. The compiler catches contradictions and gaps before they reach users. Every claim traces back to the source fragment it came from.

The payoff over a simple search index is incremental maintenance. When one source document changes, only the knowledge derived from that document needs to be recompiled — not the whole corpus. Downstream artifacts and quality scores update automatically. This makes riverbank suitable for living corpora that change continuously, not just one-off indexing jobs.

---

## How we plan to reach that goal

The plan is organized into a sequence of concrete, testable releases that each extend the compiler by one meaningful layer.

**The first milestone (v0.1.0, done)** proves the deployment story. A single `docker compose up` brings up PostgreSQL with all required extensions, a local Ollama model runtime, Langfuse for LLM observability, and a riverbank worker container. The `riverbank health` command verifies the full extension stack is wired correctly. The catalog schema is initialized by `riverbank init`. Nothing is compiled yet, but the scaffolding that later stages depend on is in place and tested.

**The second milestone (v0.2.0, done)** delivers the core ingestion pipeline against Markdown corpora. A source is parsed, split into fragments by heading structure, and passed to an LLM extractor that produces typed facts with confidence scores and citation evidence. Each fact must carry a `prov:wasDerivedFrom` edge pointing back to its character range in the source — fabricated quotes are rejected at the type-system level. A SHACL quality gate routes low-confidence output to a draft graph rather than the trusted one. Fragment hashing means that re-ingesting an unchanged file costs zero LLM calls. This is the release where the compiler analogy becomes concrete.

**The third milestone (v0.3.0, done)** closes out the MVP with the query surface, run inspection, cost accounting, and a golden corpus CI gate. `riverbank query` executes SPARQL SELECT or ASK queries directly against the compiled graph. `riverbank runs` shows recent compiler runs with outcome, token counts, cost, and Langfuse trace deep-links. `riverbank lint --shacl-only` runs a SHACL quality report against the trusted graph and exits non-zero if the score falls below the profile threshold, making governance a first-class operation from day one. Each compiler profile now carries a `competency_questions` array of SPARQL assertions that CI validates automatically — a regression test for knowledge quality, not just code correctness.

**v0.4.0–v0.5.0 (done)** delivered incremental compilation and multi-format enrichment. The artifact dependency graph makes the recompilation story complete — `riverbank explain` shows the full dependency tree for any compiled fact. A vocabulary pass introduces SKOS concept extraction. Docling brings PDF, DOCX, and HTML support. spaCy NER with fuzzy entity matching and embedding generation round out the enrichment layer.

**v0.6.0–v0.7.0 (done)** added quality gates and production hardening. Label Studio integration routes low-confidence extractions to human reviewers whose corrections enrich the few-shot example bank. The Prefect nightly lint flow keeps SHACL quality scores current. Production hardening delivered the Helm chart, multi-replica advisory locking, Prometheus metrics, HashiCorp Vault secret management, and circuit breakers per LLM provider.

**v0.8.0–v0.9.0 (done)** introduced the epistemic layer and multi-tenancy. Negative knowledge records, argument graphs, and an assumption registry make the absence of facts as queryable as their presence. Row-Level Security activates tenant isolation at the PostgreSQL level. Federated compilation lets one riverbank instance pull triples from remote pg-ripple instances. The rendering engine emits Markdown, JSON-LD, and HTML entity pages from the compiled graph.

**v0.10.0–v0.14.0 (done)** built the extraction quality stack: a PyPI release with SBOM support; document-level LLM preprocessing with entity catalog injection; permissive extraction with per-triple confidence routing to a tentative graph; noisy-OR confidence consolidation; entity and predicate normalization; semantic few-shot selection; knowledge-prefix context injection; constrained decoding for local models; semantic chunking; SHACL shape validation; and SPARQL CONSTRUCT rules plus OWL 2 RL forward-chaining.

**v0.15.0–v0.15.1 (done)** established the external evaluation framework. `riverbank evaluate-wikidata` compares compiled triples against Wikidata's curated statements for the same Wikipedia articles. A 1,000-article benchmark dataset covers seven domains; the v0.15.1 improvement loop closed the feedback cycle with per-property recall gap analysis, targeted prompt tuning, and 200+ novel-discovery annotations.

**v1.0.0 (planned)** will deliver full API stability, signed release artifacts, Helm chart stability, and SLOs verified in CI.

The full release plan is in [ROADMAP.md](ROADMAP.md).

---

## What riverbank is built on

riverbank delegates its most demanding responsibilities to three PostgreSQL extensions that are developed alongside it.

**[pg-ripple](https://github.com/trickle-labs/pg-ripple)** is the knowledge store. It provides a full RDF triple store inside PostgreSQL with SPARQL 1.1 query support, SHACL validation, Datalog inference, OWL 2 RL reasoning, vector search via pgvector, and GraphRAG export. The capabilities riverbank relies on most heavily are `load_triples_with_confidence()` for writing facts with extraction confidence scores, the `shacl_score()` family of functions for numeric data quality gates, `rag_context()` and `rag_retrieve()` for formatting graph facts into LLM prompts, and `suggest_sameas()` / `pagerank_find_duplicates()` for entity deduplication without leaving the database. Every claim in the compiled graph carries full PROV-O provenance and can be erased subject-by-subject for GDPR compliance.

**[pg-trickle](https://github.com/trickle-labs/pg-trickle)** handles incremental view maintenance. It keeps derived artifacts — quality scores, entity pages, topic indices, embedding centroids — up to date using DBSP-inspired differential dataflow, so they reflect current state in milliseconds rather than requiring a full recomputation pass. Its `IMMEDIATE` refresh mode keeps SHACL score gates in sync within the same transaction as the graph write, which means the ingest gate decision is always based on current state rather than a stale snapshot.

**[pg-tide](https://github.com/trickle-labs/pg-tide)** is a standalone Rust binary that bridges pg-trickle stream tables with external messaging systems. It supports fifteen backends — including Kafka, NATS JetStream, Redis Streams, SQS, RabbitMQ, and HTTP webhooks — all configured via SQL. When compiled knowledge changes, pg-tide delivers the semantic diff event to whatever downstream systems are listening.

---

## Current status

riverbank is at v0.15.1. The full pipeline is working end-to-end, from document ingest through quality-gated graph writes to SPARQL query and Wikidata-validated extraction evaluation.

**Core**
- `riverbank version` / `config` / `health` / `init` — version, configuration, stack health checks, and catalog schema migrations.
- `riverbank download-models` — pre-download sentence-transformer embedding models to the local cache.

**Ingest and data management**
- `riverbank ingest <path>` — parse, fragment, extract, validate, and write to pg-ripple. Unchanged fragments (xxh3_128 hash) are skipped; re-ingesting an unchanged corpus costs zero LLM calls.
- `riverbank clear-graph` / `reset-database` — targeted or full graph and catalog reset.

**Query and analysis**
- `riverbank query <sparql>` — SPARQL SELECT or ASK against the trusted graph; `--include-tentative` unions in lower-confidence triples.
- `riverbank runs` — run inspection with outcome, token counts, cost, and Langfuse trace deep-links.
- `riverbank lint` — SHACL quality report; exits non-zero below the profile threshold.
- `riverbank explain` — dependency tree for a compiled artifact.
- `riverbank explain-rejections` — triples discarded in recent runs, grouped by rejection reason.
- `riverbank explain-conflict` — contradiction explanation for an entity or functional predicate.
- `riverbank validate-graph` — competency-question coverage against the compiled graph.
- `riverbank build-knowledge-context` — preview the KNOWN GRAPH CONTEXT block injected during extraction.

**Post-processing passes**
- `riverbank deduplicate-entities` — embed entity labels, write `owl:sameAs` links for duplicates.
- `riverbank verify-triples` — re-evaluate low-confidence triples with a self-critique LLM call.
- `riverbank normalize-predicates` — cluster near-duplicate predicates, write `owl:equivalentProperty` links.
- `riverbank detect-contradictions` — detect and demote conflicting triples for functional predicates.
- `riverbank promote-tentative` — promote tentative triples whose consolidated confidence crosses the trusted threshold.
- `riverbank gc-tentative` — archive stale tentative triples that were never promoted.
- `riverbank induce-schema` — cold-start schema induction: propose an OWL ontology from graph statistics.
- `riverbank recompile` — bulk reprocess all sources compiled by an older profile version.

**Reasoning and validation**
- `riverbank validate-shapes` — validate a named graph against SHACL shapes.
- `riverbank run-construct-rules` — execute SPARQL CONSTRUCT rules, write results to `graph/inferred`.
- `riverbank run-owl-rl` — apply OWL 2 RL forward-chaining rules.

**Evaluation**
- `riverbank evaluate-wikidata` — compare compiled triples against Wikidata ground truth; single-article or full 1,000-article benchmark.
- `riverbank recall-gap-analysis` — identify Wikidata properties with recall below threshold and generate extraction examples.
- `riverbank tune-extraction-prompts` — analyse evaluation failures and generate targeted prompt patches.
- `riverbank benchmark` — re-extract a golden corpus and compare against ground truth for quality regression.
- `riverbank expand-few-shot` — auto-expand the few-shot example bank with high-confidence triples.

**Rendering and supply chain**
- `riverbank render` — render an entity page from the compiled graph (Markdown, JSON-LD, HTML).
- `riverbank sbom` — generate a CycloneDX SBOM for the installed package.

**Lifecycle management**
- `riverbank profile` — register, list, and activate compiler profiles.
- `riverbank source` — register and manage source records.
- `riverbank review` — Label Studio human review queue management.
- `riverbank tenant` — multi-tenant lifecycle (create, suspend, delete, activate RLS).
- `riverbank federation` — federated compilation from remote pg-ripple instances.
- `riverbank entities` — entity registry: list, merge, and inspect synonym rings.

Forward-looking work is tracked in [ROADMAP.md](ROADMAP.md).

---

## Quick start

```bash
git clone https://github.com/trickle-labs/riverbank.git
cd riverbank

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d postgres pg_tide ollama langfuse
riverbank init
riverbank health
```

With [uv](https://docs.astral.sh/uv/) the install step is:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

The `[dev]` extras install pytest, ruff, mypy, and testcontainers. The `[ingest]` extras install Docling, Instructor, spaCy, and sentence-transformers, which are needed for real LLM extraction (the default CI profile uses the no-op extractor and requires only `[dev]`).

---

## Configuration

Settings are resolved in this order, with earlier sources taking precedence:

1. Explicit initialization arguments
2. Environment variables with the `RIVERBANK_` prefix and `__` as the nesting separator
3. `~/.riverbank/config.toml`, or the path in `RIVERBANK_CONFIG_FILE`

Example TOML configuration:

```toml
[db]
dsn = "postgresql+psycopg://riverbank:riverbank@localhost:5432/riverbank"

[llm]
provider = "ollama"
api_base = "http://localhost:11434/v1"
model = "llama3.2"
embed_model = "nomic-embed-text"

[langfuse]
enabled = false
host = "http://localhost:3000"
```

To use a cloud provider instead of the local Ollama runtime, override the LLM settings via environment:

```bash
export RIVERBANK_LLM__PROVIDER="openai"
export RIVERBANK_LLM__API_KEY="sk-..."
export RIVERBANK_LLM__MODEL="gpt-4o-mini"
```

---

## Architecture

riverbank is a pipeline of well-defined stages, each implemented as a plugin that can be replaced or extended without touching core code. The intended shape once the full compiler is built is:

```text
sources
  └── connectors          discover and fetch source material
        └── parsers        convert raw bytes into a structured document
              └── fragmenters  split the document into stable, addressable units
                    └── ingest gate   policy and schema checks before any LLM call
                          └── extractors    LLM extraction → typed facts with confidence
                                └── validators    SHACL quality gate
                                      └── graph writers  write to pg-ripple named graphs
                                              └── pg-trickle / pg-tide  propagate changes
```

The `_riverbank` PostgreSQL schema holds the catalog: one row per source, one row per fragment, one row per compiler profile, and one row per compilation run. Every run records its fragment hash, LLM token counts, cost, and a Langfuse trace ID so you can trace any compiled fact back to the exact LLM call that produced it.

---

## Plugins

riverbank uses Python entry points so third-party packages can add new parsers, fragmenters, extractors, connectors, or reviewers without modifying any core code. This is the same mechanism used by pytest plugins and Singer taps. The package must be installed (with `pip install -e .` or `uv pip install -e .`) for entry-point discovery to work.

The built-in plugins shipped today:

| Group | Built-in |
|---|---|
| `riverbank.parsers` | `markdown`, `docling` (PDF, DOCX, HTML) |
| `riverbank.fragmenters` | `heading`, `semantic` (embedding-based), `llm_statement` (distillation-aware), `direct` |
| `riverbank.extractors` | `noop` (testing), `instructor` (LLM extraction via Instructor) |
| `riverbank.connectors` | `filesystem` |
| `riverbank.reviewers` | `file`, `label_studio` |

---

## Roadmap summary

- **v0.1.x** — skeleton: CLI, catalog schema, local stack, plugin architecture (done)
- **v0.2.x** — MVP ingestion: Markdown corpus → pg-ripple triples with confidence scores and citation provenance; fragment-level skip on re-ingest (done)
- **v0.3.x** — MVP completion: `riverbank query`, `riverbank lint --shacl-only`, run inspection, cost accounting, golden corpus CI gate (done)
- **v0.4.x** — incremental compilation: artifact dependency graph, `riverbank explain`, vocabulary pass, Docling, embedding generation (done)
- **v0.5.x** — multi-format and vocabulary: Docling parser, spaCy NER, fuzzy entity matching, Singer/pg-tide connector (done)
- **v0.6.x** — quality gates and review: Label Studio, active-learning queue, Langfuse evaluations, Prefect nightly lint flow (done)
- **v0.7.x** — production hardening: Helm chart, multi-replica advisory locking, Prometheus metrics, Vault secret management, circuit breakers (done)
- **v0.8.x** — epistemic layer: negative knowledge, argument graphs, assumption registry, 9 epistemic status labels, model ensemble, contradiction explanation (done)
- **v0.9.x** — multi-tenant and rendering: Row-Level Security, GDPR erasure, federated compilation, Markdown/JSON-LD/HTML rendering (done)
- **v0.10.x** — release infrastructure: PyPI package, `riverbank sbom`, documentation site auto-publish (done)
- **v0.11.x** — preprocessing and post-processing: LLM document preprocessing, entity catalog injection, entity deduplication, self-critique verification, token efficiency (done)
- **v0.12.x** — permissive extraction: ontology-grounded prompts, per-triple confidence routing, tentative graph, noisy-OR consolidation, `riverbank promote-tentative` (done)
- **v0.13.x** — entity convergence: predicate normalization, synonym rings, contradiction detection, schema induction, quality regression CI (done)
- **v0.14.x** — structural improvements: constrained decoding, semantic chunking, SHACL shape validation, SPARQL CONSTRUCT rules, OWL 2 RL (done)
- **v0.15.x** — Wikidata evaluation: `riverbank evaluate-wikidata`, 1,000-article benchmark, property alignment, extraction improvement loop (done)
- **v1.0.0** — stable release: full API stability guarantee, signed artifacts, Helm chart stability, SLOs in CI (planned)

See [ROADMAP.md](ROADMAP.md) for the full release-by-release specification.

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete setup, test, and code-quality workflow. The short version:

```bash
# Unit tests (no Docker required)
pytest tests/unit/

# Golden corpus tests — corpus structure + competency question CI gate
pytest tests/golden/

# Integration tests (uses testcontainers to spin up PostgreSQL automatically)
pytest tests/integration/

# Code quality
ruff check src/ tests/
mypy src/
```

---

## Core dependencies

- [pg-ripple](https://github.com/trickle-labs/pg-ripple) — RDF triple store, SPARQL, SHACL, Datalog, PageRank, and pgvector inside PostgreSQL
- [pg-trickle](https://github.com/trickle-labs/pg-trickle) — incremental view maintenance and stream tables
- [pg-tide](https://github.com/trickle-labs/pg-tide) — relay sidecar for propagating knowledge changes to external systems
- [Typer](https://github.com/fastapi/typer) — CLI framework
- [Pydantic](https://github.com/pydantic/pydantic) and [pydantic-settings](https://github.com/pydantic/pydantic-settings) — configuration and data validation
- [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) and [Alembic](https://github.com/sqlalchemy/alembic) — catalog ORM and migrations
- [Langfuse](https://github.com/langfuse/langfuse) — LLM observability (self-hosted)
- [Ollama](https://github.com/ollama/ollama) — local model runtime (no API key required for development)

---

## License

[MIT](LICENSE)
