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

### `fragmenter` and `fragmenter_config`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `fragmenter` | string | no | `heading` | Entry point name: `heading`, `semantic`, `llm_statement`, `direct` |
| `fragmenter_config.min_heading_depth` | int | no | `1` | Minimum heading depth to split on |
| `fragmenter_config.max_heading_depth` | int | no | `6` | Maximum heading depth to split on |
| `fragmenter_config.overlap_sentences` | int | no | `0` | Sentences from the previous fragment to prepend |

### `llm_statement_fragmentation`

Only used when `fragmenter: llm_statement`. Sends the whole document to the LLM once and asks it to split it into individual statements before extraction.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `max_doc_chars` | int | no | `20000` | Maximum document characters sent to LLM |
| `max_statements` | int | no | `200` | Maximum statements to extract |
| `prompt` | string | no | — | Custom system prompt override (replaces default) |

### `extraction_focus`

Controls the precision-vs-recall trade-off at the extraction layer. Applied as a guidance block injected into the extraction prompt. Does not affect fragmentation.

| Value | Description |
|-------|-------------|
| `comprehensive` | All factual claims including strong inferences (default) |
| `high_precision` | Explicitly stated claims only; confidence ≥ 0.90; no inference |
| `facts_only` | Stated factual assertions only; excludes opinions, estimates, hedged language |

### `extraction_strategy`

Controls how triples are extracted and routed by confidence.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mode` | string | no | `conservative` | `conservative` or `permissive` (tiered confidence guidance) |
| `confidence_routing.trusted_threshold` | float | no | `0.75` | Confidence ≥ this → `graph/trusted` |
| `confidence_routing.tentative_threshold` | float | no | `0.35` | Confidence ≥ this → `graph/tentative`; below → discarded |
| `safety_cap` | int | no | `50` | Maximum triples per fragment; excess kept by confidence |
| `batch_size` | int | no | `0` | Group N fragments per LLM call (0 = disabled) |

### `distillation`

Optional pre-fragmentation document distillation step (v0.15.2). Runs immediately after parsing; the distilled text replaces the original for all downstream stages.

```yaml
distillation:
  enabled: true
  strategy: moderate            # boilerplate_removal | aggressive | moderate |
                                # conservative | section_aware | budget_optimized
  cache_dir: ~/.riverbank/distill_cache   # optional; created automatically
  model_provider: ollama        # optional dedicated model for distillation
  model_name: gemma3:4b         # optional; small fast model works well

  # For aggressive / moderate / conservative:
  target_size_bytes: 30720      # output size hint; default 10240/30720/0 per strategy

  # For section_aware:
  section_types:
    factual:      keep          # copy verbatim
    biographical: summarize     # LLM 2-3 sentence summary
    event:        keep
    reference:    remove        # omit entirely
    navigation:   remove
    caption:      remove

  # For budget_optimized:
  extraction_budget_usd: 1.00
  min_triple_target: 50
  sample_fragments: 3
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | no | `false` | Enable the distillation step |
| `strategy` | string | no | `moderate` | Distillation strategy (see below) |
| `cache_dir` | string | no | `~/.riverbank/distill_cache` | Directory for cached distillation outputs |
| `model_provider` | string | no | profile's `model_provider` | Override LLM provider for distillation |
| `model_name` | string | no | profile's `model_name` | Override model for distillation |
| `target_size_bytes` | int | no | strategy-dependent | Output size hint passed to LLM |
| `section_types` | map | no | — | Per-section-type actions for `section_aware` strategy |
| `extraction_budget_usd` | float | no | `1.00` | Cost ceiling for `budget_optimized` |
| `min_triple_target` | int | no | `50` | Minimum desired triples for `budget_optimized` |
| `sample_fragments` | int | no | `3` | Sample size for yield estimation in `budget_optimized` |

**Strategy values:**

