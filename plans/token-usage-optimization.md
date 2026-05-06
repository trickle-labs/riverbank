# Token Usage Optimization Plan

_Created: 2026-05-07_

This report audits riverbank's current LLM token consumption, identifies waste
hotspots, proposes concrete optimizations, and quantifies the expected savings.

---

## 1. Current Token Flow Architecture

Every corpus ingest (`riverbank ingest`) passes through these LLM-calling stages:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 1 Preprocessing (per DOCUMENT)                                        │
│  ├── Document summary        : 1 LLM call  (up to 8 000 chars input)       │
│  └── Entity catalog          : 1 LLM call  (up to 12 000 chars input)      │
│                                                                             │
│ Phase 2 Corpus Preprocessing (per CORPUS, optional)                         │
│  ├── Per-doc summary pre-scan: N LLM calls (8 000 chars each, if Phase 1   │
│  │                              is not already enabled)                     │
│  ├── Cluster summaries       : K LLM calls (up to 10 summaries × ~100 w)   │
│  └── Corpus summary          : 1 LLM call  (~K cluster summaries)          │
│                                                                             │
│ Extraction (per FRAGMENT)                                                   │
│  └── Extraction call         : 1 LLM call  (system prompt + user text)     │
│                                                                             │
│ Post-Processing: Self-Critique Verification (per LOW-CONFIDENCE TRIPLE)     │
│  └── Verification call       : 1 LLM call  (evidence + triple, small)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Token Budget Per Fragment (current, with all features enabled)

| Prompt Component                    | Estimated Tokens | Notes                                  |
|-------------------------------------|:----------------:|----------------------------------------|
| Base extraction prompt (system)     |         ~200     | Fixed instructions                     |
| Document summary (injected)         |       80–150     | 2-3 sentences, max 100 words           |
| Entity catalog (injected)           |     200–600      | Up to 50 entities × ~8 tokens each     |
| Allowed predicates list (injected)  |      50–150      | Depends on profile size                |
| Few-shot examples (injected)        |     100–250      | 3 examples × ~40 tokens each           |
| Corpus context (Phase 2, injected)  |     100–300      | Corpus + cluster + doc context layers  |
| Fragment text (user message)        |    400–2 000     | Capped by `max_fragment_tokens: 2000`  |
| **Total input per fragment**        |  **1 130–3 650** |                                        |

| Output Component                    | Estimated Tokens | Notes                                  |
|-------------------------------------|:----------------:|----------------------------------------|
| Extracted triples (JSON)            |    200–1 500     | ~50 tokens per triple × 5–30 triples   |
| **Total output per fragment**       |  **200–1 500**   |                                        |

### 1.2 Token Budget Multipliers

For a 10-document corpus (typical Markdown, ~2 000 chars/doc, 3 fragments each):

| Stage                         | Calls | Input Tokens   | Output Tokens | Total        |
|-------------------------------|------:|:--------------:|:-------------:|:------------:|
| Phase 1 summaries (10 docs)   |    10 | ~20 000        | ~1 500        | 21 500       |
| Phase 1 entity catalogs       |    10 | ~25 000        | ~7 000        | 32 000       |
| Phase 2 cluster summaries     |     3 | ~2 400         | ~600          | 3 000        |
| Phase 2 corpus summary        |     1 | ~600           | ~100          | 700          |
| Extraction (30 fragments)     |    30 | ~60 000        | ~21 000       | 81 000       |
| Verification (~20 triples)    |    20 | ~6 000         | ~400          | 6 400        |
| **Total**                     |**74** | **~114 000**   | **~30 600**   | **~144 600** |

**Key insight:** extraction dominates, but preprocessing overhead (53 500 tokens)
is 37% of the total and grows linearly with corpus size — NOT fragment count.

---

## 2. Waste Hotspots

### 2.1 Entity Catalog Re-injection (HIGH IMPACT)

