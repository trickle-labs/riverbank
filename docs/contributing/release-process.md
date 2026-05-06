# Release process

How riverbank versions are managed, branched, and published.

## Versioning

riverbank follows [Semantic Versioning](https://semver.org/):

- **Major** (1.0.0) — breaking API changes
- **Minor** (0.9.0) — new features, backward-compatible
- **Patch** (0.9.1) — bug fixes only

The version is defined in `pyproject.toml`:

```toml
[project]
version = "0.9.0"
```

## Branching strategy

- **`main`** — stable, all tests pass, deployable
- **`release/vX.Y.Z`** — release preparation branch
- **Feature branches** — short-lived, merged to `main` via PR

## Release steps

1. **Create a release branch:**
   ```bash
   git checkout -b release/v0.10.0
   ```

2. **Bump the version** in `pyproject.toml`

3. **Update the changelog** in `docs/reference/changelog.md`

4. **Run the full test suite:**
   ```bash
   pytest tests/ -v
   ```

5. **Push and create a PR:**
   ```bash
   git push -u origin release/v0.10.0
   gh pr create --title "release: v0.10.0" --base main
   ```

6. **Merge after CI passes**

7. **Tag the release:**
   ```bash
   git tag v0.10.0
   git push --tags
   ```

8. **CI publishes:**
   - Docker image to `ghcr.io/trickle-labs/riverbank:0.10.0`
   - Documentation site updated (via `mike deploy`)

## CI checks

Every PR must pass:

- Unit tests
- Golden corpus tests
- Integration tests (testcontainers)
- `ruff check` (lint)
- `ruff format --check` (formatting)

## Documentation versioning

The docs site uses `mike` for versioned documentation:

- Each tagged release gets a versioned snapshot at `/<version>/`
- The `latest` alias always points to the most recent release
- Operators pinned to a specific version can find matching docs