| Strategy | LLM calls | Output size | Use when |
|---|---|---|---|
| `boilerplate_removal` | 0 | ~80–100% of content | Document is structured; just want clean input |
| `aggressive` | 1 | ~5–15 kB | Very large docs; only top-level facts needed |
| `moderate` | 1 | ~20–50 kB | Long articles; maximum triple yield (**recommended default**) |
| `conservative` | 1 | ~60–90% | Every paragraph may contain extractable facts |
| `section_aware` | 1–N | configurable | Structured docs with heterogeneous section types |
| `budget_optimized` | 0–1 | dynamic | Cost-constrained high-yield scenarios |

Cache files are named `<xxh3_128_hex>_<strategy>_<target_bytes>.md`. Re-ingesting an unchanged document costs zero LLM calls regardless of strategy.

### `preprocessing`

Controls LLM document preprocessing (entity catalog, document summary) run before extraction.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | no | `true` | Enable Phase 1 preprocessing |
| `max_tokens_for_preprocessing` | int | no | `4000` | Token budget for preprocessing call |
| `skip_preprocessing_below_chars` | int | no | `2000` | Skip preprocessing for short documents |
| `noise_filtering` | bool | no | `false` | Skip boilerplate sections identified by LLM |
| `coreference` | string | no | `disabled` | `llm`, `spacy`, or `disabled` |
| `merge_preprocessing_below_chars` | int | no | `4000` | Merge summary + catalog into one call for short documents |

### `verification`

Post-extraction self-critique pass for low-confidence triples.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | no | `false` | Enable the verification pass |
| `batch_size` | int | no | `5` | Low-confidence triples per verification LLM call |
| `confidence_boost` | float | no | `0.15` | Confidence increase on confirmation |

### `few_shot`

Few-shot example injection into the extraction prompt.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | no | `false` | Enable few-shot injection |
| `path` | string | no | `examples/golden/<profile>.yaml` | Path to golden examples file |
| `selection` | string | no | `random` | `random` or `semantic` (cosine similarity) |
| `max_examples` | int | no | `3` | Maximum examples to inject per fragment |

### `token_optimization`

Controls token usage reduction strategies.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `filter_entities_by_mention` | bool | no | `false` | Only inject entity catalog entries that appear in the fragment text |
| `compact_output_schema` | bool | no | `false` | Use short JSON keys (`s`, `p`, `o`, `c`) to reduce output tokens |
| `max_input_tokens_per_fragment` | int | no | `3000` | Token budget for assembled prompt; trims few-shot → context → catalog in priority order |
| `max_graph_context_tokens` | int | no | `200` | Maximum tokens for KNOWN GRAPH CONTEXT block |

### `allowed_predicates` and `allowed_classes`

Ontology constraints injected as a closed-world allowlist into the extraction prompt.

```yaml
allowed_predicates:
  - "schema:name"
  - "schema:birthDate"
  - "schema:memberOf"

allowed_classes:
  - "schema:Person"
  - "schema:Organization"
```

Triples with predicates or classes outside these lists are rejected before writing (`triple_rejected_ontology` stat).

### `predicate_constraints`

Cardinality and domain/range hints for individual predicates.

```yaml
predicate_constraints:
  - predicate: "schema:birthDate"
    max_cardinality: 1          # functional: only one value per subject
  - predicate: "schema:memberOf"
    domain: "schema:Person"
    range: "schema:Organization"
```

### `tentative_ttl_days`

```yaml
tentative_ttl_days: 30   # Archive tentative triples older than 30 days
```

### `constrained_decoding`

```yaml
constrained_decoding: true   # Force JSON schema conformance via Ollama grammar constraints
```

Only effective for `model_provider: ollama`.

### `evaluation`

Evaluation-specific flags used by `riverbank evaluate-wikidata`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `wikidata_benchmark` | bool | no | `false` | Enable Wikidata-specific scoring pipeline |
| `novel_discovery_sampling_rate` | float | no | `0.10` | Fraction of unmatched triples sampled for manual novel-discovery annotation |
| `min_confidence_for_scoring` | float | no | `0.30` | Minimum confidence to include a triple in precision/recall scoring |