**Problem:** The full entity catalog (up to 50 entities, ~400–600 tokens) is
injected into EVERY fragment's extraction prompt, even though most fragments
reference only 3–8 of those entities.

**Location:** `preprocessors/__init__.py` → `build_extraction_prompt()`

**Waste estimate:** For 30 fragments × 50 entities, we inject 1 500 entity
references when only ~300 are relevant. **~12 000 wasted tokens per corpus.**

### 2.2 Redundant System Prompt (MEDIUM IMPACT)

**Problem:** The extraction system prompt (`_DEFAULT_PROMPT`) is ~200 tokens
of static instruction text. It's sent identically in every single extraction
call. Most API providers cache repeated system prompt prefixes, but Ollama
(our primary local provider) does not currently support prompt caching.

**Location:** `extractors/instructor_extractor.py` → `_extract_with_llm()`

**Waste estimate:** 200 tokens × 30 fragments = **6 000 tokens repeated.**
(With OpenAI/Anthropic prompt caching this is already free; with Ollama it's
real compute time.)

### 2.3 Few-Shot Examples Are Fragment-Agnostic (MEDIUM IMPACT)

**Problem:** 3 randomly-selected few-shot examples are injected into every
fragment regardless of the fragment's content. They may be semantically
irrelevant (e.g., a "pipe" example injected into a fragment about "operators").

**Location:** `preprocessors/__init__.py` → `FewShotInjector.inject()`

**Waste estimate:** ~150 tokens × 30 fragments = **4 500 tokens, with low
signal-to-noise ratio.** Reducing to 1 relevant example would save ~100
tokens/fragment while potentially improving quality.

### 2.4 Full Document Text Sent to Preprocessing (MEDIUM IMPACT)

**Problem:** Document summary uses up to 8 000 chars (≈2 000 tokens) of the
document text. Entity catalog uses up to 12 000 chars (≈3 000 tokens). For
short documents (< 3 000 chars), the full text is sent anyway — no savings
from the cap — but the overhead of TWO LLM calls (summary + catalog) is
disproportionate.

**Location:** `preprocessors/__init__.py` → `_extract_summary()`,
`_extract_entity_catalog()`

**Waste estimate:** For documents < 3 000 chars, one merged preprocessing call
would save **~50% of preprocessing tokens (1 call vs 2).**

### 2.5 Verbose Output Schema (MEDIUM IMPACT)

**Problem:** The extraction LLM produces verbose JSON output with repeated
field names per triple. Evidence spans include full verbatim excerpts (which
are already in the source text) and redundant `char_start` / `char_end` when
the excerpt text is present.

**Location:** `extractors/instructor_extractor.py` → `_TripleIn` schema

A single extracted triple currently looks like:
```json
{
  "subject": "ex:sesam-pipe",
  "predicate": "schema:isPartOf",
  "object_value": "ex:sesam-system",
  "confidence": 0.92,
  "evidence": {
    "char_start": 142,
    "char_end": 201,
    "excerpt": "A pipe is a component that belongs to a system.",
    "page_number": null
  }
}
```

**Waste estimate:** ~50 tokens per triple. With 15 triples per fragment, that's
**750 output tokens per fragment where ~300 could suffice** with a compact
schema.

### 2.6 Verification Sends Full Evidence Excerpts (LOW IMPACT)

**Problem:** The verifier caps evidence at 2 000 chars per triple. Most
evidence excerpts are 50–200 chars — this is fine. But the system prompt and
template are ~250 tokens of static text per call.

**Location:** `postprocessors/verify.py` → `_verify_triple()`

**Waste estimate:** 250 tokens × 20 calls = **5 000 tokens.** Batching
verification (multiple triples per call) would cut this to ~1 000 tokens.

### 2.7 Phase 2 Pre-Scan Duplicates Phase 1 Work (LOW-MEDIUM IMPACT)

**Problem:** When both Phase 1 (`preprocessing.enabled`) and Phase 2
(`corpus_preprocessing.enabled`) are enabled, the corpus pre-scan calls
`_extract_summary()` for each document — but then Phase 1's `preprocess()`
calls it AGAIN per document. The summary is computed twice.

