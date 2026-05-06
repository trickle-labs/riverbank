# Compiler profile schema

Complete YAML schema for compiler profiles. Every field, its type, whether required, default, and an example.

## Annotated example (`docs-policy-v1`)

```yaml
name: docs-policy-v1              # Required. Unique profile identifier.
version: 1                         # Required. Integer version number.
extractor: noop                    # Required. Entry point name for the extractor plugin.
model_provider: ollama             # Optional. LLM provider. Default: from global config.
model_name: llama3.2               # Optional. Model identifier. Default: from global config.
embed_model: nomic-embed-text      # Optional. Embedding model. Default: from global config.
max_fragment_tokens: 2000          # Optional. Max tokens per fragment. Default: 2000.
named_graph: "http://riverbank.example/graph/trusted"  # Optional. Target graph. Default: trusted.

run_mode_sequence: [full]          # Optional. Pass order. Default: [full].

prompt_text: |                     # Optional. System prompt for extraction.
  Extract factual claims as RDF triples.

editorial_policy:                  # Optional. Fragment filtering rules.
  min_fragment_length: 50
  max_fragment_length: 8000
  min_heading_depth: 0
  confidence_threshold: 0.7
  allowed_languages: [en]

absence_rules: []                  # Optional. Negative knowledge rules.

competency_questions: []           # Optional. SPARQL regression tests.

ensemble: null                     # Optional. Multi-model ensemble config.
```

## Field reference

### Top-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | yes | — | Unique profile identifier. Used in CLI and catalog. |
| `version` | int | yes | — | Integer version. Profiles are upserted by `(name, version)`. |
| `extractor` | string | yes | — | Entry point name: `noop`, `instructor`, or custom. |
| `model_provider` | string | no | global config | `ollama`, `openai`, `anthropic`, `vllm`, `azure-openai` |
| `model_name` | string | no | global config | Model identifier (e.g., `gpt-4o`, `llama3.2`) |
| `embed_model` | string | no | global config | Embedding model (e.g., `nomic-embed-text`) |
| `max_fragment_tokens` | int | no | `2000` | Maximum tokens per fragment sent to LLM |
| `named_graph` | string | no | `http://riverbank.example/graph/trusted` | Target named graph IRI |
| `run_mode_sequence` | list[string] | no | `[full]` | Pass order: `vocabulary`, `full` |
| `prompt_text` | string | no | built-in | System prompt guiding extraction |

### `editorial_policy`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `min_fragment_length` | int | no | `50` | Skip fragments shorter than this (characters) |
| `max_fragment_length` | int | no | `8000` | Flag fragments longer than this |
| `min_heading_depth` | int | no | `0` | Skip headings above this depth (0 = all) |
| `confidence_threshold` | float | no | `0.7` | Below this → draft graph |
| `allowed_languages` | list[string] | no | `[en]` | ISO language codes |

### `absence_rules`

List of rules for generating `pgc:NegativeKnowledge` records.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `predicate` | string | yes | Full predicate IRI to check for absence |
| `summary` | string | yes | Human-readable explanation of the absence |

### `competency_questions`

List of SPARQL assertions the compiled graph must satisfy.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique identifier (e.g., `cq-01`) |
| `description` | string | no | Human-readable description |
| `sparql` | string | yes | SPARQL ASK or SELECT query |

### `ensemble`

Multi-model ensemble configuration for higher extraction accuracy.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `models` | list[object] | yes | List of model configurations |
| `models[].provider` | string | yes | LLM provider |
| `models[].model` | string | yes | Model identifier |
| `models[].weight` | float | yes | Weight in merge (0.0–1.0) |
| `strategy` | string | no | Merge strategy: `weighted_merge`, `majority_vote` |
| `min_agreement` | float | no | Minimum agreement threshold |
