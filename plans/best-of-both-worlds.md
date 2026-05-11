# Best of Both Worlds: Intelligent Predicate Guidance + Open-Vocabulary Discovery

> **Date:** 2026-05-11  
> **Status:** Strategy document  
> **Context:** We achieved 44 unique predicates from a single Marie Curie article using
> `predicate_inference.use_for_extraction: false`. This document explores what more is possible.

---

## The Tension

Two extraction philosophies are in fundamental conflict:

| Approach | Advantage | Problem |
|---|---|---|
| **Constrained** (`allowed_predicates` list) | Consistent, canonical vocabulary; no sprawl | Misses domain-specific facts; requires manual schema work |
| **Open-vocabulary** (empty `allowed_predicates`) | Discovers everything relevant | Produces noisy, inconsistent predicate names; hard to query |

The current solution — run predicate inference to propose predicates, then ignore them as constraints — gets us 44 unique predicates but with sprawl (`was_died_in`, `was_born_in_empire`, `isolated_pure_radium_metal`). The ideal is **rich discovery with semantic cohesion**.

---

## What We Have Now

**Pipeline:** Distillation → Preprocessing → Predicate inference (propose only) → Extraction (open-vocabulary) → Entity resolution

**Settings:**
```yaml
predicate_inference:
  enabled: true
  confidence_threshold: "all"
  use_for_extraction: false   # proposals are informational only
  max_predicates: 100
```

**Result:** 44 unique predicates, 65 triples — good recall, medium precision, some naming inconsistency.

---

## Strategies for Better Balance

### Strategy 1: Prompt-Injected Predicate Hints (Low Cost, High Leverage)

**What:** Instead of using proposals as hard constraints (`allowed_predicates`), inject them into the extraction prompt as soft guidance:

```
You may use any predicate you find appropriate. The following predicates have
been identified as especially relevant to this document and should be preferred
when applicable:
  ex:discovered, ex:collaborated_with, ex:received_award, ex:published_paper_about, ...

Do not limit yourself to these — propose new predicates where appropriate.
```

**How:** Modify `SchemaProposer.propose()` to return a `suggested_predicates` list separately from `allowed_predicates`. Pass suggestions into the extraction prompt template in `pipeline/__init__.py`.

**Trade-offs:**
- ✅ No additional LLM calls
- ✅ Consistent with existing predicate inference infrastructure
- ✅ Gets the guidance effect without hard constraint
- ⚠️ Requires extraction prompt changes
- ⚠️ LLM may still diverge from suggestions

**Expected gain:** ~20% reduction in synonym predicates, same recall depth.

---

### Strategy 2: Two-Pass Extraction (Best Recall, Moderate Cost)

**What:** Run extraction twice per document:

- **Pass 1 (constrained):** Use predicate inference proposals as strict `allowed_predicates`. Gets high-precision, schema-coherent triples.
- **Pass 2 (open):** Use no constraints. Discovers domain-specific facts that didn't fit the proposed schema.
- **Merge:** Deduplicate and union the results.

**How:** This is already partially supported by the `sequence` parameter in `IngestPipeline.run()` which runs multiple `run_mode` passes. Could be extended to support named extraction passes with different profile overrides.

**Trade-offs:**
- ✅ Maximum recall — captures both well-known schema and novel facts
- ✅ Clean separation: constrained triples are more reliable
- ⚠️ 2× LLM extraction cost
- ⚠️ Deduplication needed (same fact extracted with different predicate names)
- ⚠️ Requires pipeline architecture change (multi-profile pass support)

**Expected gain:** 50-70% more triples than single-pass constrained, with better precision than single-pass open.

---

### Strategy 3: Embedding-Based Predicate Canonicalization (Post-Extraction)

**What:** After open-vocabulary extraction, use embedding similarity to cluster semantically equivalent predicates and canonicalize to a single representative:

```
was_born_in (0.97 similarity) → has_birth_place
born_in (0.95)               → has_birth_place
birthplace (0.91)            → has_birth_place
```

**How:** Extract all unique predicates from the knowledge graph. Embed them using `nomic-embed-text`. Cluster with DBSCAN or k-means. For each cluster, pick the most frequent predicate name (or ask an LLM to pick the canonical one). Rewrite all triples in the cluster to the canonical predicate.

This is related to the existing `vocab_predicates_collapsed` vocabulary normalisation pass, but driven by semantic similarity rather than edit distance.

**Trade-offs:**
- ✅ Works post-extraction, no re-ingestion needed
- ✅ Dramatically improves SPARQL queryability
- ✅ `nomic-embed-text` is already in the stack
- ⚠️ Requires tuning similarity threshold
- ⚠️ May merge genuinely distinct predicates (e.g., `studied_in` vs `worked_in`)
- ⚠️ Canonical selection needs care

**Expected gain:** Reduces predicate count from 44 to ~15-20 well-defined canonical predicates, while retaining the same factual coverage.

---

### Strategy 4: Seed Predicates + Inference Extension

**What:** Define a small set of universal predicates that should always be detected (birthdate, nationality, occupation, etc.), and let predicate inference add domain-specific ones on top.

