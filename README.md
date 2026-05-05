# riverbank

riverbank is a knowledge compiler — a Python worker and CLI that turns raw documents into a governed, queryable knowledge graph stored entirely inside PostgreSQL. Feed it a corpus of Markdown files, PDFs, tickets, or API feeds; it parses and fragments the content, runs an LLM extraction pipeline to pull out structured facts and relationships, validates the output against quality contracts, and writes the results as a cited RDF knowledge graph that you can query with SPARQL or retrieve with plain English. The end state is not a search index you re-query every time — it is a compiled artifact you can interrogate directly and trust.

The project is at an early stage. v0.1.0 ships the deployment skeleton: the CLI, catalog schema migrations, local Docker stack, and plugin architecture. The ingestion pipeline and graph writes come next. This README describes both what exists today and where the project is headed.

---

## The goal

Most systems that feed documents to AI models work by finding the most similar chunks and handing them to the language model at query time. That pattern is fast to set up, but it has real limits: a chunk loses the context that made it meaningful, similarity is not the same as relevance, multi-document reasoning is fragile, and the model re-interprets the same raw prose from scratch on every request.

riverbank takes a different approach, borrowed from how software compilers work. A compiler does not run source code directly — it transforms it into a form the machine can execute quickly and reliably. riverbank does the same thing for knowledge: it compiles raw documents into structured facts with citations and confidence scores, validates those facts against data-quality contracts, and stores the result in a governed graph. At query time you ask structured questions against a compiled artifact, not raw text. The compiler catches contradictions and gaps before they reach users. Every claim traces back to the source fragment it came from.

The payoff over a simple search index is incremental maintenance. When one source document changes, only the knowledge derived from that document needs to be recompiled — not the whole corpus. Downstream artifacts and quality scores update automatically. This makes riverbank suitable for living corpora that change continuously, not just one-off indexing jobs.

---

## How we plan to reach that goal

The plan is organized into a sequence of concrete, testable releases that each extend the compiler by one meaningful layer.

**The first milestone (v0.1.0, done)** proves the deployment story. A single `docker compose up` brings up PostgreSQL with all required extensions, a local Ollama model runtime, Langfuse for LLM observability, and a riverbank worker container. The `riverbank health` command verifies the full extension stack is wired correctly. The catalog schema is initialized by `riverbank init`. Nothing is compiled yet, but the scaffolding that later stages depend on is in place and tested.

**The second milestone (v0.2.0)** delivers the core ingestion pipeline against Markdown corpora. A source is parsed, split into fragments by heading structure, and passed to an LLM extractor that produces typed facts with confidence scores and citation evidence. Each fact must carry a `prov:wasDerivedFrom` edge pointing back to its character range in the source — fabricated quotes are rejected at the type-system level. A SHACL quality gate routes low-confidence output to a draft graph rather than the trusted one. Fragment hashing means that re-ingesting an unchanged file costs zero LLM calls. This is the release where the compiler analogy becomes concrete.

**The third milestone (v0.3.0)** closes out the MVP with the query surface, run inspection, cost accounting, and a golden corpus CI gate. The golden corpus is a fixed set of Markdown files with SPARQL assertions that the compiled graph must answer correctly — a regression test for knowledge quality, not just code correctness. `riverbank lint --shacl-only` runs a SHACL quality report against the trusted graph and exits non-zero if the score falls below the profile threshold, making governance a first-class operation from day one.

**Later milestones (v0.4.0 and beyond)** extend the system in several directions. The artifact dependency graph makes the incremental recompilation story complete: when a source changes, exactly the downstream artifacts that depend on it rebuild, and `riverbank explain` can show you the full dependency tree for any compiled fact. A vocabulary pass introduces SKOS concept extraction as a prerequisite step before relationship extraction, so entity references snap to canonical preferred-label IRIs rather than being deduplicated after the fact. Additional document formats arrive through Docling integration. A human review loop connects to Label Studio, where low-confidence extractions are routed to reviewers whose corrections flow back into the graph and enrich the example bank for future compilation runs. Production hardening brings Kubernetes deployment, multi-replica workers with fragment-level advisory locking to prevent duplicate work, and Prometheus metrics dashboards.

The full release plan is in [ROADMAP.md](ROADMAP.md).

---

## What riverbank is built on

riverbank delegates its most demanding responsibilities to three PostgreSQL extensions that are developed alongside it.

