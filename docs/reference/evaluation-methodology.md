# Evaluation Methodology

This page describes riverbank's external evaluation methodology using Wikidata
as ground truth, introduced in v0.15.0 and refined with the v0.15.1 improvement
loop.

---

## Overview

riverbank's extraction quality is measured by comparing compiled triples against
Wikidata's curated statements for the same Wikipedia articles.  Wikidata is chosen
because it is:

- **Large** — 1.65 billion statements from 110 million items
- **Sourced from Wikipedia** — the same articles riverbank ingests
- **Human-curated** — each statement has at least one reference
- **Structured** — typed properties (P-ids) enable automated matching

The evaluation pipeline is reproducible and fully automated.  Results are stored
in `eval/results/` and are never committed to the repository.

---

## Benchmark Dataset

The benchmark is defined in `eval/wikidata-benchmark-1k.yaml` and contains
**1,000 Wikipedia articles** stratified across 7 domains:

| Domain | Articles | Description |
|---|---|---|
| `biography_living` | 150 | Living notable persons |
| `biography_historical` | 200 | Deceased notable persons |
| `organization` | 150 | Companies, NGOs, governments |
| `geographic` | 150 | Cities, rivers, mountains, regions |
| `creative_work` | 150 | Films, novels, artworks, albums |
| `scientific` | 100 | Theories, phenomena, discoveries |
| `event` | 100 | Wars, disasters, cultural events |

Stratification ensures that no single domain dominates the aggregate metrics.

---

## Pipeline Stages

### 1. Article Fetch (`WikipediaClient`)

Each article is fetched via the MediaWiki REST API and converted to Markdown.
A local hybrid cache (`.riverbank/article_cache/`) avoids redundant network
calls:

- **Cache hit** — metadata TTL checked (default 30 days); served from disk
- **Cache miss** — fetched fresh, cached to disk for future runs
- **`--no-cache`** — bypass local cache entirely (force fresh)
- **`--cache-only`** — raise `CacheOnlyError` if article not in cache

### 2. Ground-Truth Fetch (`WikidataClient`)

The Wikidata SPARQL endpoint (WDQS) is queried for all statements of the
corresponding Wikidata item, identified via sitelink from the Wikipedia title.

**Exclusion filters** — statements are excluded if their value type is:

| Excluded type | Reason |
|---|---|
| `ExternalId` | Database identifiers (ISNI, VIAF, etc.) |
| `CommonsMedia` | Image filenames |
| `Url` | Website URLs |
| `GeoShape`, `TabularData` | Complex geodata blobs |
| `Math` | Mathematical formulae |

This focuses evaluation on factual, extractable content.

### 3. Property Alignment (`PropertyAlignmentTable`)

riverbank predicates are matched to Wikidata P-ids via the alignment table
defined in `property-alignment-v1.yaml` and implemented in
`src/riverbank/eval/property_alignment.py`.

The table currently covers **50+ properties** including:

| P-id | Label | riverbank predicates |
|---|---|---|
| P31 | instance of | `rdf:type`, `pgc:isA` |
| P106 | occupation | `pgc:hasOccupation` |
| P569 | date of birth | `pgc:birthDate` |
| P27 | country of citizenship | `pgc:nationality`, `ex:citizenship` |
| P159 | headquarters location | `pgc:headquartersLocation` |

### 4. Entity Resolution (`EntityResolver`)

riverbank IRIs are linked to Wikidata Q-ids through a three-stage pipeline:

1. **Sitelink match** — if the IRI label matches the article title, use the
   article's Q-id directly (confidence 1.0)
2. **Label match** — extract a human-readable label from the IRI; fuzzy-match
   against Wikidata entity labels and aliases
3. **Context disambiguation** — when multiple candidates have similar scores,
   filter by P31 (instance of) type using domain hints

### 5. Scoring (`Scorer`)

Each riverbank triple `(subject, predicate, object, confidence)` is classified:

| Match type | Meaning | Counted as |
|---|---|---|
| `exact` | Predicate aligned **and** object matches | True positive (TP) |
| `partial` | Predicate aligned but object doesn't match | False positive (FP) |
| `no_match` | Predicate not in alignment table | Novel discovery candidate |

Object matching uses:

- **Exact string normalisation** (lowercase, punctuation removed)
- **Year extraction** from ISO 8601 dates (year-level match → 0.95 score)
- **Fuzzy string similarity** via `rapidfuzz` (or `difflib` fallback)
- **Q-id label lookup** for Wikidata items

Precision, recall, and F1 are computed as:

$$\text{Precision} = \frac{TP}{TP + FP}$$

$$\text{Recall} = \frac{TP}{TP + FN}$$

$$F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$

### 6. Confidence Calibration

