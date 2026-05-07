# riverbank — Wikidata-Based Extraction Evaluation

> **Date:** 2026-05-07  
> **Status:** Strategy proposal — not yet implemented  
> **Owner:** trickle-labs  
> **Related:** [riverbank.md](riverbank.md) · [optimizing-knowledge-graph.md](optimizing-knowledge-graph.md)  
> **Prerequisites:** riverbank v0.3.0 (MVP complete), Wikidata SPARQL endpoint access

---

## 1. The idea in one paragraph

Wikidata is the world's largest open-access knowledge graph — 1.65 billion
human-validated semantic triples, collaboratively maintained, freely queryable
via SPARQL, and grounded in the same Wikipedia articles that riverbank can
ingest. By feeding Wikipedia articles through riverbank's compilation pipeline
and comparing the extracted triples against what Wikidata already knows about
those articles, we get an unbiased, externally-maintained ground truth for
measuring extraction precision, recall, confidence calibration, and novel
discovery rate — without building our own annotation team.

---

## 2. Why Wikidata is the right benchmark

### What Wikidata is

Wikidata stores structured claims about entities as property–value pairs
(semantic triples). Each claim can carry qualifiers (temporal bounds, context)
and references (source citations). The data model is:

```
Item (Q-id) → Property (P-id) → Value (Q-id | literal | date | quantity)
                                  ├── Qualifier (P-id → value)
                                  └── Reference (P-id → value)
```

Example: `Q7186 (Marie Curie) → P106 (occupation) → Q169470 (physicist)`

### Why it fits riverbank's evaluation needs

| Property | Benefit for evaluation |
|----------|----------------------|
| **Scale** | 1.65B triples across 100M+ items; statistically meaningful |
| **Coverage** | Strong on biographies, orgs, locations, works, science |
| **Structured RDF** | Directly comparable to riverbank's RDF output |
| **Open SPARQL endpoint** | `query.wikidata.org` — free, no API key |
| **CC0 license** | No legal constraints on use in CI/benchmarks |
| **Human-validated** | Community-curated consensus = high-confidence ground truth |
| **Source references** | Can verify that claims trace to Wikipedia article text |
| **Temporal qualifiers** | Enables testing time-bounded extraction accuracy |

### What Wikidata is NOT

Wikidata is not a complete extraction of all facts from Wikipedia articles. It
captures structured, notable claims — typically the kind of information that
appears in infoboxes or lead paragraphs. This means:

- **Recall ceiling is not 100%** — many implicit relationships in article prose
  are not in Wikidata. Riverbank may correctly extract facts Wikidata lacks.
- **Schema is opinionated** — Wikidata uses ~11,000 predefined properties;
  riverbank's open extraction may produce relations with no Wikidata equivalent.
- **Wikidata can be stale** — community edits lag behind article changes.

These limitations are features for evaluation: they let us distinguish
**precision** (do we match what Wikidata has?) from **novel discovery** (what
correct facts do we find beyond Wikidata?).

---

## 3. Evaluation dimensions

### 3.1 Precision against Wikidata

> Of the triples riverbank extracts, what fraction aligns with Wikidata
> statements?

**Method:** For each extracted triple `(s, p, o)`, attempt to match against
Wikidata statements on the same item:
1. Resolve riverbank's subject IRI to a Wikidata Q-id (via label matching or
   Wikipedia article ↔ Wikidata sitelink).
2. Map riverbank's predicate to the closest Wikidata property (property
   alignment table, see §5.2).
3. Compare the object value (fuzzy string match for literals, Q-id resolution
   for entities).

**Scoring:**
- **Exact match:** Object resolves to same Wikidata value → true positive.
- **Partial match:** Correct property, related but imprecise value (e.g.
  "scientist" vs "physicist") → scored at 0.5.
- **No match:** No corresponding Wikidata statement exists → either novel
  discovery or false positive (requires sampling + human judgment).

### 3.2 Recall against Wikidata

> Of Wikidata's statements about an article's subject, what fraction does
> riverbank capture?

