# Compile a runbook corpus

This tutorial uses the `procedural-v1` profile to compile incident-response runbooks into a knowledge graph with step sequences, preconditions, and error-handling paths.

## Scenario

Your team maintains a set of runbooks for incident response. You want to compile them into structured procedural knowledge so that an AI assistant can answer questions like "what is the rollback path for step X?" or "which steps require admin access?" without re-reading the raw Markdown every time.

## Prerequisites

- riverbank installed with `[dev]` extras
- Docker Compose stack running
- `riverbank init` completed

## Step 1: Register the procedural profile

```bash
riverbank profile register examples/profiles/procedural-v1.yaml
```

The `procedural-v1` profile differs from `docs-policy-v1` in several ways:

- **`run_mode_sequence: [vocabulary, full]`** — runs a vocabulary pass first (extracts `skos:Concept` triples), then a full extraction pass. This ensures entity references snap to canonical IRIs.
- **PKO predicates** — the prompt instructs the extractor to use Procedural Knowledge Ontology predicates: `pko:nextStep`, `pko:previousStep`, `pko:nextAlternativeStep`, `pko:hasPrecondition`, `pko:requiresExpertiseLevel`, `pko:hasErrorHandlingPath`
- **Absence rules** — explicitly records when a step has no error-handling path (`pgc:NegativeKnowledge`)

## Step 2: Ingest the runbooks

```bash
riverbank ingest examples/markdown-corpus/ --profile examples/profiles/procedural-v1.yaml
```

!!! note
    In a real deployment, you'd point this at your actual runbook directory. The example corpus demonstrates the pipeline mechanics.

## Step 3: Query step sequences

Find all step sequences:

```sparql
SELECT ?step ?nextStep
WHERE {
  ?step <http://procedural-knowledge.example/nextStep> ?nextStep .
}
ORDER BY ?step
```

```bash
riverbank query "SELECT ?step ?next WHERE { ?step <http://procedural-knowledge.example/nextStep> ?next } ORDER BY ?step"
```

## Step 4: Query rollback paths

```sparql
SELECT ?step ?alternative
WHERE {
  ?step <http://procedural-knowledge.example/nextAlternativeStep> ?alternative .
}
```

## Step 5: Query error-handling paths

```sparql
SELECT ?step ?errorPath
WHERE {
  ?step <http://procedural-knowledge.example/hasErrorHandlingPath> ?errorPath .
}
```

Steps without an error-handling path are recorded as `pgc:NegativeKnowledge` entries. Query them with:

```sparql
SELECT ?step ?absence
WHERE {
  ?absence a <https://pg-ripple.org/compile#NegativeKnowledge> ;
           <https://pg-ripple.org/compile#aboutSubject> ?step .
}
```

## Step 6: Verify competency questions

The profile defines five competency questions:

1. Defines at least one procedural step sequence
2. What happens if a step fails? (error-handling paths)
3. Which steps require admin access? (expertise level)
4. What is the rollback path? (alternative steps)
5. Contains at least one subject–predicate–object triple

Run the lint check to validate:

```bash
riverbank lint --shacl-only --threshold 0.7
```

## Why structured procedural knowledge beats search

A search index over the same runbooks would return the most similar chunks to your question — but it cannot guarantee structural completeness. With compiled procedural knowledge:

- You can traverse the step graph programmatically
- Missing error-handling paths are recorded explicitly (not silently absent)
- The AI assistant can answer "what comes after step 3?" without hallucinating
- Changes to one step automatically invalidate downstream dependency edges

## What you learned

- The `run_mode_sequence` field enables multi-pass compilation (vocabulary → full)
- PKO predicates create queryable step sequences
- Absence rules record explicit gaps via `pgc:NegativeKnowledge`
- Procedural knowledge enables reliable AI-assisted incident response