**Location:** `pipeline/__init__.py` lines 268–286 vs 369–380

**Waste estimate:** N documents × ~2 000 input tokens =
**~20 000 wasted tokens for a 10-doc corpus.**

---

## 3. Optimization Strategies

### 3.1 Per-Fragment Entity Catalog Filtering

**Technique:** Before injecting the entity catalog, filter it to only include
entities whose `label` or `aliases` appear in the fragment text.

**Implementation:**
```python
def build_extraction_prompt(self, result, profile, fragment_text=""):
    # ... existing code ...
    if result.entity_catalog and fragment_text:
        text_lower = fragment_text.lower()
        relevant = [
            e for e in result.entity_catalog
            if e.label.lower() in text_lower
            or any(a.lower() in text_lower for a in e.aliases)
        ]
    else:
        relevant = result.entity_catalog
    # Use `relevant` instead of full catalog
```

**Savings:** ~300–400 input tokens per fragment (50 → ~10 entities).  
**Effort:** 1–2 hours. No new dependencies.  
**Risk:** Very low. Worst case: a fragment mentions an entity by a surface form
not in the alias list; mitigated by keeping a small "always inject" list of
high-frequency entities.

### 3.2 Merged Preprocessing for Short Documents

**Technique:** For documents below a size threshold (e.g., < 4 000 chars),
combine the summary and entity catalog into a single LLM call with a merged
prompt. This halves the number of preprocessing calls for small documents.

**Implementation:** New `_extract_combined()` method using a merged prompt:
```
Summarize this document in 2-3 sentences AND produce a canonical entity catalog.
Return JSON: {"summary": "...", "entities": [...]}
```

**Savings:** ~2 000 input tokens per small document (eliminates one call).  
**Effort:** 2–3 hours.  
**Risk:** Slightly lower quality for the merged output vs. dedicated calls.
Mitigated by only merging for short documents where context window pressure
is not an issue.

### 3.3 Compact Output Schema

**Technique:** Replace verbose JSON field names with short keys and make
evidence output optional when character offsets are provided.

**New schema:**
```python
class _TripleCompact(BaseModel):
    s: str          # subject IRI
    p: str          # predicate IRI
    o: str          # object value
    c: float        # confidence
    e: str          # evidence excerpt (verbatim)
    cs: int         # char_start
    ce: int         # char_end
```

**Savings:** ~20 tokens per triple × 15 triples = **300 output tokens per
fragment.** Over 30 fragments: **9 000 output tokens saved.**  
**Effort:** 3–4 hours (need to update extractor + all downstream consumers).  
**Risk:** Slightly harder to debug raw LLM output. Mitigated by mapping back
to verbose names in `ExtractionResult`.

### 3.4 Batched Verification

**Technique:** Instead of one LLM call per low-confidence triple, batch 5–10
triples into a single verification call. The system prompt is sent once and the
LLM evaluates multiple triples.

**Implementation:**
```
Source text: [excerpt 1]
Triple 1: (s, p, o)

Source text: [excerpt 2]
Triple 2: (s, p, o)

...

For each triple, respond with:
[{"id": 1, "supported": true, "confidence": 0.8}, ...]
```

**Savings:** For 20 triples: 20 × 250 (system prompt) → 1 × 250 + 20 × 80
(triple text) = **~3 400 tokens saved.**  
**Effort:** 4–6 hours (batch logic, error handling per item).  
**Risk:** One parse failure could lose the entire batch. Mitigated by chunking
into groups of 5 with retry-per-chunk.

### 3.5 Semantic Few-Shot Selection

**Technique:** Instead of random selection, embed the fragment text and the
golden examples, then select the top-K most similar examples by cosine
similarity. Alternatively, select examples that share the same predicate types
expected in the current fragment's topic.

