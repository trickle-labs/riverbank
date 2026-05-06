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

This parses the example Markdown files, fragments them at heading boundaries, and applies the editorial policy gate. The default profile uses a `noop` extractor (no LLM calls) so this completes instantly — you'll see it processes 17 fragments and skips 3 due to the quality gate, but writes 0 triples since extraction is disabled.

**What you've validated:** the full ingest pipeline works end-to-end — source discovery, fragmenting, gate evaluation, and database writes all function correctly.

**To enable real LLM extraction:**

1. Install ingest dependencies: `pip install 'riverbank[ingest]'`
2. Pull an LLM model: `ollama pull llama3.2`  
3. Use a profile with `extractor: instructor`: `riverbank ingest examples/markdown-corpus/ --profile examples/profiles/docs-policy-v1.yaml`

_Note: LLM extraction takes 5–10 minutes depending on your hardware. The quickstart uses `noop` by default for speed._

## Query the result

```bash
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
```

With the default profile (noop extractor), the graph is empty. After enabling LLM extraction, you'll have compiled triples that trace back to source fragments.

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
