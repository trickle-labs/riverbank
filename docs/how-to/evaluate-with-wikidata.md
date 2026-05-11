# Evaluate with Wikidata

`riverbank evaluate-wikidata` measures extraction quality by comparing compiled
triples against Wikidata's curated statements for the same Wikipedia articles.
Introduced in v0.15.0, refined with the v0.15.1 improvement loop.

For the full methodology and scoring pipeline, see the
[Evaluation Methodology reference](../reference/evaluation-methodology.md).

---

## Prerequisites

Install the `eval` extras:

```bash
pip install 'riverbank[eval]'
```

Configure your LLM provider in `~/.riverbank/settings.yaml` or via environment variables.

---

## Single-article evaluation

```bash
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-statement.yaml
```

You can also pass a Wikipedia URL or Wikidata Q-id:

```bash
riverbank evaluate-wikidata --article "https://en.wikipedia.org/wiki/Marie_Curie"
riverbank evaluate-wikidata --article "Q7186"
```

**Output:**

```
Article: Marie Curie (Q7186)
Triples extracted: 143 | Wikidata statements: 89 (after filtering)
Precision: 0.87  Recall: 0.71  F1: 0.78
Novel discovery rate: 0.24 (34 triples not in Wikidata but plausible)
Calibration ρ: 0.83
```

---

## Caching options

By default, Wikipedia articles are cached in `.riverbank/article_cache/` to
avoid repeated network calls. Control this behaviour with:

```bash
# Force fresh fetch (bypass local cache)
riverbank evaluate-wikidata --article "Marie Curie" --no-cache

# Offline mode (raise an error if article not in cache)
riverbank evaluate-wikidata --article "Marie Curie" --cache-only
```

---

## Batch evaluation over the 1,000-article benchmark

```bash
riverbank evaluate-wikidata \
  --dataset eval/wikidata-benchmark-1k.yaml \
  --profile examples/profiles/wikidata-eval-v1-llm-statement.yaml \
  --output eval/results/run-$(date +%Y%m%d).json
```

The benchmark contains 1,000 Wikipedia articles stratified across 7 domains
(biographies, organizations, geographic entities, creative works, scientific
concepts, events). Results are stored in `eval/results/` and never committed.

---

## Choose an evaluation profile

Three built-in profiles in `examples/profiles/` cover the main precision/recall trade-offs:

| Profile | `extraction_focus` | Typical precision | Typical recall |
|---|---|---|---|
| `wikidata-eval-v1-llm-statement.yaml` | `comprehensive` | Lower | Higher |
| `wikidata-eval-v1-llm-essential.yaml` | `high_precision` | Higher | Lower |
| `wikidata-eval-v1-llm-minimal.yaml` | `facts_only` | Medium-high | Medium |

See [Control extraction focus](use-extraction-focus.md) for details on each mode.

---

## Analyse recall gaps (v0.15.1)

After a batch run, identify Wikidata properties where recall falls below a threshold:

```bash
riverbank recall-gap-analysis --threshold 0.50 \
  --results eval/results/run-20260101.json
```

This lists properties with `recall < 0.50` and generates targeted extraction examples
that can be added to your profile's `few_shot` examples.

---

## Tune prompts from evaluation results (v0.15.1)

```bash
riverbank tune-extraction-prompts \
  --results eval/results/run-20260101.json \
  --profile examples/profiles/wikidata-eval-v1-llm-statement.yaml
```

This analyses false-positive and false-negative patterns and suggests prompt modifications.
Review the suggestions and apply the ones that make sense for your domain.

---

## Understanding the output report

The JSON report includes:

```json
{
  "summary": {
    "precision": 0.87,
    "recall": 0.71,
    "f1": 0.78,
    "novel_discovery_rate": 0.24,
    "calibration_rho": 0.83
  },
  "by_domain": { ... },
  "by_property": { ... },
  "calibration_curve": [ ... ]
}
```

- **precision** — of all triples riverbank extracted, what fraction are in Wikidata?
- **recall** — of all Wikidata statements, what fraction did riverbank find?
- **novel_discovery_rate** — fraction of unmatched triples that are plausible but absent from Wikidata (sampled and annotated manually via `eval/novel-discovery-annotations.yaml`)
- **calibration ρ** — Pearson correlation between confidence scores and observed accuracy across confidence buckets

---

## Related

- [Evaluation methodology](../reference/evaluation-methodology.md) — full pipeline description, property alignment table, scoring formulae
- [Control extraction focus](use-extraction-focus.md) — tune precision vs recall
- [Tune extraction quality](tune-extraction-quality.md) — all extraction quality levers
