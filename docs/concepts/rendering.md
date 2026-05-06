# Rendering

Rendering transforms compiled knowledge back into human-readable pages — Markdown, JSON-LD, or HTML — that can be published as documentation or fed to other systems.

## How it works

`riverbank render` fetches all facts about an entity from the named graph and produces a formatted page:

```bash
riverbank render http://example.org/entity/Acme --format markdown --target docs/knowledge/
```

## Output formats

| Format | Use case |
|--------|----------|
| `markdown` | MkDocs sites, Obsidian vaults, GitHub wikis |
| `jsonld` | Machine-readable export, API responses |
| `html` | Standalone pages, email reports |

## Page structure (Markdown)

A rendered Markdown page contains:

1. **Title** — entity label or IRI
2. **Summary** — key properties in a table
3. **Relationships** — connected entities with predicates
4. **Citations** — source fragments with evidence spans
5. **Provenance footer** — compilation timestamp, profile, confidence

## Dependency tracking

Each rendered page is stored as a `pgc:RenderedPage` artifact with dependency edges to its source facts:

```turtle
<http://example.org/rendered/acme> a pgc:RenderedPage ;
    pgc:dependsOn <http://example.org/fact/acme-produces-widgets> ;
    pgc:dependsOn <http://example.org/fact/acme-founded-1995> ;
    pgc:renderedAt "2024-12-01T10:30:00Z"^^xsd:dateTime ;
    pgc:format "markdown" .
```

When source facts change, the rendered page is stale and can be regenerated.

## Integration with MkDocs

Rendered pages in `docs/knowledge/` are picked up automatically by the `mkdocs-gen-files` plugin. No manual navigation entries needed.

## The `--persist` flag

By default, `riverbank render` writes the `pgc:RenderedPage` artifact back to the graph. Use `--no-persist` to render without recording:

```bash
riverbank render http://example.org/entity/Acme --no-persist
```

## Bulk rendering

Render all entities:

```bash
for iri in $(riverbank query "SELECT DISTINCT ?s WHERE { ?s a ?type }" --format csv | tail -n +2); do
  riverbank render "$iri" --format markdown --target docs/knowledge/
done
```