**Profile:**
```yaml
allowed_predicates:
  - ex:born_in
  - ex:died_in
  - ex:nationality
  - ex:occupation
  - ex:received_award
  - ex:worked_at

predicate_inference:
  enabled: true
  use_for_extraction: false   # still open-vocabulary, but seeds bias discovery
```

Or use them as prompt hints (Strategy 1) to anchor the extraction vocabulary.

**Trade-offs:**
- ✅ Low effort, immediate improvement to naming consistency
- ✅ Seed predicates translate well across documents
- ⚠️ Needs manual curation of seeds per domain (biography, science, sports, etc.)
- ⚠️ Risk of over-anchoring: LLM may overuse seed predicates even when irrelevant

---

### Strategy 5: Predicate Hierarchy Inference

**What:** Instead of a flat list of predicates, propose a typed schema: some predicates are for **entities** (subjects, IRIs), some for **attributes** (literals, dates, counts), and some for **relationships** (links between named entities). Apply different constraints per category.

**Example:**
```json
{
  "entity_predicates":    ["ex:discovered", "ex:collaborated_with"],
  "attribute_predicates": ["ex:birth_date", "ex:publication_year"],
  "relationship_predicates": ["ex:affiliated_with", ex:member_of"]
}
```

Use entity predicates for IRI objects (constrained), allow free naming for attributes (literals are self-documenting).

**How:** Extend `SchemaProposer._INFERENCE_PROMPT` to request category-typed predicates. Inject typed suggestions selectively into the extraction prompt.

**Trade-offs:**
- ✅ Reduces sprawl specifically in IRI predicate names (the noisy part)
- ✅ Literal predicates matter less for SPARQL queryability
- ⚠️ More complex prompt engineering
- ⚠️ Category detection is imperfect

---

### Strategy 6: Corpus-Level Predicate Accumulation

**What:** Run predicate inference across the whole corpus first, accumulate and deduplicate the proposals, then use the corpus-level vocabulary for all subsequent extraction runs.

```
Step 1: riverbank infer-schema --corpus ~/.riverbank/article_cache/ --output corpus-schema.yaml
Step 2: riverbank ingest --corpus ... --schema corpus-schema.yaml
```

This turns the cold-start problem (no schema for new domain) into a one-time corpus scan.

**How:** Add a `riverbank infer-schema` CLI command that runs `SchemaProposer.propose()` on a sample of corpus documents, aggregates proposals by frequency, and outputs a ranked predicate list.

**Trade-offs:**
- ✅ Corpus-level schema is much richer than per-document proposals
- ✅ One-time cost, cached result
- ✅ Foundation for `riverbank induce-schema` which already exists in the CLI
- ⚠️ Requires corpus to be available upfront (warm-start only)
- ⚠️ High-frequency predicates may be generic; rare domain predicates may be missed

---

### Strategy 7: Confidence-Weighted Predicate Injection

**What:** Include proposed predicates in the extraction prompt with their confidence scores, so the LLM can calibrate how strongly to prefer them:

```
High-confidence predicates (strongly prefer):
  ex:discovered, ex:received_award, ex:born_in

Medium-confidence predicates (use when relevant):
  ex:collaborated_with, ex:studied_at

Exploratory predicates (consider but not required):
  ex:contributed_to_theory_of, ex:was_contemporary_with
```

**Trade-offs:**
- ✅ Richer guidance than a flat suggestion list
- ✅ Preserves open-vocabulary freedom at the exploratory tier
- ⚠️ Larger extraction prompt (more tokens)
- ⚠️ Requires prompt template changes

---

## Recommended Implementation Order

| Priority | Strategy | Effort | Gain | Version |
|---|---|---|---|---|
| 1 | **Prompt-injected hints** (Strategy 1) | Low | High | v0.18.1 |
| 2 | **Seed predicates** (Strategy 4) | Low | Medium | v0.18.1 |
| 3 | **Embedding canonicalization** (Strategy 3) | Medium | High | v0.19.0 |
| 4 | **Corpus-level accumulation** (Strategy 6) | Medium | High | v0.19.0 |
| 5 | **Two-pass extraction** (Strategy 2) | High | Very High | v0.20.0 |
| 6 | **Predicate hierarchy** (Strategy 5) | High | Medium | v0.20.0 |
| 7 | **Confidence weighting** (Strategy 7) | Low | Low-Medium | v0.18.2 |

---

## Near-Term Quick Win: Strategy 1 + Strategy 4

The highest-leverage change with minimal risk:

1. Modify `pipeline/__init__.py` to inject predicate inference proposals into the extraction prompt as soft hints rather than constraints.
2. Add a `seed_predicates` section to the profile YAML for domain-common predicates.
3. Keep `use_for_extraction: false` so extraction remains open-vocabulary.

Expected result: ~30 unique predicates, naming consistency closer to proposed schema, full recall of domain-specific facts.

---

## Metrics for Success

When evaluating any of these strategies, measure:

| Metric | Current | Target |
|---|---|---|
| Unique predicates per document | 44 | 25-35 (fewer, more consistent) |
| Triples per document | 65 | 60-80 (similar or better recall) |
| Synonym predicate pairs (manual) | ~8 | < 3 |
| SPARQL query success rate | ~60% | > 85% |
| F1 vs ground truth | ~0.45 | > 0.60 |

Use `eval/ground-truth/marie-curie.jsonl` (45 verified triples) as the benchmark.
