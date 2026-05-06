# Development setup

## Prerequisites

- Python 3.12+
- Docker with Compose v2
- `uv` (recommended) or pip
- Git

## Clone and install

```bash
git clone https://github.com/trickle-labs/riverbank.git
cd riverbank
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

The `-e .` (editable install) is required for plugin entry points to resolve correctly.

## Configure environment

Copy the example environment file:

```bash
cp .env.example .env
```

Defaults use local Ollama (no API key required). For other providers, set:

```bash
export RIVERBANK_LLM__PROVIDER=openai
export RIVERBANK_LLM__API_KEY="sk-..."
```

Or create `~/.riverbank/config.toml`:

```toml
[llm]
provider = "openai"
api_key = "sk-..."
model = "gpt-4o"
```

## Start backing services

```bash
docker compose up -d postgres pg_tide ollama langfuse
```

## Apply schema migrations

```bash
riverbank init
```

## Verify

```bash
riverbank health
```

## Code quality tools

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/riverbank/

# All tests
pytest tests/ -v
```

## IDE setup

The project uses:

- **ruff** for linting and formatting (config in `pyproject.toml`)
- **mypy** for type checking
- **pytest** with `asyncio_mode = "auto"`

VS Code settings are not committed — configure your own `settings.json` with the Python extension pointing to `.venv/bin/python`.