Each triple's confidence score is bucketed into four ranges
(`0.0–0.25`, `0.25–0.5`, `0.5–0.75`, `0.75–1.0`) and observed accuracy
within each bucket is measured.  Calibration quality is reported as
Pearson ρ between bucket midpoints and observed accuracy.

A well-calibrated model should produce ρ ≥ 0.80: higher confidence triples
should be more accurate.

---

## Metrics

| Metric | Target | Description |
|---|---|---|
| Precision | ≥ 0.85 | Fraction of riverbank triples that match a Wikidata statement |
| Recall | ≥ 0.60 | Fraction of Wikidata statements captured by riverbank |
| F1 | ≥ 0.70 | Harmonic mean of precision and recall |
| Calibration ρ | ≥ 0.80 | Pearson correlation of confidence vs. observed accuracy |
| Novel discovery rate | — | Fraction of unmatched triples that are factually correct |

The **novel discovery rate (NDR)** is validated by manual annotation:
unmatched triples are sampled (10% by default) and classified as
`correct`, `incorrect`, `uncertain`, or `in_wikidata` (alignment gap).

$$\text{NDR} = \frac{|\text{correct}|}{|\text{correct}| + |\text{incorrect}|}$$

---

## v0.15.0 Baseline Results

The first evaluation run over all 1,000 articles established the baseline:

| Metric | Value |
|---|---|
| Precision | 0.87 |
| Recall | 0.62 |
| F1 | 0.72 |
| Calibration ρ | 0.83 |
| Novel discovery rate | 0.78 |

All four exit criteria from the v0.15.0 roadmap were met.

---

## v0.15.1 Improvement Loop

v0.15.1 closes the feedback loop from the evaluation back into the extraction
pipeline.

### Per-Property Recall Gap Analysis

The `RecallGapAnalyzer` class (in `src/riverbank/eval/recall_gap.py`) identifies
Wikidata properties where recall falls below a configurable threshold (default
0.50) and generates targeted extraction examples for each gap property.

Run from the CLI:

```
riverbank recall-gap-analysis --results eval/results/latest.json \
    --threshold 0.50 \
    --output eval/results/recall-gaps.json
```

### Extraction Prompt Tuning

The `PromptTuner` class (in `src/riverbank/eval/prompt_tuning.py`) analyses
false-positive and false-negative patterns from the evaluation report and
generates concrete prompt patches — additional few-shot examples and system
instructions — to improve precision and recall.

Run from the CLI:

```
riverbank tune-extraction-prompts --results eval/results/latest.json \
    --output eval/results/tuning-report.json
```

### Novel Discovery Annotations

212 unmatched riverbank triples from the v0.15.0 run were manually annotated
and stored in `eval/novel-discovery-annotations.yaml`.  The validated NDR is
**0.779** (134 correct out of 172 judged):

| Verdict | Count |
|---|---|
| Correct | 134 |
| Incorrect | 38 |
| Uncertain | 24 |
| In Wikidata (alignment gap) | 16 |

Alignment gap discoveries (16 triples) directly informed property table
extensions in v0.15.1.

---

## Running an Evaluation

### Single article

```bash
riverbank evaluate-wikidata --article "Marie Curie" \
    --profile wikidata-eval-v1
```

### Full benchmark dataset

```bash
riverbank evaluate-wikidata \
    --dataset eval/wikidata-benchmark-1k.yaml \
    --profile wikidata-eval-v1 \
    --output eval/results/run-$(date +%Y%m%d).json
```

### Recall gap analysis

```bash
riverbank recall-gap-analysis \
    --results eval/results/latest.json \
    --threshold 0.50 \
    --output eval/results/recall-gaps.json
```

### Prompt tuning report

```bash
riverbank tune-extraction-prompts \
    --results eval/results/latest.json \
    --output eval/results/tuning-report.json
```

---

## Reproducibility

All evaluation runs are fully reproducible:

1. The benchmark dataset YAML is committed to the repository
2. The property alignment table is committed (`property-alignment-v1.yaml`)
3. The evaluation profile YAML is committed (`examples/profiles/wikidata-eval-v1.yaml`)
4. The Wikipedia article cache is local and persisted across runs
5. LLM calls use temperature 0 by default when scoring

Wikidata statements may change over time.  Evaluation runs should record the
run date; results older than 90 days should be re-run against fresh Wikidata
data.

---

## Limitations

- **Novel discoveries** require manual annotation; the automated NDR estimate
  uses heuristics
- **Entity resolution** for ambiguous IRIs falls back to label matching, which
  can introduce noise
- **Object matching** for quantities, coordinates, and dates uses heuristics;
  unit normalisation is not exhaustive
- The benchmark covers English Wikipedia only
- Wikidata completeness varies by domain; recall is penalised for statements
  that Wikidata itself is missing
