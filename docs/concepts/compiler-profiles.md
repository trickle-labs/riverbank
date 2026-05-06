# Compiler profiles

A compiler profile is the primary configuration surface for controlling what riverbank extracts, how it evaluates quality, and what the compiled graph must be able to answer.

## What a profile controls

| Field | Purpose |
|-------|---------|
| `name` | Unique identifier for the profile |
| `version` | Integer version (supports multiple versions per name) |
| `extractor` | Which extractor plugin to use (`noop`, `instructor`, or custom) |
| `model_provider` | LLM provider (`ollama`, `openai`, `anthropic`, `vllm`, `azure-openai`) |
| `model_name` | Model identifier |
| `embed_model` | Embedding model for vector operations |
| `max_fragment_tokens` | Maximum tokens per fragment sent to the LLM |
| `named_graph` | Target named graph IRI for compiled triples |
| `prompt_text` | System prompt guiding extraction |
| `editorial_policy` | Gate rules for fragment filtering |
| `competency_questions` | SPARQL assertions the compiled graph must satisfy |
| `run_mode_sequence` | Multi-pass compilation order (e.g., `[vocabulary, full]`) |
| `absence_rules` | Rules for recording explicit absences |
| `ensemble` | Multi-model configuration for higher accuracy |

## Profile as a contract

The profile defines a contract between the corpus author and the knowledge consumer:

1. **What gets extracted** — controlled by `prompt_text` and `extractor`
2. **What quality level is acceptable** — controlled by `editorial_policy.confidence_threshold`
3. **What questions the graph must answer** — controlled by `competency_questions`

This contract is testable. The golden corpus CI gate validates competency questions on every commit.

## Competency-question-driven design

The most effective way to design a profile:

1. Write the SPARQL queries your consumers need to answer
2. Put them in `competency_questions`
3. Iterate on `prompt_text` until all questions pass
4. The competency questions become your regression test suite

## Profile versioning

Profiles are versioned by `(name, version)`. When you improve a profile, bump the version. Old versions remain in the catalog for audit trail and recompilation comparison.

```bash
# Register v2 of an existing profile
riverbank profile register improved-profile-v2.yaml
```

## Editorial policy

The editorial policy prevents wasted LLM calls on content that cannot produce useful knowledge:

```yaml
editorial_policy:
  min_fragment_length: 50      # Characters — skip tiny fragments
  max_fragment_length: 8000    # Characters — flag oversized fragments
  min_heading_depth: 0         # 0 = all headings; 2 = skip H1
  confidence_threshold: 0.7    # Below this → draft graph
  allowed_languages: [en]      # Skip non-English content
```

See the [compiler profile schema reference](../reference/compiler-profile-schema.md) for exhaustive field documentation.
