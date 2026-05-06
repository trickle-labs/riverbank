# Quick start

This page gets you from zero to a working SPARQL query against a compiled knowledge graph. Every command below is tested in CI.

## Prerequisites

- Python 3.12+
- Docker with Compose v2
- Git

## Clone and install

=== "uv (recommended)"

    ```bash
    git clone https://github.com/trickle-labs/riverbank.git
    cd riverbank
    uv venv && source .venv/bin/activate
    uv pip install -e ".[dev]"
    ```

=== "pip"

    ```bash
    git clone https://github.com/trickle-labs/riverbank.git
    cd riverbank
    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    ```

## Start backing services

```bash
docker compose up -d postgres pg_tide ollama langfuse
```

This brings up:

- **PostgreSQL** with pg-ripple (RDF/SPARQL), pg-trickle (incremental views), and pgvector
- **pg-tide** — CDC relay sidecar for streaming semantic diffs
- **Ollama** — local LLM runtime
- **Langfuse** — LLM observability (optional)

## Initialise the catalog

```bash
riverbank init
```

This runs Alembic migrations to create the `_riverbank` schema: tables for sources, fragments, profiles, runs, artifact dependencies, and audit log entries.

## Verify the stack

```bash
riverbank health
```

You should see green checkmarks for all pg-trickle preflight checks and the pg-tide availability probe.

## Compile your first corpus

```bash
riverbank ingest examples/markdown-corpus/
```

This parses the example Markdown files, fragments them at heading boundaries, applies the editorial policy gate, and writes compiled triples to the knowledge graph.

## Query the result

```bash
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
```

You now have a compiled knowledge graph. Every fact traces back to the source fragment it was extracted from.

## Inspect the run

```bash
riverbank runs --since 1h
```

This shows the compilation run with outcome, token counts, cost estimate, and a Langfuse trace link.

---

## What's next?

- [First corpus](first-corpus.md) — understand what happened during that ingest run
- [Compile a policy corpus](../tutorials/compile-a-policy-corpus.md) — use a real compiler profile with competency questions
- [CLI reference](../reference/cli.md) — every subcommand and flag
