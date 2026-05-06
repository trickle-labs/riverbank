# Explain a compiled artifact

The `riverbank explain` command traces a compiled fact back to its source fragments, profile, and extraction run.

## Basic usage

```bash
riverbank explain http://example.org/entity/Acme
```

Output shows the dependency tree:

| Dependency kind | Reference |
|----------------|-----------|
| fragment | `http://example.org/source/docs#section-about-acme` |
| profile | `docs-policy-v1 v1` |
| run | `run-2024-12-01T10:30:00Z` |

## What the dependency tree tells you

- **Which fragments** contributed facts about this entity
- **Which profile** controlled the extraction rules
- **Which run** produced the current state
- **Fuzzy match candidates** — potential `owl:sameAs` links to other entities that might be duplicates

## Fuzzy match suggestions

When pg-ripple detects entities with similar labels, `riverbank explain` also shows:

```
Fuzzy match suggestions (owl:sameAs candidates)
  →  http://example.org/entity/ACME_Corp
  →  http://example.org/entity/Acme_Inc
```

These are computed by `pg_ripple.suggest_sameas()` using edit distance and token overlap.

## SPARQL equivalent

```sparql
SELECT ?dep_kind ?dep_ref
WHERE {
  <http://example.org/entity/Acme> <http://riverbank.example/ns/dependsOn> ?dep .
  ?dep <http://riverbank.example/ns/depKind> ?dep_kind ;
       <http://riverbank.example/ns/depRef> ?dep_ref .
}
```