**[pg-ripple](https://github.com/trickle-labs/pg-ripple)** is the knowledge store. It provides a full RDF triple store inside PostgreSQL with SPARQL 1.1 query support, SHACL validation, Datalog inference, OWL 2 RL reasoning, vector search via pgvector, and GraphRAG export. The capabilities riverbank relies on most heavily are `load_triples_with_confidence()` for writing facts with extraction confidence scores, the `shacl_score()` family of functions for numeric data quality gates, `rag_context()` and `rag_retrieve()` for formatting graph facts into LLM prompts, and `suggest_sameas()` / `pagerank_find_duplicates()` for entity deduplication without leaving the database. Every claim in the compiled graph carries full PROV-O provenance and can be erased subject-by-subject for GDPR compliance.

**[pg-trickle](https://github.com/trickle-labs/pg-trickle)** handles incremental view maintenance. It keeps derived artifacts — quality scores, entity pages, topic indices, embedding centroids — up to date using DBSP-inspired differential dataflow, so they reflect current state in milliseconds rather than requiring a full recomputation pass. Its `IMMEDIATE` refresh mode keeps SHACL score gates in sync within the same transaction as the graph write, which means the ingest gate decision is always based on current state rather than a stale snapshot.

**[pg-tide](https://github.com/trickle-labs/pg-tide)** is a standalone Rust binary that bridges pg-trickle stream tables with external messaging systems. It supports fifteen backends — including Kafka, NATS JetStream, Redis Streams, SQS, RabbitMQ, and HTTP webhooks — all configured via SQL. When compiled knowledge changes, pg-tide delivers the semantic diff event to whatever downstream systems are listening.

---

## Current status

riverbank is in the skeleton phase (v0.1.0). The repository ships the infrastructure the compiler will run on, not the compiler itself yet.

What is fully working today:

- `riverbank version` prints the installed package version.
- `riverbank config` shows the resolved runtime settings from environment variables and the optional TOML config file.
- `riverbank init` applies the `_riverbank` catalog schema via Alembic migrations, creating the tables for sources, fragments, compiler profiles, runs, artifact dependencies, and audit log entries.
- `riverbank health` verifies the full extension stack is alive by calling `pgtrickle.preflight()` (seven system checks) and `pg_ripple.pg_tide_available()`.
- Plugin discovery loads parsers, fragmenters, extractors, connectors, and reviewers via Python entry points, which is the mechanism later ingestion stages will build on.

The commands `riverbank ingest` and `riverbank query` exist as placeholders that signal where the v0.2.0 and v0.3.0 pipeline stages will land.

Forward-looking work is tracked in [ROADMAP.md](ROADMAP.md), [plans/riverbank.md](plans/riverbank.md), and [plans/riverbank-implementation.md](plans/riverbank-implementation.md).

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

The `[dev]` extras install pytest, ruff, mypy, and testcontainers. The `[ingest]` extras install Docling, Instructor, spaCy, and sentence-transformers, which are only needed when the ingestion pipeline lands in v0.2.0.

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

Today the repository implements the catalog, CLI, and service wiring. The extraction and graph-writing stages are the next work items.

---

## Plugins

riverbank uses Python entry points so third-party packages can add new parsers, fragmenters, extractors, connectors, or reviewers without modifying any core code. This is the same mechanism used by pytest plugins and Singer taps. The package must be installed (with `pip install -e .` or `uv pip install -e .`) for entry-point discovery to work.

The built-in plugins shipped today:

| Group | Built-in |
|---|---|
| `riverbank.parsers` | `markdown` |
| `riverbank.fragmenters` | `heading` |
| `riverbank.extractors` | `noop` (no-op, for testing) |
| `riverbank.connectors` | `filesystem` |
| `riverbank.reviewers` | `file` |

---

## Roadmap summary

- **v0.1.x** — skeleton: CLI, catalog schema, local stack, plugin architecture (done)
- **v0.2.x** — MVP ingestion: Markdown corpus → pg-ripple triples with confidence scores and citation provenance; fragment-level skip on re-ingest
- **v0.3.x** — MVP completion: `riverbank query`, `riverbank lint --shacl-only`, run inspection, cost accounting, golden corpus CI gate
- **v0.4.x** — incremental compilation: artifact dependency graph, `riverbank explain`, vocabulary pass, Docling multi-format parser, Singer connector, embedding generation
- **v0.5.x** — quality gates and review: Label Studio integration, active-learning review queue, Langfuse evaluations, full lint flow, Prefect orchestration
- **v0.6.x** — production hardening: Helm chart, multi-replica workers, Prometheus metrics, audit trail, bulk reprocessing

See [ROADMAP.md](ROADMAP.md) for the full release-by-release specification.

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete setup, test, and code-quality workflow. The short version:

```bash
# Unit tests (no Docker required)
pytest tests/unit/

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
