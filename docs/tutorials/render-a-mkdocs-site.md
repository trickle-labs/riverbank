# Render a MkDocs site

This tutorial shows how to use `riverbank render` to generate Markdown pages from your compiled knowledge graph and publish them as a documentation site via GitHub Actions.

## Scenario

You've compiled a corpus into a knowledge graph and want to publish entity pages and topic surveys as a browsable site — automatically rebuilt whenever the graph changes.

## Prerequisites

- riverbank installed with `[dev,docs]` extras
- A compiled knowledge graph (run `riverbank ingest` first)
- Git repository with GitHub Actions enabled

## Step 1: Render entity pages

```bash
riverbank render http://example.org/entity/Acme --format markdown --target docs/knowledge/
```

This fetches all facts about the entity from the named graph and produces a Markdown page at `docs/knowledge/acme.md` with:

- A summary section with key properties
- A relationships section showing connected entities
- A citations section linking back to source fragments
- A provenance footer with compilation timestamp and profile

## Step 2: Render multiple entities

To render all entities in the graph, use a script:

```bash
for iri in $(riverbank query "SELECT DISTINCT ?s WHERE { ?s a ?type }" --format csv | tail -n +2); do
  riverbank render "$iri" --format markdown --target docs/knowledge/
done
```

Each rendered page is stored as a `pgc:RenderedPage` artifact with dependency edges to its source facts. When facts change, stale pages can be detected and regenerated.

## Step 3: Configure MkDocs to pick up rendered pages

The `mkdocs-gen-files` plugin automatically includes files under `docs/knowledge/` in the site navigation. No manual nav entries needed.

Add to your `mkdocs.yml`:

```yaml
plugins:
  - gen-files:
      scripts:
        - docs/gen_ref_pages.py
```

## Step 4: Set up GitHub Actions

Create `.github/workflows/docs.yml`:

```yaml
name: docs
on:
  push:
    branches: [main]
    tags: ["v*"]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[docs]"
      - run: mkdocs build --strict
      - run: mkdocs gh-deploy --force
        if: github.ref == 'refs/heads/main'
```

The `--strict` flag fails on broken links, undefined references, or unparseable Mermaid diagrams.

## Step 5: Verify locally

```bash
mkdocs serve
```

Open `http://localhost:8000` and navigate to the Knowledge section. You should see your rendered entity pages alongside the handwritten documentation.

## The feedback loop

This creates a virtuous cycle:

1. Improve your source documents
2. Re-ingest with `riverbank ingest`
3. Re-render with `riverbank render`
4. The documentation site updates automatically

The rendered pages validate that `riverbank render` works correctly — a broken render fails the CI build and blocks the site publish.

## What you learned

- `riverbank render` produces Markdown from compiled knowledge
- Rendered pages carry dependency edges for staleness detection
- MkDocs picks up generated pages automatically via `mkdocs-gen-files`
- The `--strict` flag in CI catches broken links and references
- The documentation site is itself a product that improves when the graph improves
