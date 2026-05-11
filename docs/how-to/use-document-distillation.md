# Use document distillation

Document distillation is an optional pre-fragmentation step that selects and
compresses the extractable content of a document before fragmentation (v0.15.2).
Use it to reduce the token cost of large documents and improve extraction focus.

**Pipeline position:**

```
parse → [distill] → coref → fragment → gate → extract → write
```

---

## Why distillation?

Large documents (encyclopedia articles, annual reports, long specifications)
waste extraction budget on sections that will never produce useful triples —
references, changelogs, footnotes, navigation menus, captions. Distillation
front-loads this filtering in one cheap LLM call and **caches the result
permanently**, so subsequent re-ingestion of an unchanged document costs zero
additional tokens.

Unlike preprocessing (which enriches the prompt), distillation reduces the
input document itself. The two features are complementary.

---

## Quick start

Add to your compiler profile:

```yaml
distillation:
  enabled: true
  strategy: moderate
```

Then run ingest as normal:

```bash
riverbank ingest --corpus path/to/docs/ --profile my-profile.yaml
```

The distilled text is cached in `~/.riverbank/distill_cache/`. Subsequent runs
on the same document skip the distillation LLM call entirely.

---

## Choose a strategy

| Strategy | LLM calls | Output size | Use when |
|---|---|---|---|
| `boilerplate_removal` | **0** | ~80–100% of content | Document is well-structured; just want clean input at zero LLM cost |
| `aggressive` | 1 | ~5–15 kB | Very large docs; only top-level facts needed; single-fragment extraction |
| `moderate` | 1 | ~20–50 kB | Long articles where you want many fragments and maximum triple yield (**recommended**) |
| `conservative` | 1 | ~60–90% | Every paragraph may contain extractable facts; minimal information loss |
| `section_aware` | 1–N | configurable | Structured long-form docs with heterogeneous section types |
| `budget_optimized` | 0–1 | dynamic | Cost-constrained scenarios; automatically picks the best strategy per document |

### `boilerplate_removal` — zero cost

Deterministic: strips reference sections, footnote markers, navigation menus,
captions, image alt text, and horizontal rules. No LLM call.

```yaml
distillation:
  enabled: true
  strategy: boilerplate_removal
```

Good for preprocessing pipelines where you want clean Markdown before further
analysis, or as a first pass before applying a more aggressive strategy.

### `moderate` — recommended default

Removes boilerplate and low-density elaboration while preserving all factual
sections verbatim for downstream fragmentation. One LLM call. Default output
size ~30 kB.

```yaml
distillation:
  enabled: true
  strategy: moderate
  target_size_bytes: 30720   # optional hint; default is 30 kB
```

### `aggressive` — minimize cost

Compresses to core facts only. Abstracts and removes elaboration. Use when
only top-level facts are needed and you're extracting a single fragment.

```yaml
distillation:
  enabled: true
  strategy: aggressive
  target_size_bytes: 10240   # default 10 kB
```

### `conservative` — minimal information loss

Removes only navigation, references, and captions; keeps all prose unchanged.
Use for documents where every paragraph may contain extractable facts.

```yaml
distillation:
  enabled: true
  strategy: conservative
```

### `section_aware` — fine-grained control

Two-pass: first classifies each Markdown section by type (factual, biographical,
event, reference, navigation, caption, appendix), then applies a per-type action.

```yaml
distillation:
  enabled: true
  strategy: section_aware
  section_types:
    factual:      keep        # copy verbatim
    biographical: summarize   # LLM 2-3 sentence summary
    event:        keep
    reference:    remove      # omit entirely
    navigation:   remove
    caption:      remove
    appendix:     remove
```

Valid actions per section type: `keep`, `summarize`, `remove`.

### `budget_optimized` — adaptive

Estimates triples-per-kB from a sample of fragments, then selects the cheapest
strategy that is predicted to meet `min_triple_target` within
`extraction_budget_usd`.

```yaml
distillation:
  enabled: true
  strategy: budget_optimized
  extraction_budget_usd: 1.00    # total extraction budget for this document
  min_triple_target: 50          # minimum desired triples
  sample_fragments: 3            # fragments to sample before choosing
```

---

## Use a dedicated distillation model

You can configure a smaller, faster model for distillation independently of
the extraction model. Small instruction-following models (e.g., `gemma3:4b`)
work well for distillation because the task is structural, not knowledge-intensive.

```yaml
name: my-profile
extractor: instructor
model_name: llama3.2         # extraction model

distillation:
  enabled: true
  strategy: moderate
  model_provider: ollama     # optional override
  model_name: gemma3:4b      # cheap distillation model
```

---

## Configure the cache directory

By default, distillation outputs are cached in `~/.riverbank/distill_cache/`.
Override to share a cache across machines or use a project-local path:

```yaml
distillation:
  enabled: true
  strategy: moderate
  cache_dir: /shared/distill_cache
```

Cache files are named `<xxh3_128_hex>_<strategy>_<target_bytes>.md`. The same
document distilled with different strategies or target sizes produces independent
cached outputs — you can experiment without invalidating previous work.

---

## Read distillation stats

Each ingest run reports distillation statistics in the summary line:

```
[my-profile] 3 sources: 87 triples | distilled: 142 kB removed (moderate) | ...
```

The run stats dict includes:
- `distillation_bytes_removed` — bytes removed across all documents in the run
- `distillation_strategy_used` — strategy name (last document's value in multi-doc runs)

---

## Full example profile

See `examples/profiles/distil-example.yaml` for a complete working profile
demonstrating the `moderate` strategy with all options annotated.

---

## Related

- [Tune extraction quality](tune-extraction-quality.md) — all extraction quality levers
- [Control extraction focus](use-extraction-focus.md) — precision vs recall trade-off at the extraction layer
- [Pipeline stages — distillation](../concepts/pipeline-stages.md#3-distillation-optional) — concept explanation
- [Compiler profile schema — distillation](../reference/compiler-profile-schema.md#distillation) — full field reference