**Implementation:**
```python
# In FewShotInjector._select()
if self._cfg.selection == "semantic":
    fragment_embedding = self._embed(fragment_text)
    scored = [(cosine_sim(fragment_embedding, ex_emb), ex) for ex, ex_emb in self._embedded_examples]
    scored.sort(reverse=True)
    return [ex for _, ex in scored[:n]]
```

**Savings:** Reduce from 3 examples to 1–2 highly relevant ones:
~80–150 tokens per fragment.  
**Effort:** 4–6 hours. Needs embeddings at injector init time.  
**Risk:** Embedding cost at startup (negligible — uses local model).
Quality may degrade if golden examples are too few to have meaningful diversity.

### 3.6 Deduplicate Phase 2 Pre-Scan

**Technique:** Cache the Phase 1 document summary so Phase 2 pre-scan doesn't
recompute it.

**Implementation:** Store summaries in a `{source_iri: summary}` dict that is
passed between Phase 1 and Phase 2 pre-scan. If a summary already exists for a
source IRI, skip the LLM call.

**Savings:** N documents × ~2 000 tokens = **20 000 tokens for 10 docs.**  
**Effort:** 1 hour. Pure plumbing.  
**Risk:** None — data is already computed, just not shared.

### 3.7 Token Budget Manager

**Technique:** Introduce a `TokenBudgetManager` that caps total input tokens per
fragment. When the assembled prompt exceeds the budget, components are trimmed
in priority order:

1. Few-shot examples (drop last, then all)
2. Corpus context (Phase 2 context block)
3. Entity catalog (truncate to top-10 by relevance)
4. Document summary (truncate)
5. Fragment text (NEVER truncated)

**Implementation:**
```python
@dataclass
class TokenBudget:
    max_input_tokens: int = 3000  # profile-configurable
    priority_order: list[str] = field(default_factory=lambda: [
        "few_shot", "corpus_context", "entity_catalog", "doc_summary", "fragment"
    ])
```

**Savings:** Prevents worst-case prompt explosion (3 650 → capped at 3 000).
Saves **~650 tokens/fragment** in the worst case (large catalog + Phase 2 +
few-shot + large fragment).  
**Effort:** 6–8 hours. Needs tokenizer integration (tiktoken for OpenAI,
approximate for Ollama).  
**Risk:** Medium — token counting adds latency. Mitigated by using byte-length
estimation (÷ 4 ≈ token count) for local models where precision doesn't matter.

### 3.8 Prompt Caching (Provider-Level)

**Technique:** Leverage OpenAI's prompt caching (automatic for repeated system
prompts) and Anthropic's `cache_control` header. For Ollama, use the `/api/chat`
keep-alive feature to reuse KV cache across calls with identical system prompts.

**Implementation:**
- For OpenAI/Anthropic: already active automatically for system prompts.
- For Ollama: set `keep_alive: "5m"` and structure messages so the system prompt
  is identical across calls in the same ingest run (already the case).

**Savings:** The system prompt (~200 tokens) is cached after the first call.
For 30 fragments: **~5 800 input tokens saved** (not charged / not re-processed).  
**Effort:** 1–2 hours (verify keep-alive config is passed, add `cache_control`
for Anthropic).  
**Risk:** None — transparent provider optimization.

### 3.9 Adaptive Preprocessing (Skip for Small Documents)

**Technique:** Documents below a threshold (e.g., < 2 000 chars / 1 fragment)
don't benefit from preprocessing — the fragment IS the document. Skip
preprocessing entirely for single-fragment documents.

**Implementation:**
```python
# In _process_source():
if len(fragments) <= 1 and len(doc.raw_text) < 2000:
    extraction_profile = profile  # skip preprocessing
```

**Savings:** Eliminates 2 LLM calls per small document.
For a corpus with 5 small docs: **~10 000 tokens saved.**  
**Effort:** 30 minutes.  
**Risk:** Very low. The preprocessing value (entity canonicalization) is minimal
for single-fragment documents where there's no inter-fragment drift.

