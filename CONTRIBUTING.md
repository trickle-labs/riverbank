# Contributing to riverbank

## Prerequisites

- Python 3.12+
- Docker with Compose v2 (`docker compose version`)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Local development setup

### 1. Clone and install

```bash
git clone https://github.com/trickle-labs/riverbank.git
cd riverbank

# With uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Installing with `-e .` is required so that the plugin entry points (`riverbank.parsers`, `riverbank.extractors`, etc.) are registered and discoverable at test time.

### 2. Configure your environment

```bash
cp .env.example .env
# Edit .env if needed — defaults use local Ollama (no API key required)
```

Or create `~/.riverbank/config.toml`:

```toml
[llm]
provider = "openai"
api_key  = "sk-..."
model    = "gpt-4o-mini"
```

Environment variables (`RIVERBANK_LLM__MODEL`, etc.) always take precedence over the config file.

### 3. Start backing services

```bash
docker compose up -d postgres pg_tide ollama langfuse
```

Wait for everything to be healthy:

```bash
docker compose ps
```

### 4. Apply schema migrations

```bash
riverbank init
```

### 5. Verify health

```bash
riverbank health
# Expected: "all systems nominal"
```

### 6. Pull a model into Ollama (first time only)

```bash
docker compose exec ollama ollama pull llama3.2
docker compose exec ollama ollama pull nomic-embed-text
```

## Running tests

```bash
# Unit tests only (no Docker required)
pytest tests/unit/

# Integration tests (requires Docker — uses testcontainers)
pytest tests/integration/

# Golden corpus tests
pytest tests/golden/

# Full suite with coverage
pytest --cov=riverbank --cov-report=term-missing
```

## Code quality

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

## Pull request workflow

1. Branch off `main`: `git checkout -b feat/<short-description>`
2. Write tests for your change (unit tests at minimum).
3. Run the full test suite locally.
4. Open a PR against `main`.
5. CI runs `pytest`, `ruff`, and `mypy` automatically.

## Adding a plugin

Plugins are registered via Python entry points in `pyproject.toml`. Each
plugin implements a small `Protocol` defined in `src/riverbank/plugin.py`.
See [plans/riverbank-implementation.md](plans/riverbank-implementation.md) §5
for the full protocol definitions and entry-point group names.

The five extension points are:

| Group | Protocol | Example |
|---|---|---|
| `riverbank.parsers` | `Parser` | `DoclingParser`, `MarkdownParser` |
| `riverbank.fragmenters` | `Fragmenter` | `HeadingFragmenter`, `PageFragmenter` |
| `riverbank.extractors` | `Extractor` | `InstructorExtractor` |
| `riverbank.connectors` | `Connector` | `FilesystemConnector`, `SingerTapConnector` |
| `riverbank.reviewers` | `Reviewer` | `LabelStudioReviewer` |

Third-party plugins live in their own packages and are registered by adding an
entry point — no changes to the core code are required.
