# riverbed

**Turn raw documents into a governed, living knowledge graph — inside PostgreSQL.**

riverbed is a knowledge compilation system. It takes messy human-readable sources — Markdown files, PDFs, tickets, transcripts, API feeds — runs them through an LLM pipeline that extracts structured facts, relationships, and summaries, then stores the result as a validated RDF knowledge graph. From that point on, you query compiled knowledge rather than re-reading raw text on every request.

The key insight, borrowed from [Andrej Karpathy's LLM Wiki proposal](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): *documents are source code, and the knowledge graph is the compiled binary*. riverbed is the compiler.

---

## Why a compiler, not just RAG?

Standard RAG (retrieval-augmented generation) is fast to set up but has well-known limits. Chunks lose context. Similarity is not the same as correctness. Multi-document reasoning is fragile. Every query re-interprets the same raw prose.

Compilation does more work upfront so runtime is faster and more reliable:

| Compilation phase | What riverbed does |
|---|---|
| **Parse** | Read documents in any format (Markdown, PDF, HTML) |
| **Fragment** | Split into semantically coherent units |
| **Extract** | LLM workflow turns prose into structured entities, relationships, and confidence scores |
| **Validate** | SHACL shapes check quality; contradictions surface as first-class findings |
| **Write** | Facts land in a governed RDF graph with provenance and citations |
| **Maintain** | Only changed fragments recompile — not the whole corpus |
| **Publish** | Downstream systems receive structured change events the moment knowledge updates |

The incremental maintenance step is what makes the difference. riverbed doesn't re-index everything on a schedule. When a source document changes, only the knowledge derived from that document rebuilds — and only the downstream artifacts that depend on it refresh.

---

## What it is built on

riverbed is a Python project but its heavy lifting lives in two PostgreSQL extensions:

**[pg-ripple](https://github.com/trickle-labs/pg-ripple)** is the knowledge store. It provides a full RDF triple store with SPARQL 1.1, SHACL validation, Datalog inference, OWL 2 RL reasoning, vector search via pgvector, and GraphRAG export — all inside PostgreSQL. Highlights that riverbed relies on heavily:

- `load_triples_with_confidence()` — writes facts with extraction confidence scores
- `shacl_score()` / `shacl_report_scored()` — numeric quality gates, not just pass/fail
- `rag_context()` / `rag_retrieve()` — formats graph facts into LLM prompts; runs end-to-end RAG
- `sparql_from_nl()` — natural-language to SPARQL translation
- `suggest_sameas()`, `find_alignments()`, `pagerank_find_duplicates()` — entity deduplication without leaving the database
- `explain_pagerank()` — shows *why* an entity is considered important
- `erase_subject()` — GDPR right-to-erasure across all tables
- CONSTRUCT writeback rules — derived facts update automatically when source triples change

**[pg-trickle](https://github.com/trickle-labs/pg-trickle)** handles change propagation. It maintains SQL views incrementally using DBSP-inspired differential dataflow, so derived artifacts (entity pages, quality scores, topic indices) update in milliseconds rather than requiring full recomputation. Its `IMMEDIATE` refresh mode keeps SHACL score gates in sync within the same transaction as the write — the ingest gate decision is always based on current state.

**[pgtrickle-relay](https://github.com/trickle-labs/pg-trickle/tree/main/pgtrickle-relay)** is a standalone Rust binary that bridges pg-trickle with the outside world. It supports Kafka, NATS JetStream, Redis Streams, SQS, RabbitMQ, and HTTP webhooks — all configured via SQL. It also speaks the **Singer protocol** as a target, so any Singer tap can pipe directly to a pg-trickle inbox table without writing a Python connector:

```bash
tap-github --config github.json | pgtrickle-relay --target singer --config relay.json
```

---

## The three things you can do with a compiled knowledge graph

Once your documents are compiled, the full pg-ripple query layer is available:

**Query.** Ask structured questions with SPARQL, retrieve LLM-ready context with `rag_context()`, or use `sparql_from_nl()` to translate plain English to a graph query. Graph facts are grounded in cited sources — no hallucination about where a claim came from.

**Lint.** Run a scheduled health check across the compiled graph: find contradictions, stale claims, orphan entities, missing cross-references, and coverage gaps. Lint findings are first-class graph nodes, not log lines.

**Rank.** PageRank and centrality scoring (betweenness, eigenvector, Katz) tell you which entities are most important to your corpus. The review queue is sorted by `centrality × confidence` — you fix the highest-leverage entries first.

---

## Quick start

```bash
git clone https://github.com/trickle-labs/riverbed
cd riverbed
docker compose up          # Postgres + pg-ripple + pg-trickle + relay + worker + Prefect + Langfuse

riverbed init my-corpus
riverbed source add filesystem --path ./docs
riverbed run               # Compiles all sources
riverbed query "What are the main entities in this corpus?"
```

Everything runs locally. PostgreSQL is the only required dependency. Cloud LLM endpoints are optional — Ollama works out of the box for development.

---

## Project status

riverbed is at the **planning stage**. The plan documents in [`plans/`](plans/) describe the full architecture, phased implementation roadmap, and detailed engineering decisions. Implementation begins with the MVP phase (single-command corpus ingest, fragment-level incremental recompilation, SHACL quality gate, review queue).

---

## Plans

- [`plans/riverbed.md`](plans/riverbed.md) — Strategy document: the knowledge compiler analogy, what pg-ripple and pg-trickle provide, and the full feature vision
- [`plans/riverbed-implementation.md`](plans/riverbed-implementation.md) — Engineering blueprint: architecture diagram, phased roadmap, tech stack, extensibility recipes, and operational decisions

---

## Architecture overview

```
Sources (files, APIs, Kafka, NATS, Singer taps)
        │
  Connector plane (plugin or Singer tap → pgtrickle-relay)
        │
  pg-trickle inbox stream tables
        │
  riverbed worker
  ├── Parser → Fragmenter → Ingest gate
  └── LLM extraction → SHACL validation → Graph writer
        │
  pg-ripple (RDF graph, SPARQL, Datalog, PageRank, pgvector)
        │
  pg-trickle outbox → pgtrickle-relay
                       ├── NATS / Kafka / Redis / SQS
                       └── HTTP webhooks / downstream agents
```

---

## Built on the shoulders of

- [pg-ripple](https://github.com/trickle-labs/pg-ripple) — PostgreSQL RDF triple store (v0.88)
- [pg-trickle](https://github.com/trickle-labs/pg-trickle) — Incremental stream tables and event relay (v0.44)
- [Docling](https://github.com/DS4SD/docling) — Document parsing
- [Instructor](https://github.com/jxnl/instructor) — Structured LLM output
- [Prefect](https://github.com/PrefectHQ/prefect) — Workflow orchestration
- [Langfuse](https://github.com/langfuse/langfuse) — LLM observability
- [Label Studio](https://github.com/HumanSignal/label-studio) — Human review
- [Meltano Singer SDK](https://github.com/meltano/sdk) — Tap ecosystem

---

## License

[Apache 2.0](LICENSE)
