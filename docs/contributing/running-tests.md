# Running tests

riverbank has three test suites with different requirements.

## Unit tests

Fast, no external dependencies. Run in CI on every push.

```bash
pytest tests/unit/ -v
```

Unit tests cover:

- Configuration parsing
- Pipeline logic (mocked extractors)
- Plugin discovery
- Profile parsing
- Fragment hashing
- Editorial policy gates
- Cost calculations
- CLI command parsing

## Golden corpus tests

Validate the full pipeline against the example corpus using the `noop` extractor. No database required.

```bash
pytest tests/golden/ -v
```

Golden tests verify:

- Profile registration
- Corpus ingestion with the noop extractor
- Competency question assertions
- Fragment deduplication

## Integration tests

Require a running PostgreSQL instance (via testcontainers). Test real database operations.

```bash
pytest tests/integration/ -v
```

Integration tests cover:

- Alembic migrations
- Graph writes via pg-ripple
- SPARQL queries
- Advisory locks
- Tenant RLS
- Audit logging

### Running with testcontainers

Integration tests use `testcontainers[postgres]` to spin up a temporary PostgreSQL instance:

```bash
export TESTCONTAINERS_RYUK_DISABLED=true
pytest tests/integration/ -v
```

## All tests

```bash
pytest tests/ -v --tb=short
```

## Coverage

```bash
coverage run -m pytest tests/
coverage report --show-missing
```

## Writing tests

- Place unit tests in `tests/unit/test_<module>.py`
- Use fixtures from `tests/conftest.py`
- Mock external dependencies (database, LLM) in unit tests
- Integration tests can use real database connections via testcontainers
- Golden tests should be self-contained (no external state)