### 3.10 Evidence Excerpt Deduplication

**Technique:** When the same evidence excerpt appears in multiple triples from
the same fragment, store it once and reference by index in the output schema.

**Current:** 3 triples sharing the same evidence each output the excerpt.  
**Optimized:**
```json
{
  "evidence_pool": ["A pipe belongs to a system.", "Systems process data."],
  "triples": [
    {"s": "ex:pipe", "p": "schema:isPartOf", "o": "ex:system", "c": 0.9, "ei": 0},
    {"s": "ex:pipe", "p": "rdf:type", "o": "ex:Component", "c": 0.85, "ei": 0},
    {"s": "ex:system", "p": "ex:processes", "o": "ex:data", "c": 0.8, "ei": 1}
  ]
}
```

**Savings:** ~15–30 output tokens per shared excerpt × ~5 instances per
fragment = **75–150 tokens per fragment.**  
**Effort:** 3–4 hours.  
**Risk:** LLMs may struggle with the reference-by-index pattern. May increase
retry rate. Test carefully with local models.

---

## 4. Roadmap Feature Token Impact Analysis

Several v0.12.0–v0.13.0 features will **increase** token consumption.
Planning mitigations now prevents cost surprises.

### 4.1 v0.12.0 — Permissive Extraction (Phase A)

| New Feature                        | Token Impact             | Mitigation                             |
|------------------------------------|:------------------------:|----------------------------------------|
| Ontology-grounded extraction       | +50–100 input/fragment   | Short predicate list, use compact form |
| CQ-guided extraction objectives    | +80–150 input/fragment   | Cap at 5 CQs, compress format          |
| Permissive prompt (tiered guide)   | +50–100 input/fragment   | Replace, don't append — net ~same      |
| Overlapping fragments              | +30–40% more fragments   | Already unchanged content → hash skip  |
| Safety cap (50 triples max)        | Saves output tokens      | Prevents 1 500+ token outputs          |
| Pre-write structural filtering     | Zero token impact        | Post-extraction filter, no LLM call    |

**Net v0.12.0 impact:** +15–25% more input tokens per fragment from prompt
enrichment, but +30–40% more fragments from overlapping windows.
**Total increase: ~45–65%.** Mitigations from §3 should be applied first to
offset this.

### 4.2 v0.12.1 — Permissive Extraction (Phase B)

| New Feature                        | Token Impact             | Mitigation                             |
|------------------------------------|:------------------------:|----------------------------------------|
| Noisy-OR accumulation              | Zero (math, no LLM)     | —                                      |
| `promote-tentative`                | Zero (graph operation)   | —                                      |
| `explain-rejections`               | Zero (query + format)    | —                                      |
| Functional predicate hints         | +20–40 input/fragment    | Only inject for functional predicates  |

**Net v0.12.1 impact:** Minimal. This is primarily a post-extraction phase.

### 4.3 v0.13.0 — Entity Quality

| New Feature                        | Token Impact             | Mitigation                             |
|------------------------------------|:------------------------:|----------------------------------------|
| Predicate normalization            | Zero (embedding + math)  | —                                      |
| Incremental entity linking         | +50–100 input/fragment   | Cap injected entities at top-K=10      |
| Knowledge-prefix adapter           | +100–300 input/fragment  | Budget manager caps at 200 tokens      |
| Auto few-shot expansion            | +50–100 input/fragment   | Still capped by max_examples=3         |
| `induce-schema`                    | One-time large call      | Run once per corpus lifecycle          |
| Contradiction detection            | Zero (graph queries)     | —                                      |
| Quality benchmarks                 | Re-extraction calls      | Use same budget as normal ingest       |

**Net v0.13.0 impact:** +100–400 tokens per fragment from knowledge-prefix
and entity injection. **Must** be paired with token budget manager (§3.7) and
per-fragment catalog filtering (§3.1).

### 4.4 v0.14.0 — Structural Improvements

