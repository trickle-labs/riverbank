# riverbank — Implementation Plan

> **Date:** 2026-05-03  
> **Status:** Implementation plan — companion to [riverbank.md](riverbank.md)  
> **Scope:** Engineering blueprint for riverbank — a standalone project built on top of [pg-ripple](https://github.com/trickle-labs/pg-ripple), [pg-trickle](https://github.com/trickle-labs/pg-trickle), and [pg-tide](https://github.com/trickle-labs/pg-tide), from MVP through production hardening  
> **Constraint:** Open-source software only (permissive licences preferred: MIT, Apache 2.0, BSD)

---

## 0. Goals and non-goals

### Goals

1. **Single-command MVP.** A new operator can ingest a Markdown corpus, query the resulting knowledge graph, and inspect the compiler runs in under 10 minutes from a clean checkout, using only `docker compose up`.
2. **Pluggable from day one.** Document parsers, LLM providers, embedding models, source connectors, and review back-ends are loaded via entry points. Adding a new connector does not require modifying core code.
3. **Operationally boring.** Stateless workers, externalised state in PostgreSQL, structured logs, OpenTelemetry traces. Deployable as a single container, a `docker compose` stack, or a Helm chart on Kubernetes.
4. **Open source only.** Every dependency is permissively licensed. No usage tiers, no SaaS lock-in. Local-first development is the default; cloud LLM endpoints are optional.
5. **Incremental from day one.** The MVP must demonstrate fragment-level skip on re-ingest. This is what distinguishes the product from a batch re-indexer.

### Non-goals

1. **Not a custom UI.** Review uses Label Studio. Observability uses Langfuse and Perses. The compiler exposes APIs, not a bespoke web app.
2. **Not a workflow editor.** The compiler is a pipeline of well-defined stages, not a DAG editor for end users to assemble.
3. **Not a connector marketplace.** The MVP supports filesystem ingest and a Singer-tap shim. Pre-built connectors land per-source as needed.
4. **Not multi-tenant in the MVP.** Single-tenant from Phase 1; multi-tenant scaffolding lands in Phase 5.

---

## 1. Architecture at a glance

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            SOURCES (file, API, Kafka)                         │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                              ┌────────▼────────┐
                              │   Connector     │  (plugin or Singer tap)
                              │   plane          │   filesystem, Singer tap, GitHub,
                              │                  │   Meltano SDK, …
                              └────────┬────────┘
                                       │ source events
                              ┌────────▼────────┐
                              │   pg_trickle    │   inbox stream tables
                              │   (existing)     │   + pg-tide for
                              │                  │   Kafka, NATS, Redis, SQS,
                              │                  │   RabbitMQ, webhooks, Singer
                              └────────┬────────┘
                                       │
┌──────────────────────────────────────▼───────────────────────────────────────┐
│                        riverbank worker                               │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Parser     │→ │ Fragmenter  │→ │ Ingest gate  │→ │ Extraction (LLM)    │  │
│  │ (Docling,  │  │ (heading,   │  │ (policy +    │  │ (Instructor +       │  │
│  │  markdown) │  │  page, …)   │  │  schema +    │  │  pluggable provider) │  │
│  │            │  │             │  │  citation)   │  │                     │  │
│  └────────────┘  └─────────────┘  └──────┬───────┘  └──────────┬──────────┘  │
│        ▲                                 │                     │              │
│        │ (plugin)                        ▼                     ▼              │
│  ┌────────────┐                  ┌───────────────┐    ┌────────────────┐    │
│  │ Profile    │                  │ Quarantine    │    │  Validator     │    │
│  │ catalog    │                  │ (rejected     │    │  SHACL gate +  │    │
│  │ (DB)        │                  │  named graph) │    │  pgc:Synthesis │    │
│  └────────────┘                  └───────────────┘    └────────┬───────┘    │
│                                                                │             │
│                                                                ▼             │
│                                                      ┌──────────────────┐   │
│                                                      │ Graph writer     │   │
│                                                      │ (load_triples_   │   │
│                                                      │  with_confidence) │   │
│                                                      └────────┬─────────┘   │
└────────────────────────────────────────────────────────────────┼────────────┘
                                                                 │
                                                ┌────────────────▼────────────────┐
                                                │       pg_ripple (existing)       │
                                                │  VP storage · SPARQL · SHACL ·  │
                                                │  Datalog · PageRank · pgvector  │
                                                └────────────────┬────────────────┘
                                                                 │ outbox events
                                                ┌────────────────▼────────────────┐
                                                │     pg_trickle outbox            │
                                                │  + pg-tide (Rust)                │
                                                │  → review queue (Label Studio)  │
                                                │  → downstream subscribers        │
                                                │  → render service (Markdown)     │
                                                │  → NATS / Kafka / Redis / SQS   │
                                                └─────────────────────────────────┘

  ┌─────────────────────────────────┐         ┌─────────────────────────────────┐
  │  Orchestration (Prefect)         │         │  Observability (OTel + Langfuse) │
  │  Flow runs, retries, schedules   │         │  Traces, prompts, costs, evals   │
  └─────────────────────────────────┘         └─────────────────────────────────┘
```

The worker is the only new long-running process. Everything else is either an existing pg_ripple capability, a sidecar (Label Studio, Langfuse, Prefect server), or a library import.

---

## 2. Technology stack

All choices are open-source with permissive licences. Versions are minimum-supported as of the implementation start date.

| Layer | Technology | Licence | Phase introduced | Rationale |
|---|---|---|---|---|
| Worker language | Python 3.12+ | PSF | Phase 0 | Pgrx remains for pg_ripple itself; the compiler is I/O-bound and benefits from the AI tooling ecosystem |
| Document parser | [Docling](https://github.com/docling-project/docling) ≥ 2.92 (LF AI & Data) | MIT | Phase 1 | Multi-format (PDF, DOCX, PPTX, XLSX, HTML, audio); unified `DoclingDocument`; produces stable structure metadata. Markdown-only corpora can use [markdown-it-py](https://github.com/executablebooks/markdown-it-py) (MIT) to keep the dependency surface small in CI |
| Structured LLM output | [Instructor](https://github.com/567-labs/instructor) ≥ 1.15 | MIT | Phase 1 | Pydantic-validated extraction with retry on schema failure; provider-agnostic interface (OpenAI, Anthropic, Ollama, vLLM) |
| Local model runtime | [Ollama](https://github.com/ollama/ollama) | MIT | Phase 1 | One-binary install of any open-weight model; HTTP API compatible with the OpenAI client. Used for CI mock mode and air-gapped deployments |
| Retry / scheduling (Phase 1) | [tenacity](https://github.com/jd/tenacity) + [APScheduler](https://github.com/agronholm/apscheduler) ≥ 4.0 | Apache 2.0 | Phase 1 | `tenacity` handles per-call retry with exponential back-off; `APScheduler` drives the nightly lint and daily SHACL snapshot jobs. No extra service or port required |
| Workflow orchestration | [Prefect](https://github.com/PrefectHQ/prefect) ≥ 3.6 | Apache 2.0 | Phase 2 | Full flow/task graph, run history, retry UI, and scheduling console. Introduced once the pipeline is stable and operational visibility becomes the priority |
| LLM observability | [Langfuse](https://github.com/langfuse/langfuse) ≥ 3.x | MIT (core) | Phase 1 | Self-hostable via `docker compose up`; traces every LLM call with cost, latency, prompt/completion. Native Instructor integration |
| OpenTelemetry | [opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) | Apache 2.0 | Phase 1 | Traces/metrics for the worker; exports to Langfuse and any OTLP collector |
| Embeddings | [sentence-transformers](https://github.com/UKPLab/sentence-transformers) | Apache 2.0 | Phase 2 | CPU-friendly local embedding models (e.g., `all-MiniLM-L6-v2`, `bge-small-en-v1.5`); no API call required for vector indices |
| Entity NER | [spaCy](https://github.com/explosion/spaCy) ≥ 3.8 | MIT | Phase 2 | Pre-resolves named entities before LLM extraction; reduces token usage and noise (the same pattern used in production by Kompl and others) |
| Fuzzy matching | [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | MIT | Phase 2 | Fast Rust-backed token-set ratio for Python-side entity pre-resolution before DB writes. Note: pg-ripple provides `pg:fuzzy_match()` and `pg:token_set_ratio()` with a GIN trigram index directly in SPARQL (v0.87) — use the in-database functions for query-time matching and RapidFuzz only for pre-LLM entity context preparation |
| Probabilistic entity matching | [dedupe](https://github.com/dedupeio/dedupe) | MIT | Phase 4 | Active-learning entity-matching trained on review corrections. Note: pg-ripple provides three in-database dedup methods — `suggest_sameas()` (vector-based, v0.49), `find_alignments()` (KGE cross-graph, v0.57), and `pagerank_find_duplicates()` (centrality-guided, v0.88) — which handle most scenarios without a Python dependency. Use dedupe only when active-learning from Label Studio corrections requires a Python-native training loop |
| Source connectors | [Singer SDK](https://github.com/meltano/sdk) (Meltano) | Apache 2.0 | Phase 2 | 600+ existing taps with a uniform output schema; lighter than Airbyte for self-hosting |
| Human review | [Label Studio](https://github.com/HumanSignal/label-studio) ≥ 1.13 | Apache 2.0 | Phase 3 | Pre-labeling, span annotation, ensemble arbitration, webhook-driven correction loop |
| BM25 text search | PostgreSQL `tsvector` + `ts_rank_cd` (built-in) | PostgreSQL (BSD) | Phase 1 | GIN-indexed full-text search with BM25-style ranking over compiled artifact text. `ts_rank_cd` applies cover-density weighting. pg-ripple's GIN trigram index adds fuzzy-match on top. No additional dependency required |
| Vector search | pgvector (already in pg_ripple) | PostgreSQL | Phase 1 | Cosine-similarity search over compiled artifact embeddings; co-located with structured facts |
| Hybrid search fusion | RRF SQL function (in-repo) | — | Phase 2 | Reciprocal rank fusion (`Σ 1/(60 + rank_i)`) combines BM25, vector, and graph-traversal result sets. Implemented as a small SQL helper — no external dependency, no tuning parameters. Scores from each stream are normalised before fusion so relative ranking order, not raw score magnitude, determines the final result |
| Container packaging | Docker / Compose | Apache 2.0 | Phase 0 | Standard. Single Dockerfile per worker variant |
| Kubernetes packaging | Helm chart | Apache 2.0 | Phase 4 | Production deployments. Built on the existing pg_ripple chart |
| Metrics & dashboards | [Prometheus](https://github.com/prometheus/prometheus) + [Perses](https://github.com/perses/perses) | Apache 2.0 | Phase 4 | Compiler run rates, cost trends, queue depth, SHACL score over time. Perses is a CNCF Apache 2.0 dashboard tool designed for Prometheus |
| Object storage (artifacts) | Filesystem (default) + [fsspec](https://github.com/fsspec/filesystem_spec) with provider backends | Apache 2.0 | Phase 4 | Local deployments use the filesystem. Cloud deployments configure a backend via `RIVERBANK_STORAGE_BACKEND`: S3 ([s3fs](https://github.com/fsspec/s3fs), Apache 2.0 — AWS S3, Cloudflare R2, Backblaze B2), Azure Blob Storage ([adlfs](https://github.com/fsspec/adlfs), MIT), or GCP Cloud Storage ([gcsfs](https://github.com/fsspec/gcsfs), BSD). All share the same fsspec `AbstractFileSystem` interface; switching backends requires only a config change |

### Licence notes

- All dependencies are MIT, Apache 2.0, or PostgreSQL (BSD). No AGPL dependencies are used. AGPL carries network-service disclosure obligations (AGPL v3 §13) that apply to any hosted deployment of riverbank; this is avoided by design.
- Langfuse Cloud is *not* required. The MIT-licensed core supports all features used in this plan; the `ee/` enterprise folder is excluded by Docker build.

---

## 3. Repository layout

riverbank is a standalone repository. It depends on pg-ripple and pg-trickle as external packages — no code is copied or forked from those repos.

```
riverbank/                       (this repo)
├── pyproject.toml
├── README.md
├── Dockerfile
├── docker-compose.yml          one-command MVP launcher (includes pg-ripple + pg-trickle)
├── helm/                       Phase 4
├── plans/                      strategy and implementation docs
├── src/riverbank/
│   ├── __init__.py
│   ├── cli.py                  `riverbank` command
│   ├── config.py               pydantic-settings; env + YAML
│   ├── pipeline/               ingest, recompile, and lint pipelines (plain async functions; Prefect wrappers added in Phase 2)
│   │   ├── ingest.py
│   │   ├── recompile.py
│   │   └── lint.py
│   ├── parsers/                (plugin) Docling, markdown-it, plain text
│   ├── fragmenters/            (plugin) heading-based, page-based, time-segment
│   ├── extractors/             (plugin) Instructor-based + custom
│   ├── connectors/             (plugin) filesystem, Singer-tap, GitHub
│   ├── ingest_gate/            editorial policy + citation grounding + schema
│   ├── writers/                graph writer, draft writer
│   ├── reviewers/              (plugin) Label Studio, file-based
│   ├── renderers/              Phase 6: Markdown/JSON-LD page rendering
│   ├── catalog/                SQLAlchemy models + Alembic migrations
│   ├── prov/                   provenance helpers (PROV-O, evidence spans)
│   ├── observability/          OTel setup, Langfuse handler, metrics
│   └── plugin.py               entry-point loader
├── tests/
│   ├── conftest.py             testcontainers, mock LLM
│   ├── unit/
│   ├── integration/
│   └── golden/                 SPARQL assertions over a fixed corpus
└── examples/
    ├── markdown-corpus/
    ├── github-issues/
    └── compliance-pdfs/
```

Dependencies on sibling projects:

| Dependency | Role in riverbank |
|---|---|
| **pg-ripple** | Graph storage, SPARQL, SHACL validation, Datalog inference, provenance, pgvector, fuzzy matching (`pg:fuzzy_match`, `pg:token_set_ratio`), entity resolution (`suggest_sameas`, `find_alignments`, `pagerank_find_duplicates`), JSON↔RDF mapping registry, CONSTRUCT writeback rules, CDC bridge triggers, bidirectional integration (conflict policies, outbox/inbox), SPARQL live subscriptions (SSE), uncertain knowledge engine, PageRank & centrality analytics |
| **pg-trickle** | Inbound stream tables (with IMMEDIATE mode for transactional consistency), differential change propagation, outbox event delivery, tiered scheduling, watermark gating, change buffer compaction, dbt integration |
| **pg-tide** | External system integration: forward mode (outbox→NATS/Kafka/Redis/SQS/RabbitMQ/webhooks), reverse mode (external→inbox), Singer target mode (Singer taps→inbox via standard Singer protocol), SQL-configured pipelines, hot reload, HA via advisory locks |

---

## 4. Catalog schema

The schema lives in the `_riverbank` PostgreSQL schema, separate from `_pg_ripple` to keep the compiler upgradable independently of the extension.

### 4.1 Tables

```sql
-- A registered source (a logical identifier, not a fragment).
CREATE TABLE _riverbank.sources (
    id              BIGSERIAL PRIMARY KEY,
    iri             TEXT UNIQUE NOT NULL,           -- e.g., file:///docs/intro.md
    source_type     TEXT NOT NULL,                  -- 'file', 'github_issue', 'kafka', …
    connector       TEXT NOT NULL,                  -- which plugin produced it
    profile_id      BIGINT NOT NULL REFERENCES _riverbank.profiles(id),
    named_graph     TEXT NOT NULL,                  -- where compiled triples land
    content_hash    BYTEA NOT NULL,                 -- last seen
    last_seen_at    TIMESTAMPTZ NOT NULL,
    last_compiled_at TIMESTAMPTZ,
    status          TEXT NOT NULL,                  -- 'pending', 'compiled', 'failed', 'rejected'
    metadata        JSONB DEFAULT '{}'
);

-- A stable section of a source (page, heading, time segment, …).
CREATE TABLE _riverbank.fragments (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT NOT NULL REFERENCES _riverbank.sources(id) ON DELETE CASCADE,
    fragment_key    TEXT NOT NULL,                  -- stable identifier within the source
    content_hash    BYTEA NOT NULL,                 -- skip re-extraction when unchanged
    char_start      INTEGER,
    char_end        INTEGER,
    page_number     INTEGER,
    heading_path    TEXT[],                         -- ['Chapter 1', '1.2 Background']
    text_excerpt    TEXT,                           -- the raw text content
    UNIQUE (source_id, fragment_key)
);
CREATE INDEX ON _riverbank.fragments (content_hash);

-- A compiler profile (versioned).
CREATE TABLE _riverbank.profiles (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    version         INTEGER NOT NULL,
    schema_json     JSONB NOT NULL,                 -- output JSON Schema
    prompt_hash     BYTEA NOT NULL,
    prompt_text     TEXT NOT NULL,
    editorial_policy JSONB NOT NULL,                -- ingest gate policy YAML→JSON
    model_provider  TEXT NOT NULL,                  -- 'openai-compat', 'ollama', …
    model_name      TEXT NOT NULL,
    embedding_model TEXT,
    max_fragment_tokens INTEGER NOT NULL DEFAULT 2000,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

-- One row per compile attempt (success or failure).
CREATE TABLE _riverbank.runs (
    id              BIGSERIAL PRIMARY KEY,
    fragment_id     BIGINT NOT NULL REFERENCES _riverbank.fragments(id) ON DELETE CASCADE,
    profile_id      BIGINT NOT NULL REFERENCES _riverbank.profiles(id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    outcome         TEXT NOT NULL,                  -- 'success', 'schema_fail', 'gate_reject', 'shacl_fail', 'error'
    error_message   TEXT,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    cost_usd        NUMERIC(12, 6),
    output_hash     BYTEA,
    diagnostics     JSONB,                          -- warnings, contradictions, …
    langfuse_trace_id TEXT
);
CREATE INDEX ON _riverbank.runs (fragment_id, started_at DESC);
CREATE INDEX ON _riverbank.runs (profile_id, started_at DESC);

-- Dependency graph: which compiled artifact depends on which fragments and rules.
CREATE TABLE _riverbank.artifact_deps (
    artifact_iri    TEXT NOT NULL,                  -- the SPARQL/RDF identifier of the artifact
    dep_kind        TEXT NOT NULL,                  -- 'fragment', 'rule', 'profile', 'artifact'
    dep_ref         TEXT NOT NULL,                  -- fragment IRI, rule name, profile id:version, artifact IRI
    PRIMARY KEY (artifact_iri, dep_kind, dep_ref)
);
CREATE INDEX ON _riverbank.artifact_deps (dep_kind, dep_ref);

-- Append-only log of every compile-side operation (the §7.10 audit log).
CREATE TABLE _riverbank.log (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    operation       TEXT NOT NULL,                  -- 'ingest', 'lint', 'render', 'gate_reject', …
    actor           TEXT,                           -- operator id, agent id, or 'system'
    subject_iri     TEXT,
    payload         JSONB NOT NULL
);
CREATE INDEX ON _riverbank.log (occurred_at DESC);
CREATE INDEX ON _riverbank.log (operation, occurred_at DESC);
```

### 4.2 RDF vocabulary

A small `pgc:` vocabulary lives in `_pg_ripple.dictionary` and is published as a Turtle ontology file in `riverbank/ontology/pgc.ttl`:

```turtle
@prefix pgc: <https://pg-ripple.org/compile#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

pgc:Source            a rdfs:Class .
pgc:Fragment          a rdfs:Class .
pgc:Profile           a rdfs:Class .
pgc:Run               a rdfs:Class .
pgc:Synthesis         a rdfs:Class ; rdfs:subClassOf pgc:Artifact .
pgc:LintFinding       a rdfs:Class .
pgc:ArgumentRecord    a rdfs:Class .             # Phase 5
pgc:AssumptionRecord  a rdfs:Class .             # Phase 5
pgc:NegativeKnowledge a rdfs:Class .             # Phase 5

pgc:fromFragment      a rdf:Property ; rdfs:subPropertyOf prov:wasDerivedFrom .
pgc:byProfile         a rdf:Property .
pgc:confidence        a rdf:Property ; rdfs:range xsd:float .
pgc:epistemicStatus   a rdf:Property .
pgc:evidenceSpan      a rdf:Property .           # JSON: {char_start, char_end, page}
```

The vocabulary is intentionally small. Domain extraction is expressed in the compiler profile's JSON Schema, not in OWL.

---

## 5. Plugin architecture

Five extension points are implemented as Python entry points in `pyproject.toml`:

```toml
[project.entry-points."riverbank.parsers"]
docling   = "riverbank.parsers.docling:DoclingParser"
markdown  = "riverbank.parsers.markdown:MarkdownParser"

[project.entry-points."riverbank.fragmenters"]
heading   = "riverbank.fragmenters.heading:HeadingFragmenter"
page      = "riverbank.fragmenters.page:PageFragmenter"

[project.entry-points."riverbank.extractors"]
instructor = "riverbank.extractors.instructor_extractor:InstructorExtractor"

[project.entry-points."riverbank.connectors"]
filesystem = "riverbank.connectors.fs:FilesystemConnector"
singer     = "riverbank.connectors.singer:SingerTapConnector"

[project.entry-points."riverbank.reviewers"]
labelstudio = "riverbank.reviewers.labelstudio:LabelStudioReviewer"
file        = "riverbank.reviewers.file:FileReviewer"
```

Each plugin implements a small protocol (Python `Protocol` class):

```python
class Parser(Protocol):
    name: ClassVar[str]
    supported_mimetypes: ClassVar[set[str]]
    def parse(self, source: SourceRecord) -> ParsedDocument: ...

class Fragmenter(Protocol):
    name: ClassVar[str]
    def fragment(self, doc: ParsedDocument) -> Iterator[Fragment]: ...

class Extractor(Protocol):
    name: ClassVar[str]
    def extract(self, fragment: Fragment, profile: Profile,
                trace: TraceCtx) -> ExtractionResult: ...

class Connector(Protocol):
    name: ClassVar[str]
    def discover(self, config: dict) -> Iterator[SourceRecord]: ...
    def fetch(self, source: SourceRecord) -> bytes: ...

class Reviewer(Protocol):
    name: ClassVar[str]
    def enqueue(self, task: ReviewTask) -> None: ...
    def collect(self) -> Iterator[ReviewDecision]: ...
```

A plugin in a third-party package is registered automatically via Python entry points — no edit to the core code is required. This is the same mechanism used by `pytest`, `flake8`, and Singer.

---

## 6. Phase 0 — Skeleton (week 1)

Goal: a runnable empty pipeline with all the scaffolding in place.

### Deliverables

1. `riverbank/` directory with `pyproject.toml`, `Dockerfile`, `docker-compose.yml`.
2. `riverbank` CLI with `init`, `version`, `health` subcommands.
3. Catalog schema migrations (Alembic) for the §4.1 tables.
4. CI workflow that runs `pytest` against an ephemeral PostgreSQL with pg_ripple installed (via `testcontainers-python`).
5. A no-op extractor that records a run, emits a span, and writes nothing to the graph — verifying the orchestration plumbing end-to-end.
6. `docker compose up` brings up: PostgreSQL with pg_ripple and pg_trickle, pg-tide, the worker, and Langfuse. All services are reachable on `localhost`. (Prefect server is deferred to Phase 2.)

### Acceptance

```bash
git clone <repo> && cd riverbank
docker compose up -d
riverbank health   # → "all systems nominal"
```

No LLM call is made yet. This phase exists to prove the deployment story.

---

## 7. Phase 1 — MVP (weeks 2–6)

Goal: ingest a Markdown corpus, extract atomic facts, write them to pg_ripple with confidence and provenance, and demonstrate fragment-level skip on re-ingest.

### 7.1 Scope

**In:**
- `markdown` parser + `heading` fragmenter
- `instructor` extractor with OpenAI-compatible endpoint (Ollama for local/CI)
- A single deterministic example profile: `docs-policy-v1`
- Editorial policy ingest gate: minimum heading depth, minimum fragment length, language check
- Citation grounding: every extracted triple must carry a `prov:wasDerivedFrom` edge with character-range evidence
- JSON Schema validation via Instructor's Pydantic loop
- `load_triples_with_confidence()` writes facts to a named graph
- `shacl_score()` gate routes low-quality output to `<draft>` graph
- Run records with token counts, cost, Langfuse trace links
- Fragment hash check: re-ingesting an unchanged file results in 0 LLM calls
- Filesystem connector with directory-watcher mode (`watchdog` library)
- `riverbank ingest <path>`, `riverbank query <sparql>`, `riverbank runs --since 1h`

**Out (deferred):**
- PDF/DOCX parsing (Phase 2)
- Entity resolution beyond exact match (Phase 2)
- Argument graphs, negative knowledge (Phase 5)
- Label Studio review UI (Phase 3)
- Prefect — deferred to Phase 2. Phase 1 uses `tenacity` for retry and `APScheduler` for scheduling

### 7.2 Key implementation decisions

**Instructor configuration.** The extractor uses `instructor.from_provider(profile.model_provider + "/" + profile.model_name)`. For CI: `ollama/llama3.2:3b` running in a sidecar container, with deterministic sampling (`temperature=0`, fixed seed). For development: any OpenAI-compatible endpoint. The same code path serves both.

**Fragment hashing.** The `Fragment.content_hash` is `xxh3_128(canonicalized_text)` — the same hashing primitive pg_ripple uses for the dictionary. The fragmenter normalises whitespace and strips trailing newlines before hashing. A fragment whose `content_hash` matches the most recent successful run's `fragment.content_hash` skips extraction entirely; a `pgc:SkipRun` log entry is recorded.

**Citation grounding.** Each extracted triple's evidence span is a sub-range of the fragment text. The Instructor schema mandates an `evidence_span: EvidenceSpan` field on every extracted fact:

```python
class EvidenceSpan(BaseModel):
    char_start: int
    char_end: int
    quote: str           # verbatim — validated against the fragment text

class ExtractedFact(BaseModel):
    subject: str
    predicate: str
    object_value: str
    object_kind: Literal["iri", "literal"]
    evidence_span: EvidenceSpan
    confidence: float = Field(ge=0.0, le=1.0)
```

A Pydantic validator confirms `fragment.text[span.char_start:span.char_end] == span.quote`; if not, Instructor's retry loop re-prompts the model. After three failures the fact is rejected and counted in the run diagnostics. This is the §7.0 ingest gate enforced at the type-system level.

**Ingest gate flow.**

```
Fragment ─▶ editorial policy score ─▶ if below threshold: insert into _riverbank.log
                                       (gate_reject), do not call LLM
              │
              ▼ above threshold
         LLM extraction ─▶ schema validation (Instructor) ─▶
                                       if invalid: log (schema_fail), no graph write
              │
              ▼ valid
         Citation grounding check ─▶ if missing: log (citation_fail), quarantine to <draft>
              │
              ▼ grounded
         shacl_score(graph_iri) ─▶ if < threshold: route to <review> graph
              │
              ▼ above threshold
         load_triples_with_confidence() ─▶ <trusted> graph
              │
              ▼
         Emit pg_trickle outbox event (entity.updated, source.compiled)
```

**Cost accounting.** Token counts come from the Instructor response. Cost-per-token tables are in YAML in `riverbank/cost_tables/`; Ollama models are zero-cost. The `cost_usd` column is the source of truth for §7.6 dashboards.

**Observability.** OpenTelemetry spans wrap every stage (parse, fragment, gate, extract, validate, write). Langfuse receives the LLM call traces with prompt and completion. The run record in `_riverbank.runs` carries a `langfuse_trace_id` column for direct deep-link access from the CLI.

### 7.3 Deployment

`docker-compose.yml` brings up five services:

| Service | Image | Ports |
|---|---|---|
| postgres | `postgres:18` with pg_ripple and pg_trickle installed | 5432 |
| pg-tide | `ghcr.io/trickle-labs/pg-tide:latest` | 9090 (metrics) |
| worker | `riverbank:latest` | — |
| langfuse-web | `langfuse/langfuse:3` | 3000 |
| langfuse-worker | `langfuse/langfuse-worker:3` | — |
| ollama (CI/local) | `ollama/ollama:latest` | 11434 |

Prefect server is not part of the Phase 1 stack. Retry is handled by `tenacity`; scheduled jobs (nightly lint, daily SHACL snapshot) run via `APScheduler` inside the worker process. Prefect is introduced in Phase 2 alongside the full scheduling console.

Resource budget: the entire stack runs comfortably on a 4 vCPU / 8 GB laptop for the example corpus.

### 7.4 Acceptance tests

1. **End-to-end ingest.** `riverbank ingest examples/markdown-corpus/` produces N triples in pg_ripple, all with `pgc:fromFragment` edges and confidence scores.
2. **Idempotent re-ingest.** Running the same command twice produces 0 additional LLM calls. The second run's `_riverbank.runs` rows have `outcome = 'skipped'`.
3. **Schema rejection.** A malformed prompt (configured to produce invalid output) results in `outcome = 'schema_fail'` and zero graph writes.
4. **Citation enforcement.** A fact with a fabricated quote (test fixture) is rejected; the run diagnostics record the failure.
5. **SHACL gate.** A fragment that produces facts violating a profile's SHACL shape (e.g., missing required predicate) routes to the `<review>` graph, not `<trusted>`.
6. **Reproducible CI.** The full test suite runs in CI in under 5 minutes against `ollama/llama3.2:3b`.

---

## 8. Phase 2 — Incremental compilation (weeks 7–10)

Goal: prove that the system rebuilds *only* what changed when a source updates.

### Deliverables

1. **Artifact dependency graph.** Every compiled artifact records its `(fragment, profile_version, rule_set)` dependencies in `artifact_deps`. The graph is queryable in SQL and SPARQL.
2. **`riverbank explain <artifact-iri>`** — dumps the dependency tree of any compiled artifact: which fragments it came from, which profile version, which rules contributed.
3. **Recompile flow.** When a source updates: identify changed fragments → identify dependent artifacts → invalidate them → re-extract changed fragments → re-derive dependent artifacts → emit semantic diff event.
4. **Docling integration.** PDF, DOCX, PPTX, HTML, and image OCR. The `Docling` parser becomes the default for non-Markdown sources.
5. **spaCy NER pre-resolution.** Named entities are extracted before the LLM call and passed as a structured context block. The Instructor schema can reference pre-resolved entity IRIs, reducing both token usage and entity-confusion errors.
6. **Fuzzy entity matching.** pg-ripple provides `pg:fuzzy_match()` and `pg:token_set_ratio()` directly in SPARQL (v0.87), backed by a GIN trigram index on `_pg_ripple.confidence`. These produce candidate `owl:sameAs` edges with confidence scores without leaving the database. For Python-side pre-resolution before LLM calls, `RapidFuzz` token-set ratio provides the same matching in the extraction pipeline. Above-threshold matches are written automatically; borderline matches are flagged for Phase 3 review. Additionally, pg-ripple's `suggest_sameas()` (v0.49) provides vector-based entity candidates and `pagerank_find_duplicates()` (v0.88) provides centrality-guided entity deduplication.
7. **Embedding generation.** Sentence-transformers locally produce embeddings for each compiled summary. Embeddings are written to a pgvector column on the entity-page artifact.
8. **Singer-tap connector.** A `singer` connector wraps any Singer tap; the MVP includes `tap-github` for issues and `tap-slack-search` for channel exports. Alternatively, configure pg-tide as a Singer target:

```bash
# In a Meltano project or standalone
tap-github | pg-tide --target singer --config tide-singer-config.json
# pg-tide writes RECORD messages directly to the pg-trickle inbox table
```

This bypasses the Python connector wrapper entirely. For SaaS-specific integrations not covered by tide backends, the Python wrapper remains the best choice; for standard Singer taps, piping directly to the pg-tide target is simpler.

### Acceptance

1. Modify one paragraph in one Markdown file. Re-run `riverbank ingest`. Exactly one fragment is re-extracted; all unrelated artifacts remain untouched.
2. The semantic diff event (`pg_trickle` outbox payload) lists exactly the affected facts, summaries, and entity pages.
3. Replace one PDF in the corpus with an updated version. Only fragments whose content hash changed are re-extracted, even if the page numbers shifted.
4. `riverbank explain entity:Acme` prints a tree showing every fragment, profile version, and rule that contributed to the entity page.

---

## 9. Phase 3 — Quality gates and review loop (weeks 11–14)

Goal: a running human-in-the-loop pipeline that converts low-confidence extractions into reviewed, high-confidence facts.

### Deliverables

1. **Label Studio integration.**
   - `LabelStudioReviewer` plugin creates one Label Studio task per item in the review queue.
   - Pre-labels the fact with the LLM's extraction; the reviewer accepts, corrects, or rejects.
   - Webhook posts decisions back to `riverbank`; corrections enter the `<human-review>` named graph at higher priority than LLM-extracted facts.
   - Custom labeling templates for: atomic-fact correction, span-based evidence annotation, ensemble disagreement arbitration.
2. **Active-learning queue.** `riverbank review queue` runs the SPARQL query from §10.9 of the parent plan (centrality × uncertainty) and refreshes Label Studio task priorities.
3. **Editorial policy example bank.** Each Label Studio decision is exported to the profile's example bank. The next compile run uses these as few-shot examples.
4. **SHACL score history.** A daily Prefect flow snapshots `shacl_score()` per named graph into a Prometheus metric. (Prefect is first introduced here; the APScheduler job from Phase 1 is replaced.)
5. **Langfuse evaluations.** Generated Q&A pairs (parent §8.4) run as Langfuse dataset evaluations on every recompile; regressions surface as Langfuse alerts.
6. **Lint flow.** `riverbank lint` runs the §10.21 lint pass and writes findings to `pgc:LintFinding` triples; Prefect schedules it nightly.

### Acceptance

1. A reviewer receives a Label Studio task within 60 seconds of a low-confidence extraction.
2. After a correction, a SPARQL query for the corrected entity returns the human-reviewed fact, not the LLM extraction.
3. The example bank for `docs-policy-v1` has at least 20 entries after a one-week pilot.
4. The next compile run after a corrected example shows measurable confidence improvement on similar fragments.

---

## 10. Phase 4 — Production hardening (weeks 15–20)

Goal: deployable in a regulated production environment with multi-replica workers, secret management, backups, and SLOs.

### Deliverables

1. **Helm chart.** `riverbank/helm/` deploys the worker, Prefect server, Langfuse, and Label Studio onto Kubernetes. The chart depends on the existing `pg_ripple` chart.
2. **Multi-replica workers.** Workers acquire fragment-level advisory locks via PostgreSQL (`pg_try_advisory_lock(hashtext(fragment_iri)::bigint)`) and skip locked fragments. Combined with the `runs` idempotency key (fragment_id + profile_id + content_hash), this prevents duplicate work without a separate coordinator.
3. **Prometheus metrics.** A `/metrics` endpoint exposes: `riverbank_runs_total{outcome=...}`, `riverbank_run_duration_seconds`, `riverbank_llm_cost_usd_total`, `riverbank_shacl_score{graph=...}`, `riverbank_review_queue_depth`. A Perses dashboard ships in `riverbank/perses/`.
4. **Backups.** The catalog tables back up via standard PostgreSQL `pg_dump` along with the existing pg_ripple data. The `_riverbank.log` table is the recovery key — replaying it reconstructs the compilation state.
5. **Secret management.** LLM API keys load from environment variables, Kubernetes Secrets, or HashiCorp Vault (via `hvac`). No secret is ever logged.
6. **Rate limiting & circuit breakers.** Per-provider concurrency limits and a circuit breaker (using `aiobreaker`) protect against runaway LLM costs when an upstream API misbehaves.
7. **Audit trail.** Every operation that mutates the compiled graph writes to `_riverbank.log` with operator/agent identifier. The log is append-only at the database level (`REVOKE UPDATE, DELETE`).
8. **Bulk reprocessing.** `riverbank recompile --profile docs-policy-v1 --version 2` scans all sources compiled with v1, queues them for recompilation against v2, and produces a semantic diff report when complete.
9. **Cost dashboard.** Perses panels for cost per source, cost per profile, cost trend over time, and projected monthly spend at current rate.
10. **OpenTelemetry export.** `OTEL_EXPORTER_OTLP_ENDPOINT` routes traces to any collector (Jaeger, Tempo, Honeycomb-OSS).

### Acceptance (load test)

- Three worker replicas process 10,000 fragments/hour on a 4-node Kubernetes cluster.
- A simulated 1-hour LLM outage triggers the circuit breaker; on recovery, queued fragments process without manual intervention.
- A planned Helm upgrade rolls workers without dropping in-flight runs (drained via `pg_advisory_unlock` on SIGTERM).

---

## 11. Phase 5 — Advanced epistemic features (weeks 21–28)

Goal: implement the §10.12, §10.13, §10.17, §10.18 features from the parent plan that distinguish this from a generic compiler.

### Deliverables

1. **Negative knowledge.** `pgc:NegativeKnowledge` records for explicit denials, exhaustive search failures, and superseded facts. The compiler profile can declare "search-and-record-absence" rules per predicate.
2. **Argument graphs.** A `pgc:ArgumentRecord` extractor with a Label Studio annotation template for {claim, evidence, objection, rebuttal} spans. Used for compliance and policy corpora.
3. **Assumption registry.** Extracted assumptions attached as RDF-star annotations to facts; surfaced by `rag_context()`.
4. **Epistemic status layer.** Every fact gets a `pgc:epistemicStatus` annotation: `observed`, `extracted`, `inferred`, `verified`, `deprecated`, `normative`, `predicted`, `disputed`, `speculative`. Status flows from compiler outcome (`extracted`), Datalog inference (`inferred`), and Label Studio decisions (`verified`).
5. **Model ensemble compilation.** Per-profile opt-in; runs N model variants and routes disagreements to Label Studio with a side-by-side template. Hard cost cap configurable per profile.
6. **Minimal contradiction explanation.** A `riverbank explain-conflict <iri>` command computes the smallest set of facts and rules producing a contradiction, using a SAT-style minimal-cause algorithm over the inference dependency graph.
7. **Coverage maps.** A daily flow computes per-topic source density, mean confidence, and unanswered-question count; results write to `pgc:CoverageMap` triples surfaced by `rag_context()`.

### Acceptance

1. An expert annotating an argument graph in Label Studio produces a `pgc:ArgumentRecord` with claim, two evidence nodes, one objection, and one rebuttal — all queryable in SPARQL.
2. A contradiction in the test corpus produces an explanation with three facts and one rule; the explanation matches a hand-verified expected answer.
3. Ensemble compilation with 3 models on 100 fragments produces a measurable reduction in extraction error rate vs single-model baseline (verified against golden corpus).

---

## 12. Phase 6 — Multi-tenant, federated, prose generation (weeks 29–36)

Goal: deploy as shared infrastructure across multiple knowledge bases; render compiled knowledge back to prose.

### Deliverables

1. **Multi-tenant catalog.** All catalog tables gain a `tenant_id` column with row-level security. Per-tenant editorial policies, profiles, and named graphs.
2. **Tenant-scoped Label Studio.** One Label Studio organisation per tenant; reviewer assignments respect tenant boundaries.
3. **Federated compilation.** A "remote profile" type pulls SERVICE-federated triples from a peer pg_ripple instance into a local compilation context, applies confidence weighting, and writes the result locally.
4. **Markdown / JSON-LD page rendering.** A `pgc render` command generates entity pages, topic surveys, comparison tables, and change digests from compiled artifacts. Output formats: Markdown (for Obsidian/MkDocs), JSON-LD (for downstream graphs), HTML (for direct hosting).
5. **Render scheduling.** Pages are stored as `pgc:RenderedPage` artifacts with dependency edges to their source facts. When facts change, pages are flagged stale and regenerated in the next render flow.
6. **Streaming render.** SSE endpoint that emits page updates as the underlying graph changes, for live documentation sites.

### Acceptance

1. Two tenants can compile independently against the same physical PostgreSQL with no data leakage (verified by row-level security tests).
2. `riverbank render --format markdown --target docs/` produces a navigable MkDocs site of entity pages with citations linking back to source fragments.
3. Modifying one fact regenerates exactly the pages that depend on it.

---

## 13. Operational topologies

Three supported deployment shapes:

### 13.1 Single-binary local

For development and CI: `pip install riverbank[ollama]` and `riverbank serve`. Uses SQLite for catalog (no PostgreSQL required) and `tap-files` for ingest. Trades durability for setup speed.

### 13.2 Single-VM with Docker Compose

For small teams: the `docker-compose.yml` from Phase 1, scaled to one VM (4 vCPU, 16 GB RAM). All services on one host. PostgreSQL with pg_ripple is the source of truth; everything else can be re-created from configuration. Backup is `pg_dump` + the YAML profile files in version control.

### 13.3 Kubernetes (production)

For organisational deployments: the Helm chart from Phase 4. Components:

| Service | Replicas | Notes |
|---|---|---|
| pg_ripple (PostgreSQL with extension) | 1 primary + 2 replicas | CloudNativePG operator recommended |
| pg_ripple_http | 2+ | Existing companion |
| pg-tide | 2+ | HA via advisory locks; no external coordinator needed |
| riverbank worker | 3+ | Horizontal autoscaling on queue depth |
| Prefect server | 1 | State in PostgreSQL (introduced Phase 2) |
| Langfuse web + worker | 2 + 1 | Requires PostgreSQL (shared) and ClickHouse for traces |
| Label Studio | 1 | Backed by PostgreSQL (shared) |
| Ollama (optional) | 1 with GPU | For local-model deployments; cloud LLM provider also supported |
| Prometheus + Perses | 1 + 1 | Metrics and dashboards (Apache 2.0) |

Total minimum production footprint without GPU: ~12 vCPU, 32 GB RAM.

---

## 14. Testing strategy

### 14.1 Unit tests

Pure-function tests for the parser plugins, fragmenters, ingest gate logic, and the artifact dependency resolver. Target ≥ 90% line coverage on the `riverbank/src/` tree.

### 14.2 Integration tests

`testcontainers-python` brings up PostgreSQL with pg_ripple, an Ollama sidecar with a small fixed model, and the worker. Tests assert end-to-end behaviour:

- Ingest produces expected triples
- Re-ingest skips unchanged fragments
- Schema rejection blocks malformed output
- Citation grounding rejects fabricated quotes
- SHACL gate routes correctly

Tests run in CI on every PR. Total runtime budget: < 10 minutes.

### 14.3 Golden corpus

`tests/golden/` holds a small hand-curated Markdown corpus with expected SPARQL `ASK` and `SELECT` results. A profile change, model upgrade, or pg_ripple version bump that breaks a golden assertion is a CI failure.

### 14.4 Property-based tests

Hypothesis-based property tests for the fragmenter (round-trip stability of `content_hash` under whitespace perturbations) and the citation grounding validator (no false positives when the quote matches).

### 14.5 Load tests

`locust` scenarios in `tests/load/` simulate batch ingest of 10,000 fragments. Performance regressions are tracked over time in the same CSV format the existing pg_ripple benchmarks use.

### 14.6 Chaos tests

A Phase 4 scenario kills the LLM endpoint mid-run; the worker should recover, the circuit breaker should engage, and queued fragments should resume on recovery.

---

## 15. Extensibility recipes

### 15.1 Adding a new connector

```python
# my_company/riverbank_jira.py
class JiraConnector:
    name = "jira"
    def discover(self, config): ...
    def fetch(self, source): ...

# pyproject.toml
[project.entry-points."riverbank.connectors"]
jira = "my_company.riverbank_jira:JiraConnector"
```

`pip install my-company-riverbank-jira` and the connector is available — no fork of riverbank required.

**Alternative 1: pg-tide for message-queue sources.** If the source system publishes to Kafka, NATS, Redis Streams, SQS, or RabbitMQ, configure a pg-tide reverse pipeline via SQL instead of writing a Python connector:

```sql
SELECT pgtide.set_inbox('jira-events',
    config => '{"source_type": "kafka",
                "kafka_brokers": "localhost:9092",
                "kafka_topic": "jira-changes",
                "inbox_table": "source_inbox"}'::jsonb);
SELECT pgtide.enable('jira-events');
```

The pg-tide binary writes directly to a pg-trickle inbox stream table. A riverbank flow watches the inbox and triggers compilation. No Python connector code is required.

**Alternative 2: pg-tide as a Singer target.** If a Singer tap already exists (e.g., `tap-jira` from Meltano Hub), pipe it directly to pg-tide as a Singer target instead of writing a Python wrapper:

```bash
tap-jira --config jira-config.json | pg-tide --target singer --config tide-singer.json
```

The pg-tide binary ingests the Singer protocol RECORD messages and writes directly to the pg-trickle inbox table. Ideal for leveraging existing Meltano taps without additional Python code.

### 15.2 Adding a new compiler profile

A YAML file in the `profiles/` directory:

```yaml
name: incident-reports
version: 1
schema:
  $ref: ./schemas/incident.json
prompt: |
  You are extracting structured incident reports …
editorial_policy:
  min_fragment_chars: 500
  required_topics: ["incident", "resolution", "action items"]
  language: en
model_provider: openai-compat
model_name: gpt-4o-mini
embedding_model: bge-small-en-v1.5
```

`riverbank profile register profiles/incident-reports.yaml` writes it to the catalog. Existing sources can opt in via `riverbank source set-profile <iri> incident-reports`.

### 15.3 Adding a new renderer

Phase 6 renderers live in `riverbank/renderers/`. A new renderer implements `Renderer.render(artifact_iri) -> bytes` and registers itself via the `riverbank.renderers` entry point. Output goes to a configurable target (filesystem, S3, HTTP push).

---

## 16. Risk register and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| LLM cost runaway | High | Cost cap per profile; circuit breaker; daily budget alarm; cost dashboard panel |
| Hallucinated facts entering trusted graph | High | Citation grounding at write time; SHACL gate; ingest-gate quarantine; review queue with active-learning prioritisation |
| Catalog/graph drift after partial failure | Medium | All compile operations write to `_riverbank.log` first; replay on recovery; advisory-lock-based idempotency |
| Plugin compatibility breakage | Medium | Plugin protocol versioning; conformance test suite plugins must pass; semantic versioning of the plugin API |
| Self-hosted Langfuse / Label Studio drift | Medium | Pin to specific tags; integration tests against the pinned versions in CI |
| Ollama model determinism in CI | Low | Fixed seed, temperature 0; record model digest in run; fail CI on digest change without explicit approval |
| Kubernetes deployment complexity | Medium | Phase 1–3 must work without Kubernetes; the Helm chart is additive, not required |
| Prompt injection from user-provided sources | High | Already covered by the parent plan §15; the implementation enforces it via the ingest gate, schema validator, and quarantine graph |

---

## 17. Rollout and success criteria

### 17.1 Internal pilot (end of Phase 1)

Compile pg_ripple's own documentation corpus (`docs/src/**/*.md`). Demonstrate:
- ≥ 80% fragment skip rate on re-ingest
- ≥ 95% of facts carry valid evidence spans
- LLM cost per full compile < $5 with `gpt-4o-mini` or $0 with Ollama
- Query "which migrations affect the dictionary table?" returns correct answer

### 17.2 First external pilot (end of Phase 3)

A single external corpus (e.g., a partner's compliance documentation). Demonstrate:
- A reviewer can correct 50 facts in Label Studio in under an hour
- Corrections measurably improve extraction quality on the next run (verified by example bank)
- Cost dashboard accurately attributes spend per source

### 17.3 Production-ready (end of Phase 4)

Self-service deployment via Helm. SLOs:
- Worker availability ≥ 99.5% over a rolling 30-day window
- p95 fragment-to-graph latency < 30 seconds
- Mean time to recover from LLM outage < 5 minutes
- Catalog backup and restore verified via quarterly drill

### 17.4 Differentiated product (end of Phase 5)

Demonstrable advantages over generic RAG and over flat-file LLM-wiki implementations on:
- Multi-hop questions (golden benchmark vs vector RAG)
- Contradiction detection (recall vs flat-file synthesis)
- Change-awareness (response time to source updates)
- Auditability (full provenance trail per fact)

### 17.5 Platform (end of Phase 6)

Multi-tenant deployment supports ≥ 10 independent knowledge bases on shared infrastructure. Markdown rendering produces publishable documentation sites that auto-update on graph changes.

---

## 18. Sequencing summary

| Weeks | Phase | Deliverable headline |
|---|---|---|
| 1 | 0 | Skeleton, `docker compose up` runs |
| 2–6 | 1 | MVP — Markdown corpus → triples with citations and confidence |
| 7–10 | 2 | Incremental compilation; PDF/DOCX; Singer connectors |
| 11–14 | 3 | Label Studio review loop; lint flow; example bank |
| 15–20 | 4 | Helm chart; multi-replica; Prometheus/Grafana; backups |
| 21–28 | 5 | Argument graphs; ensemble; contradiction explanations |
| 29–36 | 6 | Multi-tenant; federated; prose rendering |

Each phase ends with a tagged release and a demo. Phases 1–3 are sequential dependencies; Phases 4 and 5 can overlap; Phase 6 is independent of 5 and can start in parallel once Phase 4 is deployable.

---

## 19. Recommended next steps

1. Create the `riverbank/` directory and Phase 0 scaffolding in a single PR.
2. Land the catalog migrations and the no-op flow.
3. Stand up the `docker-compose.yml` and verify Langfuse + Prefect are reachable.
4. Implement the markdown parser and heading fragmenter as the first plugins.
5. Implement the Instructor extractor with the `EvidenceSpan` validator.
6. Run the first end-to-end compile against `docs/src/` and tag `riverbank-v0.1.0`.

The MVP exit criterion is the strongest demo: change one paragraph in one Markdown file, watch exactly one fragment recompile, see exactly the affected facts update in the SPARQL query result, and observe the semantic event arrive on the pg_trickle outbox — end-to-end in under a second.