**Method:** For a given Wikipedia article with Wikidata item Q-id:
1. Fetch all Wikidata statements on that item.
2. Filter to properties relevant to article prose (exclude external identifiers,
   image links, interwiki links).
3. Check which statements have a corresponding triple in riverbank's output.

**Important caveats:**
- Not all Wikidata statements are derivable from the article text alone (some
  come from external databases). Filter to statements with Wikipedia-sourced
  references where possible.
- Recall should be measured per-property-type, not as a single number, to
  identify extraction blind spots.

### 3.3 Confidence calibration

> Do riverbank's confidence scores predict correctness?

**Method:** Bucket extracted triples by confidence score (0.0–0.5, 0.5–0.7,
0.7–0.85, 0.85–1.0). For each bucket, measure precision against Wikidata. A
well-calibrated extractor should show monotonically increasing precision as
confidence increases.

**Output:** Calibration curve (reliability diagram) plotting mean confidence
vs. observed accuracy.

### 3.4 Novel discovery rate

> What fraction of riverbank's extractions capture facts that Wikidata does
> NOT have?

**Method:** Triples with no Wikidata match are either:
- **True novel discoveries** — correct facts absent from Wikidata.
- **False positives** — incorrect extractions.

Disambiguate via sampling: annotate 200+ unmatched triples manually. Report the
novel discovery rate as `true_novels / (true_novels + false_positives)`.

### 3.5 Temporal accuracy

> For time-bounded claims, does riverbank correctly identify temporal scope?

**Method:** Focus on Wikidata statements with `P580` (start time) / `P582`
(end time) qualifiers — e.g. "CEO of Company X from 2015 to 2021". Check
whether riverbank's extraction captures the temporal boundary or states the
relation as atemporal.

### 3.6 Contradiction detection

> When riverbank and Wikidata disagree, who is right?

**Method:** Surface all triples where riverbank asserts a value that conflicts
with Wikidata (same subject + property, different object). Categorize:
- Riverbank extraction error (false positive).
- Wikidata stale/outdated statement.
- Context-dependent (both correct in different contexts).

This directly validates riverbank's `pgc:epistemicStatus = "disputed"` detection
and the verification postprocessor.

---

## 4. Dataset design

### 4.1 Article selection

Select **1,000 English Wikipedia articles** stratified across domains:

| Domain | Count | Rationale |
|--------|-------|-----------|
| Biographies (living) | 200 | Dense factual claims, strong Wikidata coverage |
| Biographies (historical) | 100 | Temporal facts, multiple roles over time |
| Organizations (companies) | 150 | Structured data: HQ, CEO, founding, revenue |
| Organizations (non-profit/govt) | 50 | Tests breadth beyond commercial entities |
| Geographic entities | 150 | Population, coordinates, administrative divisions |
| Creative works (books/films) | 150 | Author, publication date, genre, awards |
| Scientific concepts | 100 | Tests abstract relation extraction |
| Events | 100 | Temporal boundaries, participants, locations |

### 4.2 Selection criteria

- Article must have a linked Wikidata item (sitelink exists).
- Wikidata item must have ≥ 10 statements (excluding external identifiers).
- Article must be ≥ 2,000 characters (enough prose for extraction).
- Stratify within domain by Wikidata statement density:
  - 1/3 high-density items (≥ 50 statements) — tests recall ceiling.
  - 1/3 medium-density (20–49 statements) — typical case.
  - 1/3 low-density (10–19 statements) — tests novel discovery.

### 4.3 Data preparation

```
Wikipedia article (Markdown)
         │
         ├── riverbank ingest → extracted triples
         │
         └── Wikidata SPARQL → ground truth statements
                                     │
                                     └── property alignment → comparable format
```

For each article, produce:
1. **Source markdown** — downloaded via Wikipedia API, converted to Markdown.
2. **Riverbank output** — run through compilation pipeline with a standardized
   evaluation profile (see §5.1).
3. **Wikidata ground truth** — SPARQL query for all statements on the item,
   filtered to prose-derivable properties.

---

## 5. Implementation

### 5.1 Evaluation compiler profile

