# Compile a policy corpus

This tutorial uses the `docs-policy-v1` profile to compile the example Markdown corpus into a governed knowledge graph, then validates the result with competency questions.

## Scenario

You have a set of internal documentation files and want to compile them into structured facts that your team can query with SPARQL. The compiler profile defines what gets extracted, what quality threshold is acceptable, and what questions the compiled graph must be able to answer.

## Prerequisites

- riverbank installed with `[dev]` extras
- Docker Compose stack running (`docker compose up -d`)
- `riverbank init` completed

## Step 1: Register the profile

```bash
riverbank profile register examples/profiles/docs-policy-v1.yaml
```

This registers the `docs-policy-v1` profile in the `_riverbank.profiles` table. The profile specifies:

- **Extractor:** `noop` (for CI; swap to `instructor` for real extraction)
- **Model:** `llama3.2` via Ollama
- **Confidence threshold:** 0.7
- **Named graph:** `http://riverbank.example/graph/trusted`

## Step 2: Review the profile

The profile at `examples/profiles/docs-policy-v1.yaml` contains:

```yaml
name: docs-policy-v1
version: 1
extractor: noop
model_provider: ollama
model_name: llama3.2
embed_model: nomic-embed-text
max_fragment_tokens: 2000
named_graph: "http://riverbank.example/graph/trusted"

prompt_text: |
  Extract factual claims from documentation as RDF triples.
  For each claim provide: subject, predicate, object_value, confidence, evidence.
  Only extract claims directly supported by the text. Do NOT fabricate evidence.

editorial_policy:
  min_fragment_length: 50
  max_fragment_length: 8000
  min_heading_depth: 0
  confidence_threshold: 0.7
  allowed_languages: [en]

competency_questions:
  - id: cq-01
    description: "The corpus defines a concept called 'Confidence'"
    sparql: ASK { ?s ?p "Confidence" . }
  - id: cq-02
    description: "The corpus mentions evidence spans with character offsets"
    sparql: ASK { ?s ?p ?o . FILTER(CONTAINS(STR(?o), "character")) }
  - id: cq-03
    description: "The corpus contains at least one subject–predicate–object triple"
    sparql: ASK { ?s ?p ?o . }
```

The **competency questions** are SPARQL assertions that the compiled graph must satisfy. They function as regression tests for knowledge quality.

## Step 3: Ingest the corpus

```bash
riverbank ingest examples/markdown-corpus/ --profile examples/profiles/docs-policy-v1.yaml
```

The pipeline will:

1. Discover the three Markdown files
2. Fragment each at heading boundaries
3. Apply the editorial policy gate (min 50 chars, max 8000 chars)
4. Skip unchanged fragments (hash check)
5. Extract triples using the configured extractor
6. Validate via SHACL and write to the named graph

## Step 4: Query the result

```bash
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 20"
```

To check a specific competency question:

```bash
riverbank query "ASK { ?s ?p ?o . }" --format json
```

## Step 5: Run the quality gate

```bash
riverbank lint --shacl-only --threshold 0.7
```

This exits with code 0 if the SHACL score meets or exceeds 0.7.

## Step 6: Validate in CI

The golden corpus tests validate the same pipeline in CI:

```bash
pytest tests/golden/ -v
```

These tests register the profile, ingest the example corpus, and assert the competency questions all pass.

## What you learned

- Compiler profiles control what gets extracted and how quality is measured
- Competency questions are SPARQL-based regression tests for your knowledge graph
- The `riverbank lint` command enforces quality gates in CI
- The golden corpus test suite validates the full pipeline end-to-end
