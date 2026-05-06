# Explain a conflict

When your knowledge graph contains contradictory facts, `riverbank explain-conflict` identifies the minimal set of sources responsible.

## Basic usage

```bash
riverbank explain-conflict http://example.org/entity/Acme
```

## What it computes

The command wraps `pg_ripple.explain_contradiction()`, which performs:

1. **Contradiction detection** — finds facts about the entity that are mutually inconsistent (e.g., two different values for a functional property)
2. **Minimal hitting set** — computes the smallest subset of source fragments whose removal would resolve the contradiction (SAT-style reasoning over the inference dependency graph)
3. **Explanation** — returns the conflicting claims, their sources, and a suggested resolution path

## Example output

```
riverbank explain-conflict  iri='http://example.org/entity/Acme'

┌─────────────────────────────────────┐
│ Contradiction explanation           │
├──────────────┬──────────────────────┤
│ Role         │ IRI / Value          │
├──────────────┼──────────────────────┤
│ claim_a      │ Acme founded in 1995 │
│ claim_b      │ Acme founded in 1997 │
│ source_a     │ doc/history.md#p3    │
│ source_b     │ doc/overview.md#p1   │
│ resolution   │ Remove one source    │
└──────────────┴──────────────────────┘
```

## Resolving conflicts

Two resolution paths:

### 1. Correct the source

Fix the incorrect source document and re-ingest:

```bash
# Edit the source file, then:
riverbank ingest /path/to/corrected-doc.md
```

### 2. Record as negative knowledge

If one claim is explicitly false, record it as `pgc:NegativeKnowledge`:

```sparql
INSERT DATA {
  GRAPH <http://riverbank.example/graph/trusted> {
    _:nk a pgc:NegativeKnowledge ;
         pgc:aboutSubject <http://example.org/entity/Acme> ;
         pgc:negatedPredicate <http://example.org/foundedIn> ;
         pgc:negatedValue "1997" ;
         pgc:reason "Contradicted by primary source (company registry)" .
  }
}
```

## When no contradiction is found

If `explain-conflict` returns no results:

- The entity may not have contradictory facts
- `pg_ripple.explain_contradiction()` may not be available in your pg-ripple version
- The named graph may not contain the entity (check with `--graph`)
