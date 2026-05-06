# Write a compiler profile

A compiler profile is the primary configuration surface for controlling what riverbank extracts and how quality is measured.

## Minimal profile

```yaml
name: my-profile
version: 1
extractor: noop
named_graph: "http://example.org/graph/trusted"
```

## Full profile with all fields

```yaml
name: docs-policy-v1
version: 1
extractor: noop
model_provider: ollama
model_name: llama3.2
embed_model: nomic-embed-text
max_fragment_tokens: 2000
named_graph: "http://riverbank.example/graph/trusted"

run_mode_sequence: [vocabulary, full]

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

absence_rules:
  - predicate: "http://example.org/hasErrorHandlingPath"
    summary: "No error-handling path found."

competency_questions:
  - id: cq-01
    description: "Contains at least one triple"
    sparql: ASK { ?s ?p ?o . }
```

## Register the profile

```bash
riverbank profile register path/to/my-profile.yaml
```

## Associate a source with a profile

```bash
riverbank source set-profile "http://example.org/source/docs" my-profile
```

## Design competency questions first

The most effective way to write a profile is to start with the questions your compiled graph must answer:

1. Write SPARQL ASK queries for each question
2. Put them in `competency_questions`
3. Run `pytest tests/golden/` to validate after each ingest

This is test-driven knowledge compilation.

## Multi-model ensemble profiles

For higher accuracy, configure multiple models and merge their outputs:

```yaml
name: ensemble-profile
version: 1
extractor: instructor
model_provider: openai
model_name: gpt-4o
ensemble:
  models:
    - provider: openai
      model: gpt-4o
      weight: 0.6
    - provider: anthropic
      model: claude-sonnet-4-20250514
      weight: 0.4
  strategy: weighted_merge
  min_agreement: 0.5
```

See the [compiler profile schema reference](../reference/compiler-profile-schema.md) for every field.