| New Feature                        | Token Impact             | Mitigation                             |
|------------------------------------|:------------------------:|----------------------------------------|
| Constrained decoding (grammar)     | **Saves 20–30% output** | Prevents malformed JSON retries        |
| Semantic chunking                  | Better-sized fragments   | Fewer too-large fragments → less waste |
| SHACL validation                   | Zero (post-extraction)   | —                                      |
| SPARQL CONSTRUCT rules             | Zero (post-extraction)   | —                                      |
| OWL 2 RL forward-chaining          | Zero (pure inference)    | —                                      |

**Net v0.14.0 impact:** Likely **negative** (saves tokens). Constrained
decoding is the single biggest output token optimization on the roadmap.

---

## 5. Quantified Savings Summary

Assuming a 10-document corpus (30 fragments, 20 verification triples):

| Optimization                              | Input Saved | Output Saved | Total Saved | % of Baseline |
|-------------------------------------------|:-----------:|:------------:|:-----------:|:-------------:|
| 3.1 Per-fragment entity filtering         | 10 500      | 0            | 10 500      | 7.3%          |
| 3.2 Merged preprocessing (short docs)     | 5 000       | 0            | 5 000       | 3.5%          |
| 3.3 Compact output schema                 | 0           | 9 000        | 9 000       | 6.2%          |
| 3.4 Batched verification                  | 3 400       | 0            | 3 400       | 2.4%          |
| 3.5 Semantic few-shot (3→1–2 examples)    | 3 000       | 0            | 3 000       | 2.1%          |
| 3.6 Deduplicate Phase 2 pre-scan          | 20 000      | 0            | 20 000      | 13.8%         |
| 3.7 Token budget manager                  | 6 000       | 0            | 6 000       | 4.1%          |
| 3.8 Prompt caching (Ollama keep-alive)    | 5 800       | 0            | 5 800       | 4.0%          |
| 3.9 Adaptive preprocessing (skip small)   | 10 000      | 0            | 10 000      | 6.9%          |
| 3.10 Evidence excerpt deduplication       | 0           | 4 500        | 4 500       | 3.1%          |
| **TOTAL**                                 | **63 700**  | **13 500**   | **77 200**  | **53.4%**     |

**Baseline:** ~144 600 tokens (full pipeline, all features enabled).  
**After all optimizations:** ~67 400 tokens — a **53% reduction.**

---

## 6. Implementation Priority Matrix

### Phase 1 — Quick Wins (ship before v0.12.0, ≤ 1 day total)

| # | Optimization | Effort | Savings | Priority |
|---|---|---|---|---|
| 1 | Deduplicate Phase 2 pre-scan (§3.6) | 1 hour | 20 000 tokens | **P0** |
| 2 | Adaptive preprocessing for small docs (§3.9) | 30 min | 10 000 tokens | **P0** |
| 3 | Per-fragment entity catalog filtering (§3.1) | 2 hours | 10 500 tokens | **P0** |
| 4 | Prompt caching / Ollama keep-alive (§3.8) | 1 hour | 5 800 tokens | **P1** |

**Total Phase 1:** ~4.5 hours, ~46 300 tokens saved (32% reduction).

### Phase 2 — Ship with v0.12.0

| # | Optimization | Effort | Savings | Priority |
|---|---|---|---|---|
| 5 | Compact output schema (§3.3) | 4 hours | 9 000 tokens | **P1** |
| 6 | Token budget manager (§3.7) | 6 hours | 6 000 tokens | **P1** |
| 7 | Merged preprocessing for short docs (§3.2) | 3 hours | 5 000 tokens | **P2** |

### Phase 3 — Ship with v0.13.0

| # | Optimization | Effort | Savings | Priority |
|---|---|---|---|---|
| 8 | Semantic few-shot selection (§3.5) | 5 hours | 3 000 tokens | **P2** |
| 9 | Batched verification (§3.4) | 5 hours | 3 400 tokens | **P2** |
| 10 | Evidence excerpt deduplication (§3.10) | 4 hours | 4 500 tokens | **P2** |