A dedicated profile optimized for Wikipedia extraction evaluation:

```yaml
name: wikidata-eval-v1
description: "Wikipedia extraction for Wikidata benchmarking"
version: "1.0.0"

extractor:
  backend: instructor
  model: gpt-4o  # or configured LLM
  temperature: 0.0

fragmenter:
  strategy: heading
  max_tokens: 2048

quality_gate:
  min_shacl_score: 0.0   # no filtering for evaluation — capture everything
  confidence_threshold: 0.0  # don't route to draft; keep all for measurement

editorial_policy:
  min_density_sentences: 1

# Target properties aligned to Wikidata's most common:
extraction_guidance:
  property_hints:
    - "instance of / type"
    - "occupation / profession"
    - "date of birth / date of death"
    - "place of birth / place of death"
    - "educated at"
    - "employer / member of"
    - "founded by / inception date"
    - "located in / headquarters location"
    - "authored by / publication date"
    - "part of / has parts"
    - "award received"
    - "country of citizenship / nationality"
    - "spouse / child / parent"

competency_questions:
  - id: eval-cq-01
    description: "Primary type/class of the subject is extracted"
    sparql: |
      ASK { ?s a ?type . }
  - id: eval-cq-02
    description: "At least one temporal fact is captured"
    sparql: |
      ASK { ?s ?p ?date . FILTER(DATATYPE(?date) = xsd:date) }
```

### 5.2 Property alignment table

Map between riverbank's open extraction predicates and Wikidata properties:

```python
# wikidata_property_map.py
PROPERTY_ALIGNMENT = {
    # Wikidata P-id → list of riverbank predicate patterns (regex)
    "P31":  ["rdf:type", "instance.?of", "is.?a"],
    "P106": ["occupation", "profession", "role", "job"],
    "P569": ["date.?of.?birth", "born", "birth.?date"],
    "P570": ["date.?of.?death", "died", "death.?date"],
    "P19":  ["place.?of.?birth", "born.?in", "birthplace"],
    "P20":  ["place.?of.?death", "died.?in"],
    "P69":  ["educated.?at", "studied.?at", "alma.?mater"],
    "P108": ["employer", "works?.?for", "employed.?by"],
    "P112": ["founded.?by", "founder"],
    "P571": ["inception", "founded", "established"],
    "P159": ["headquarters", "head.?office", "based.?in"],
    "P50":  ["author", "written.?by", "authored.?by"],
    "P577": ["publication.?date", "published", "release.?date"],
    "P361": ["part.?of", "belongs.?to"],
    "P527": ["has.?part", "consists.?of", "includes"],
    "P166": ["award", "prize", "honor"],
    "P27":  ["country.?of.?citizenship", "nationality"],
    "P26":  ["spouse", "married.?to"],
    "P40":  ["child", "offspring"],
    "P22":  ["father", "paternal"],
    "P25":  ["mother", "maternal"],
    "P131": ["located.?in", "admin.?territory"],
    "P17":  ["country"],
    "P625": ["coordinates", "latitude", "longitude"],
    "P1082": ["population"],
}
```

### 5.3 Entity resolution

Matching riverbank entities to Wikidata Q-ids:

1. **Sitelink lookup** — the Wikipedia article title directly maps to a Wikidata
   item via `schema:about` in the Wikidata RDF dump.
2. **Label matching** — for entities mentioned within the article, match
   riverbank's subject IRI label against Wikidata item labels + aliases using
   fuzzy matching (Levenshtein ratio ≥ 0.9).
3. **Context-assisted disambiguation** — if multiple Q-ids match a label, use
   the article's domain (person, org, place) to disambiguate via `P31`
   (instance of) on the candidate items.

### 5.4 Scoring pipeline

