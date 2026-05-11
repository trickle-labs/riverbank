# Control Extraction Focus

`extraction_focus` controls the precision-vs-recall trade-off at the extractor
layer — it tells the LLM how strictly to filter what it extracts from each
fragment. This is separate from fragmentation: the fragmenter always produces
all atomic statements; `extraction_focus` controls what gets turned into triples.

## Extraction Focus Modes

- **`comprehensive`** (default) — All factual claims including strong inferences
- **`high_precision`** — Explicitly stated claims only; confidence ≥ 0.90; no inference
- **`facts_only`** — Stated factual assertions only; excludes opinions, estimates, hedged language

## Quick Start

### YAML Configuration

Add to your profile:

```yaml
extractor: "instructor"
extraction_focus: "high_precision"  # or "comprehensive", "facts_only"
```

### Command Line (using built-in profiles)

```bash
# Comprehensive — all claims including inferences
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-statement.yaml

# High precision — explicitly stated claims only
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-essential.yaml

# Facts only — stated facts, no opinions or hedging
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-minimal.yaml
```

## When to Use Each

| Mode | Use Case | Typical Precision | Typical Recall |
|------|----------|-------------------|----------------|
| **comprehensive** | Discovery pipelines, novel-fact mining | Lower | Higher |
| **high_precision** | Authoritative knowledge graphs, production data | Higher | Lower |
| **facts_only** | Curated datasets, removing editorial noise | Medium-high | Medium |

## Built-in Profiles

Located in `examples/profiles/`:

- `wikidata-eval-v1-llm-statement.yaml` — comprehensive (default)
- `wikidata-eval-v1-llm-essential.yaml` — high_precision
- `wikidata-eval-v1-llm-minimal.yaml` — facts_only

## Related

- [Use document distillation](use-document-distillation.md) — reduce token cost *before* extraction by pre-filtering non-extractable sections
- [Tune extraction quality](tune-extraction-quality.md) — comprehensive guide to all extraction quality levers