---

## 7. Profile YAML Extensions

New configuration keys to expose token optimization at the profile level:

```yaml
# Token optimization settings (v0.12.0)
token_optimization:
  # Per-fragment entity catalog filtering
  filter_entities_by_mention: true        # default: true
  min_entities_to_inject: 3               # always inject at least 3 entities

  # Adaptive preprocessing
  skip_preprocessing_below_chars: 2000    # skip for small documents
  merge_preprocessing_below_chars: 4000   # merge summary+catalog into one call

  # Token budget
  max_input_tokens_per_fragment: 3000     # hard cap (trim in priority order)

  # Few-shot
  few_shot_selection: semantic            # "random" | "fixed" | "semantic"
  max_few_shot_examples: 2               # reduced from default 3

  # Output
  compact_output_schema: true             # use short field names in response_model

  # Verification
  verification_batch_size: 5              # batch N triples per verification call
```

---

## 8. Monitoring and Observability

To validate optimization impact, add these metrics:

| Metric | Type | Labels |
|--------|------|--------|
| `riverbank_prompt_tokens_total` | Counter | `stage` (extraction, preprocessing, verification) |
| `riverbank_completion_tokens_total` | Counter | `stage` |
| `riverbank_tokens_saved_total` | Counter | `optimization` (entity_filter, budget_trim, ...) |
| `riverbank_prompt_token_budget_exceeded` | Counter | `fragment_key` |
| `riverbank_entity_catalog_filter_ratio` | Histogram | — |

These are already partially implemented in OTel span attributes. Promoting
them to Prometheus counters enables dashboard-driven optimization tuning.

---

## 9. Cost Implications

### Local Ollama (current default)

Token savings translate directly to **latency savings** — fewer tokens =
faster inference. A 53% token reduction ≈ 40–50% faster ingest (assuming
attention-bound, which local models are for prompt-heavy workloads).

### Cloud Providers (GPT-4o, Claude)

| Provider | Baseline Cost (10 docs) | After Optimization | Savings |
|----------|:-----------------------:|:------------------:|:-------:|
| GPT-4o ($5/M in, $15/M out) | $1.03 | $0.47 | **$0.56** |
| GPT-4o-mini ($0.15/M in, $0.60/M out) | $0.035 | $0.016 | **$0.019** |
| Claude 3.5 Sonnet ($3/M in, $15/M out) | $0.80 | $0.37 | **$0.43** |

For a production corpus of 1 000 documents (3 000 fragments):
- GPT-4o: **$103 → $47** per full ingest (saves $56)
- Over 12 monthly re-ingests: **$672/year saved**

---

## 10. Relationship to Incremental Compilation

The biggest long-term token optimization is **not re-processing unchanged
content.** The existing fragment-hash skip (`fragments_skipped_hash`) already
provides this for unchanged fragments. Combined with the §3 optimizations:

- **First ingest:** ~67 400 tokens (optimized) vs ~144 600 tokens (current)
- **Incremental re-ingest (10% changed):** ~6 740 tokens (only changed
  fragments re-processed)

Incremental compilation + token optimization together deliver a
**95% reduction** in token usage for steady-state corpus maintenance.

---

## 11. Conclusion

The three highest-leverage actions are:

1. **Deduplicate Phase 2 pre-scan** (§3.6) — eliminates redundant LLM calls,
   14% savings, 1 hour effort.
2. **Per-fragment entity filtering** (§3.1) — reduces injection bloat, 7%
   savings, 2 hours effort.
3. **Adaptive preprocessing** (§3.9) — skips unnecessary work for small docs,
   7% savings, 30 minutes effort.

These three alone deliver **28% token reduction** in under 4 hours of
implementation. Applying all Phase 1 optimizations (4.5 hours total) delivers
32% savings — enough to fully offset the token increase from v0.12.0's
permissive extraction features.