```python
# Pseudocode for the evaluation pipeline
def evaluate_article(article_id: str) -> ArticleScore:
    # 1. Fetch riverbank triples for this article's graph
    rb_triples = sparql_query(f"""
        SELECT ?s ?p ?o ?confidence
        WHERE {{
            GRAPH <{article_graph}> {{ ?s ?p ?o }}
            ?s pgc:confidence ?confidence .
        }}
    """)

    # 2. Fetch Wikidata ground truth
    wd_statements = wikidata_sparql(f"""
        SELECT ?prop ?value ?valueLabel
        WHERE {{
            wd:{qid} ?prop ?value .
            SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
    """)

    # 3. Align and score
    matches = align_triples(rb_triples, wd_statements, PROPERTY_ALIGNMENT)

    return ArticleScore(
        precision=matches.true_positives / (matches.true_positives + matches.false_positives),
        recall=matches.true_positives / (matches.true_positives + matches.false_negatives),
        unmatched_riverbank=matches.no_wd_match,  # novel candidates
        confidence_buckets=bucket_by_confidence(matches),
    )
```

### 5.5 Wikidata SPARQL query template

For a given Wikidata item Q-id, fetch comparable statements:

```sparql
SELECT ?property ?propertyLabel ?value ?valueLabel ?qualifier ?qualifierValue
WHERE {
  wd:Q7186 ?claim ?statement .
  ?statement ?ps ?value .
  ?property wikibase:claim ?claim .
  ?property wikibase:statementProperty ?ps .

  # Exclude external identifiers and media
  ?property wikibase:propertyType ?type .
  FILTER(?type NOT IN (
    wikibase:ExternalId,
    wikibase:CommonsMedia,
    wikibase:Url
  ))

  # Optional temporal qualifiers
  OPTIONAL {
    ?statement pq:P580 ?startTime .
    ?statement pq:P582 ?endTime .
  }

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
```

---

## 6. Metrics and thresholds

### 6.1 Primary metrics

| Metric | Definition | Target |
|--------|-----------|--------|
| **Precision@WD** | TP / (TP + FP) against Wikidata | ≥ 0.85 |
| **Recall@WD** | TP / (TP + FN) for prose-derivable statements | ≥ 0.60 |
| **F1@WD** | Harmonic mean of Precision and Recall | ≥ 0.70 |
| **Confidence calibration** | Pearson ρ(confidence, accuracy) | ≥ 0.80 |
| **Novel discovery rate** | True novels / all unmatched triples | ≥ 0.50 |
| **False positive rate** | FP / total extractions | ≤ 0.10 |

### 6.2 Per-domain breakdowns

Report all metrics stratified by domain (biography, org, geo, works, science,
events). Identify extraction blind spots by domain.

### 6.3 Per-property breakdowns

Report recall per Wikidata property type. Expected strong properties:
- P31 (instance of) — should be near-perfect
- P106 (occupation) — high recall for biographies
- P569/P570 (birth/death dates) — structured data, high precision
- P159 (headquarters) — organizations

Expected weak properties (requiring future improvement):
- P625 (coordinates) — rarely in prose
- P1082 (population) — numeric, often ambiguous timeframe
- Relationship properties (P26, P40) — context-dependent

### 6.4 Confidence calibration curve

| Confidence bucket | Expected precision |
|---|---|
| 0.0 – 0.5 | ≥ 0.40 (these should be quarantined in draft) |
| 0.5 – 0.7 | ≥ 0.65 |
| 0.7 – 0.85 | ≥ 0.80 |
| 0.85 – 1.0 | ≥ 0.92 |

If calibration is poor (high-confidence triples have low precision), the
confidence scoring model needs retraining.

---

## 7. Integration with riverbank CI

### 7.1 Benchmark corpus as golden test

```yaml
# .github/workflows/wikidata-eval.yml
name: Wikidata Evaluation
on:
  push:
    paths: ['src/riverbank/extractors/**']
  schedule:
    - cron: '0 3 * * 0'  # Weekly Sunday 3am

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run evaluation pipeline
        run: |
          riverbank evaluate-wikidata \
            --dataset eval/wikidata-benchmark-1k/ \
            --profile examples/profiles/wikidata-eval-v1.yaml \
            --output eval/results/latest.json
      - name: Check thresholds
        run: |
          python eval/check_thresholds.py eval/results/latest.json \
            --min-precision 0.85 \
            --min-recall 0.60 \
            --min-f1 0.70
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: wikidata-eval-results
          path: eval/results/
```

