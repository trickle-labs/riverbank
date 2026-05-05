# riverbank

riverbank is a Python worker and CLI for building a document-to-knowledge-graph pipeline on top of PostgreSQL. The project is aimed at a "knowledge compiler" workflow: parse source material, fragment it, run extraction, validate the result, and write governed graph data into pg-ripple while pg-trickle and pg-tide handle change propagation.

The repository is no longer just a plan. The current release, v0.1.0, ships the skeleton needed to stand up the local stack, initialize the catalog schema, verify the extension dependencies, and exercise the plugin architecture that later ingestion stages build on.

## Current status

riverbank is in the skeleton phase.

- Shipped in v0.1.0: Python package metadata, Docker-based local stack, Alembic migrations, catalog models, plugin entry points, configuration loading, and the initial CLI.
- Not shipped yet: end-to-end corpus ingest, graph writes, SPARQL query execution, review flows, and the incremental recompilation pipeline.
- Forward-looking work is tracked in [ROADMAP.md](ROADMAP.md), [plans/riverbank.md](plans/riverbank.md), and [plans/riverbank-implementation.md](plans/riverbank-implementation.md).

## What works today

The repository currently provides these concrete capabilities:

- `riverbank version` prints the installed package version.
- `riverbank config` shows resolved runtime settings from environment variables and optional TOML config.
- `riverbank init` applies the `_riverbank` catalog schema via Alembic migrations.
- `riverbank health` checks the local PostgreSQL stack by calling `pgtrickle.preflight()` and `pg_ripple.pg_tide_available()`.
- Plugin discovery is wired through Python entry points for parsers, fragmenters, extractors, connectors, and reviewers.

The shipped CLI also reserves the future command surface:

- `riverbank ingest` exists as a placeholder for the v0.2.0 ingestion pipeline.
- `riverbank query` exists as a placeholder for the v0.3.0 graph query interface.

## Local stack

The development stack in `docker-compose.yml` brings up the services riverbank depends on locally:

- PostgreSQL with pg-ripple preinstalled
- pg-tide as a relay sidecar
- Ollama for local OpenAI-compatible model access
- Langfuse for observability
- A `worker` container that runs the riverbank image

This gives the project a runnable deployment story before the higher-level ingestion features land.

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
riverbank version
```

If you use `uv`, the equivalent install flow is:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Configuration

Settings are loaded with this precedence:

1. Explicit initialization arguments
2. Environment variables with the `RIVERBANK_` prefix
3. `~/.riverbank/config.toml`, or the file pointed to by `RIVERBANK_CONFIG_FILE`

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

Example environment overrides:

```bash
export RIVERBANK_DB__DSN="postgresql+psycopg://riverbank:riverbank@localhost:5432/riverbank"
export RIVERBANK_LLM__PROVIDER="openai"
export RIVERBANK_LLM__MODEL="gpt-4o-mini"
```

## Project layout

The repository already includes the foundational pieces for later compiler stages:

- `src/riverbank/cli.py` contains the Typer-based CLI.
- `src/riverbank/config.py` defines nested runtime settings for database, LLM, and Langfuse configuration.
- `src/riverbank/catalog/models.py` defines the `_riverbank` catalog tables for profiles, sources, fragments, runs, artifact dependencies, and audit log entries.
- `src/riverbank/plugin.py` loads registered plugins from Python entry points.
- `src/riverbank/parsers`, `fragmenters`, `extractors`, `connectors`, and `reviewers` provide the initial built-in plugins.
- `tests/unit` and `tests/integration` cover configuration, plugin loading, no-op extraction, and migrations.

## Architecture direction

riverbank is being built around the idea that documents are source material and the graph is the compiled artifact. The intended runtime shape is:

```text
sources -> connectors -> parsers -> fragmenters -> extractors -> validation -> graph writes
                                      |
                                      v
                           _riverbank catalog + run metadata

PostgreSQL hosts the knowledge graph, validation, and change propagation layer.
```

Today, the repository implements the catalog, CLI, and service wiring for that architecture. The extraction, validation, and graph-writing stages are planned work rather than present functionality.

## Plugins

riverbank uses Python entry points so extension packages can register new components without patching the core package. The built-in groups are:

| Group | Built-in example |
|---|---|
| `riverbank.parsers` | `markdown` |
| `riverbank.fragmenters` | `heading` |
| `riverbank.extractors` | `noop` |
| `riverbank.connectors` | `filesystem` |
| `riverbank.reviewers` | `file` |

Install the package in editable mode with `pip install -e .` or `uv pip install -e .` if you want entry-point discovery to work in tests and local development.

## Roadmap

The short version of the roadmap is:

- v0.1.x: skeleton and deployment story
- v0.2.x: Markdown ingestion into pg-ripple with confidence and provenance
- v0.3.x: query surface, run inspection, and golden corpus gates
- v0.4.x+: incremental compilation, review workflows, and production hardening

For the detailed release plan, see [ROADMAP.md](ROADMAP.md).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full setup, test, and code-quality workflow.

Common commands:

```bash
pytest tests/unit/
pytest tests/integration/
ruff check src/ tests/
mypy src/
```

## Core dependencies

- [pg-ripple](https://github.com/trickle-labs/pg-ripple) for RDF storage and graph-side capabilities inside PostgreSQL
- [pg-trickle](https://github.com/trickle-labs/pg-trickle) for incremental dataflow infrastructure that later pipeline stages will rely on
- [pg-tide](https://github.com/trickle-labs/pg-tide) for relay and change-stream integration
- [Typer](https://github.com/fastapi/typer), [Pydantic](https://github.com/pydantic/pydantic), [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy), and [Alembic](https://github.com/sqlalchemy/alembic) for the current Python application layer

## License

[MIT](LICENSE)