### 7.2 CLI command

```bash
# Run full evaluation
riverbank evaluate-wikidata \
  --dataset eval/wikidata-benchmark-1k/ \
  --profile wikidata-eval-v1 \
  --output eval/results/run-$(date +%Y%m%d).json \
  --parallel 8

# Quick smoke test (10 articles)
riverbank evaluate-wikidata \
  --dataset eval/wikidata-benchmark-1k/ \
  --sample 10 \
  --profile wikidata-eval-v1
```

### 7.3 Dashboard output

The evaluation produces a JSON report and optional HTML dashboard:

```json
{
  "run_date": "2026-05-07T12:00:00Z",
  "dataset": "wikidata-benchmark-1k",
  "profile": "wikidata-eval-v1",
  "articles_evaluated": 1000,
  "total_riverbank_triples": 28450,
  "total_wikidata_statements": 41200,
  "aggregate": {
    "precision": 0.87,
    "recall": 0.63,
    "f1": 0.73,
    "confidence_calibration_r": 0.84,
    "novel_discovery_rate": 0.58,
    "false_positive_rate": 0.08
  },
  "by_domain": {
    "biography_living": { "precision": 0.91, "recall": 0.72, "f1": 0.80 },
    "biography_historical": { "precision": 0.88, "recall": 0.65, "f1": 0.75 },
    "organization": { "precision": 0.85, "recall": 0.58, "f1": 0.69 },
    "geographic": { "precision": 0.84, "recall": 0.55, "f1": 0.67 },
    "creative_works": { "precision": 0.89, "recall": 0.67, "f1": 0.76 },
    "science": { "precision": 0.82, "recall": 0.48, "f1": 0.60 },
    "events": { "precision": 0.86, "recall": 0.61, "f1": 0.71 }
  },
  "calibration_curve": [...],
  "top_missed_properties": ["P625", "P1082", "P2860"],
  "top_false_positive_patterns": [...]
}
```

---

## 8. Comparison with related approaches

| Approach | Pros | Cons |
|----------|------|------|
| **Manual annotation** | Perfect ground truth | Expensive, slow, non-reproducible |
| **DBpedia comparison** | Also from Wikipedia | Auto-extracted (noisy); less curated than Wikidata |
| **Wikidata comparison** | Human-validated, SPARQL-queryable, massive scale | Not exhaustive; schema-constrained |
| **LLM-as-judge** | Flexible, can evaluate open relations | Circular (LLM evaluating LLM); not reproducible |
| **KILT benchmark** | Established NLP benchmark | Older; not RDF-native; limited property coverage |

Wikidata comparison is the best available option for riverbank because:
1. Both systems produce RDF triples — direct structural comparison.
2. Wikidata is maintained independently — no evaluation bias.
3. The SPARQL endpoint makes evaluation fully automated.
4. CC0 licensing means we can include data in our test suite.
5. The benchmark dataset is evergreen — it improves over time as Wikidata grows.

---

## 9. Where riverbank should outperform Wikidata

The evaluation should also quantify riverbank's **advantages** — areas where
automated LLM compilation adds value beyond Wikidata's manual curation:

### 9.1 Citation precision

Wikidata references point to a source (URL or work). Riverbank provides
**character-level citation spans** — the exact excerpt that justifies the claim.
Measure: % of triples with verified evidence spans vs. Wikidata's reference rate.

### 9.2 Confidence quantification

Wikidata uses binary "normal/preferred/deprecated" ranks. Riverbank produces
continuous confidence scores [0.0, 1.0] with epistemic status tracking.
Measure: How well does the confidence score predict actual accuracy?

### 9.3 Speed-to-knowledge

Wikidata relies on volunteer editors; facts often appear weeks/months after an
article is published. Riverbank can compile within minutes of source change.
Measure: For recently-edited articles, count facts riverbank extracts that
Wikidata doesn't have yet.

### 9.4 Extended relations

Wikidata's ~11,000 properties don't cover all possible relations. Riverbank's
open extraction can discover relationships that have no Wikidata property.
Measure: Novel discovery rate (§3.4) — the higher, the more added value.

### 9.5 Epistemic lifecycle

Wikidata marks disputed claims but doesn't track the full
`observed → extracted → verified → deprecated` lifecycle. Riverbank does.
Measure: % of Wikidata "deprecated" statements that riverbank's verification
pass would have caught proactively.

---

## 10. Implementation roadmap

### Phase 1: Proof of concept (1 week)

- [ ] Select 50 Wikipedia articles (10 per domain, 5 domains).
- [ ] Download as Markdown via Wikipedia API.
- [ ] Write Wikidata SPARQL fetch script (`eval/fetch_wikidata_ground_truth.py`).
- [ ] Build property alignment table (top 30 Wikidata properties).
- [ ] Run riverbank ingest on all 50; manually verify 10 alignment results.
- [ ] Compute precision/recall on the 50-article set.
- [ ] **Go/no-go decision:** If precision > 0.75 and the alignment logic works,
  proceed to Phase 2.

### Phase 2: Full benchmark dataset (2 weeks)

- [ ] Scale to 1,000 articles with stratified sampling.
- [ ] Automate Wikipedia → Markdown download pipeline.
- [ ] Expand property alignment to 50+ Wikidata properties.
- [ ] Implement entity resolution (label matching + disambiguation).
- [ ] Build `riverbank evaluate-wikidata` CLI command.
- [ ] Produce first full evaluation report.

### Phase 3: CI integration (1 week)

- [ ] Create GitHub Actions workflow for weekly evaluation.
- [ ] Implement threshold check script (`eval/check_thresholds.py`).
- [ ] Add calibration curve plotting.
- [ ] Store historical results for trend tracking.

### Phase 4: Analysis and iteration (ongoing)

- [ ] Identify top failure modes from false positives/negatives.
- [ ] Tune extraction prompts based on per-property recall gaps.
- [ ] Expand property alignment table as new extraction patterns emerge.
- [ ] Annotate 200+ novel discoveries to validate novel discovery rate.
- [ ] Publish evaluation methodology and results in docs.

---

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Property alignment errors inflate FP/FN | Misleading metrics | Manual audit of alignment table; fuzzy fallback |
| Entity resolution failures | Unmatchable triples | Multi-strategy resolution (sitelink + label + context) |
| Wikidata rate limits on SPARQL endpoint | Slow evaluation | Cache ground truth; batch queries; use Wikidata dumps |
| Wikipedia article format changes | Broken ingestion | Use stable MediaWiki API; Markdown conversion library |
| Wikidata coverage gaps in niche domains | Artificially low recall | Report recall only for properties with ≥ 5 instances |
| LLM cost for 1,000-article evaluation | Budget pressure | Sample-based smoke tests in CI; full eval weekly |

---

## 12. Open questions

1. **Should we use Wikidata RDF dumps or the live SPARQL endpoint?**
   Dumps are faster for batch evaluation but lag behind live data.
   Recommendation: dumps for the benchmark dataset, live endpoint for spot checks.

2. **How to handle multi-hop relations?**
   Riverbank may extract "Marie Curie → born in → Warsaw" while Wikidata says
   "Marie Curie → P19 → Warsaw (Q270)". Direct match. But what about "Marie
   Curie → worked at → University of Paris" when Wikidata uses P108 (employer)?
   The property alignment table must be comprehensive.

3. **Should the evaluation profile use the same LLM as production?**
   Yes — the evaluation measures the production extraction quality. But cost may
   require a smaller model for CI smoke tests.

4. **How to weight novel discoveries in the overall score?**
   A high novel discovery rate is valuable but only if the discoveries are
   correct. Propose: novel discoveries enter the score only after human sampling
   validates ≥ 50% are true positives.

5. **Can we contribute our validated novel discoveries back to Wikidata?**
   Yes — Wikidata accepts bot contributions with proper references. This would
   be a nice community contribution and validation loop. But this is out of
   scope for the initial evaluation.
