# Extract More Triples: A Permissive Extraction Strategy

> **Core thesis:** For small-to-medium corpora (< 200 documents), the current
> extraction pipeline is overly conservative — it produces too few triples per
> fragment because the LLM is instructed to only extract "claims directly supported
> by the text." A better strategy is to **extract broadly and let evidence
> accumulation, corroboration, and contradiction drive confidence** rather than
> relying on the LLM's self-assessed certainty at extraction time.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Root Causes of Under-Extraction](#2-root-causes-of-under-extraction)
3. [Proposed Architecture: Permissive Extract → Accumulate → Promote](#3-proposed-architecture-permissive-extract--accumulate--promote)
4. [Detailed Design](#4-detailed-design)
5. [Pros and Cons](#5-pros-and-cons)
6. [Impact on Small Corpora](#6-impact-on-small-corpora)
7. [Implementation Plan](#7-implementation-plan)
8. [Risk Mitigations](#8-risk-mitigations)
9. [Metrics & Success Criteria](#9-metrics--success-criteria)

---

## 1. Problem Statement

### What we observe

With the example 3-document corpus (`examples/markdown-corpus/`), a typical
extraction run produces **5–15 triples per fragment** and **30–60 triples total**
for the whole corpus. Many of these are basic type assertions (`rdf:type`) and
labels (`rdfs:label`). The graph is sparse — `validate-graph` competency
questions fail not because the wrong facts are extracted, but because the *right
facts are never extracted at all*.

### Why this matters especially for small corpora

In a 200-document corpus, there are many opportunities for the same fact to
appear in multiple documents, allowing confidence to accumulate over time. But
in a 3–20 document corpus:

- Each fact typically appears in **exactly one fragment**.
- There is no second chance — if the LLM skips a triple because it's "only
  implied" rather than "explicitly stated," that fact is permanently lost.
- The graph remains too sparse for meaningful reasoning or query answering.
- CQ coverage stagnates below 60% because the extraction is too cautious.

### The root metric

```
Triple yield = extracted_triples / (potential_triples_in_source × recall_ceiling)
```

Current estimated yield: **25–40%** (based on manual review of missed triples
in `validate-graph` failures). Target: **70–85%** with confidence-based filtering
at query time.

---

## 2. Root Causes of Under-Extraction

### 2.1 Conservative prompt language

The current default prompt says:

```
Only extract claims directly supported by the text.
```

This instruction causes the LLM to skip:
- **Implied relationships** ("Pipeline reads from the dataset" → implies
  `pipeline schema:dependsOn dataset`, but the word "depends" isn't in the text)
- **Background knowledge assertions** (the LLM knows `Pipeline rdf:type Component`
  but the text doesn't say it explicitly)
- **Compositional facts** (text says "A has parts B and C" → should produce 2
  triples, but LLM sometimes only produces 1)
- **Inverse relationships** (text says "B is part of A" → should also produce
  `A hasPart B`, but only one direction is extracted)

### 2.2 LLM confidence self-assessment is unreliable

Research (Zhu et al. 2023, Kadavath et al. 2022) shows that LLM confidence
calibration is poor:
- Models tend toward **overconfidence** on wrong facts (0.8+ for hallucinations)
- Models tend toward **underconfidence** on implied facts (0.4–0.5 for true
  inferences)
- The confidence scores are **not probabilities** — they're pattern-matching
  outputs that reflect how "explicitly stated" something sounds, not how likely
  it is to be true.

Result: legitimate triples with confidence 0.4–0.6 (implied but correct) are
treated the same as actual hallucinations in the current pipeline.

### 2.3 Batch-level SHACL routing loses granularity

The current pipeline makes a **batch-level** routing decision:

```python
score = shacl_score(conn, profile.named_graph, profile)
threshold = _confidence_threshold(profile)
target_graph = profile.named_graph if score >= threshold else "<draft>"
```

This means ALL triples from a fragment go to the same graph. A fragment might
produce 3 high-confidence triples and 5 lower-confidence but still valid triples
— all 8 get routed together based on the graph's overall SHACL score, not
individual triple quality.

### 2.4 Evidence span requirement rejects implied triples

```python
if ev.excerpt and ev.excerpt not in text:
    logger.warning("Rejecting triple — excerpt not found in source text")
    continue
```

This citation-grounding check is correct for preventing fabrication, but it
implicitly requires that every triple have a *verbatim* text span supporting it.
Implied or inferred relationships (which are still correct) don't have a single
quotable sentence — the LLM must either fabricate an excerpt (rejected) or
provide a partial one (often rejected due to off-by-one offsets).

### 2.5 No mechanism for evidence accumulation

Currently, if the same triple `(s, p, o)` is extracted from two different
fragments:
- The second write silently succeeds (pg_ripple deduplicates by SPO)
- The confidence of the **first** write persists — no boost from corroboration
- There is no record that two independent sources agree on this fact

---

## 3. Proposed Architecture: Permissive Extract → Accumulate → Promote

### Current model (conservative)

```
Fragment → LLM → "only explicit claims" → few high-conf triples → graph/trusted
```

### Proposed model (permissive with tiered confidence)

```
Fragment → LLM → extract ALL plausible facts → many triples at varied confidence
                                                       │
                                     ┌─────────────────┼──────────────────┐
                                     │                 │                  │
                              conf ≥ 0.75       0.35 ≤ conf < 0.75    conf < 0.35
                                     │                 │                  │
                                     ▼                 ▼                  ▼
                              graph/trusted     graph/tentative        DISCARD
                                     │                 │
                                     │    ┌────────────┘
                                     │    │ corroboration
                                     │    │ (same triple from other source)
                                     │    ▼
                                     │  confidence += noisy-OR
                                     │    │
                                     │    │ crosses 0.75?
                                     │    ├─── YES → PROMOTE to graph/trusted
                                     │    └─── NO  → stays in graph/tentative
                                     │
                                     ▼
                              CONTRADICTION detected?
                              (functional predicate with different object)
                                     │
                                     ├── YES → DEMOTE both, create ConflictRecord
                                     └── NO  → unchanged
```

### Key principles

1. **Extract everything above noise floor (0.35)** — the LLM should not
   self-censor
2. **Route by individual triple confidence** — not batch-level SHACL score
3. **Accumulate evidence** — same triple from N sources gets confidence boost
4. **Promote on threshold crossing** — tentative → trusted when confidence ≥ 0.75
5. **Demote on contradiction** — conflicting triples lose confidence
6. **Query-time filtering** — consumers choose their confidence floor

---

## 4. Detailed Design

### 4.1 New extraction prompt (permissive)

```
You are a knowledge graph compiler. Extract ALL plausible factual claims from
the following text as RDF triples.

EXTRACTION TIERS:
- Confidence 0.9–1.0: EXPLICIT — directly and unambiguously stated in the text
- Confidence 0.7–0.9: STRONG — clearly implied or easily derivable from the text
- Confidence 0.5–0.7: IMPLIED — reasonably inferred from context, requires some
  interpretation
- Confidence 0.35–0.5: WEAK — possible interpretation, may need corroboration
  from other documents

IMPORTANT: Extract implied relationships and type assertions even when the text
doesn't use those exact words. For example:
- "Pipeline reads from Dataset" → also extract (Pipeline, dependsOn, Dataset)
- "X is a component" → also extract (X, rdf:type, Component)
- "A consists of B and C" → extract BOTH (A, hasPart, B) AND (A, hasPart, C)

For weak inferences, use lower confidence (0.35–0.5). These will be validated
against other documents. It's better to extract a correct triple with low
confidence than to miss it entirely.

DO NOT extract:
- Pure speculation with no textual basis (confidence would be < 0.35)
- Triples about metadata (authors, dates) unless asked
```

### 4.2 Per-triple routing logic

Replace the current batch-level SHACL routing with per-triple confidence routing:

```python
TENTATIVE_FLOOR = 0.35
TRUSTED_THRESHOLD = 0.75

for triple in result.triples:
    if triple.confidence < TENTATIVE_FLOOR:
        stats["triples_discarded"] += 1
        continue  # noise floor — discard
    elif triple.confidence >= TRUSTED_THRESHOLD:
        target = profile.named_graph  # graph/trusted
    else:
        target = profile.tentative_graph  # graph/tentative

    load_triple_with_confidence(conn, triple, target)
    stats["triples_written"] += 1
```

### 4.3 Confidence accumulation (noisy-OR consolidation)

When writing a triple that already exists (same S, P, O):

```python
def consolidate_confidence(existing_confidence: float, new_confidence: float) -> float:
    """Bayesian noisy-OR: P(true) = 1 - ∏(1 - c_i)"""
    return 1.0 - (1.0 - existing_confidence) * (1.0 - new_confidence)
```

| Existing | New extraction | Consolidated | Action |
|----------|---------------|-------------|--------|
| 0.5 | 0.5 | 0.75 | **PROMOTE** (crosses threshold) |
| 0.4 | 0.4 | 0.64 | Stays tentative |
| 0.6 | 0.6 | 0.84 | Already trusted, confidence increases |
| 0.4 | 0.6 | 0.76 | **PROMOTE** |
| 0.8 | — (contradiction) | 0.6 | **DEMOTE** to tentative |

### 4.4 Promotion and demotion

**Promotion** (tentative → trusted):
- Triggered when consolidated confidence ≥ `TRUSTED_THRESHOLD`
- Triple is moved from `graph/tentative` to `graph/trusted`
- A `pgc:PromotionEvent` provenance record is created
- Stats: `triples_promoted += 1`

**Demotion** (trusted → tentative):
- Triggered when a conflicting triple is extracted for a functional predicate
- Both conflicting triples have confidence reduced by 30%
- If confidence drops below threshold → move to `graph/tentative`
- A `pgc:ConflictRecord` is created (existing v0.8.0 mechanism)
- Stats: `triples_demoted += 1`

### 4.5 Query-time confidence filtering

Default SPARQL queries should filter by confidence:

```sparql
# Standard query (only confident facts)
SELECT ?s ?p ?o WHERE {
  GRAPH <http://riverbank.example/graph/trusted> { ?s ?p ?o }
}

# Exploratory query (include tentative)
SELECT ?s ?p ?o ?c ?g WHERE {
  { GRAPH <http://riverbank.example/graph/trusted> { ?s ?p ?o } }
  UNION
  { GRAPH <http://riverbank.example/graph/tentative> { ?s ?p ?o } }
  OPTIONAL { ?s pgc:hasConfidence ?c }
  BIND(IF(BOUND(?g), ?g, "trusted") AS ?graph)
}
ORDER BY DESC(?c)
```

CLI integration:

```bash
# Default: only trusted graph
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o }"

# Include tentative
riverbank query --include-tentative "SELECT ?s ?p ?o WHERE { ?s ?p ?o }"

# Promote qualifying triples
riverbank promote-tentative --threshold 0.75 --dry-run
```

### 4.6 Profile YAML configuration

```yaml
extraction_strategy:
  mode: permissive              # "conservative" (default/current) or "permissive"
  tentative_floor: 0.35        # discard below this
  trusted_threshold: 0.75      # route to trusted above this
  accumulation: noisy_or       # "noisy_or", "max", or "latest"
  promote_on_accumulation: true # auto-promote when threshold crossed
  demote_on_conflict: true     # auto-demote on functional predicate conflict
  max_triples_per_fragment: 50 # safety cap to prevent runaway extraction
```

---

## 5. Pros and Cons

### Pros

| Benefit | Impact | Applies to small corpora? |
|---------|--------|---------------------------|
| **Higher recall** — facts that are implied but correct are no longer lost | +30–50% more triples | ✅ Critical — no second chance |
| **Evidence accumulation** — corroborated facts get stronger over time | Better precision ranking | ⚠️ Limited with few docs |
| **Graceful quality gradient** — no hard boundary between "in" and "out" | Better user experience | ✅ |
| **Self-healing** — tentative triples that get corroborated auto-promote | Reduced manual review | ⚠️ Needs >1 source per fact |
| **Nothing is permanently lost** — all plausible facts are preserved | Better CQ coverage | ✅ Directly addresses the problem |
| **Query-time flexibility** — different consumers can choose their confidence floor | More use cases | ✅ |
| **Contradiction detection** — conflicts surface rather than silently overwrite | Better data quality | ✅ |
| **Incremental improvement** — adding new documents to the corpus strengthens existing tentative triples | Growing quality | ✅ |
| **Aligns with how knowledge works** — hypotheses get strengthened or weakened by evidence | Philosophically sound | ✅ |

### Cons

| Drawback | Severity | Mitigation |
|----------|----------|-----------|
| **Storage growth** — 2–4x more triples stored (most in tentative) | Low | Storage is cheap; pg_ripple handles millions of triples |
| **Hallucination risk** — more aggressive extraction may include fabricated facts | Medium | Evidence span validation still rejects fabricated excerpts; tentative graph is clearly separated from trusted |
| **Correlated hallucination** — if multiple docs repeat the same wrong claim, noisy-OR promotes it | Medium | Source diversity scoring; self-critique verification at promotion time (not extraction time) |
| **LLM cost increase** — more output tokens per fragment (~30–50% more) | Low | Marginal cost for Ollama (free); ~$0.01–0.02 per corpus for cloud models |
| **Latency increase** — LLM generates more tokens per call | Low | Negligible for batch processing |
| **Complexity** — more moving parts (promotion, demotion, two graphs) | Medium | Progressive rollout: start with permissive prompt + per-triple routing only |
| **Noise in tentative graph** — low-quality triples accumulate without cleanup | Low | TTL-based expiry: tentative triples not promoted within N ingests get archived |
| **False precision** — users may over-trust tentative triples | Low | Clear UX: CLI shows tentative count separately; queries default to trusted-only |
| **Inverse relationship duplication** — extracting both directions doubles storage for symmetric predicates | Low | Deduplication at write time for known symmetric/inverse pairs |
| **Diminishing returns for single-source facts** — in a 3-doc corpus, most facts appear once, so noisy-OR accumulation rarely triggers | High for small corpora | Compensated by the primary benefit: higher single-pass recall |

### Net assessment

For **small corpora** (3–20 documents), the primary benefit is not accumulation
(which needs multiple sources) but rather **higher single-pass recall from the
permissive prompt**. The tentative graph serves as a staging area that preserves
facts the conservative prompt would discard entirely.

For **medium corpora** (20–200 documents), both benefits compound: higher
single-pass recall AND evidence accumulation.

For **large corpora** (200+ documents), the accumulation mechanism becomes the
dominant quality driver — individual extraction quality matters less because
corroboration filters for truth.

---

## 6. Impact on Small Corpora

### The 3-document scenario (our example corpus)

| Metric | Current (conservative) | Proposed (permissive) | Delta |
|--------|------------------------|----------------------|-------|
| Triples per fragment | 5–15 | 15–35 | +100–130% |
| Total triples (trusted) | 30–60 | 40–70 | +30% |
| Total triples (tentative) | 0 | 30–60 | NEW |
| CQ coverage (trusted only) | ~50% | ~65% | +15pp |
| CQ coverage (trusted + tentative) | ~50% | ~80% | +30pp |
| Entity duplication rate | 1.2x | 1.4x | Needs dedup |

### Why higher single-pass recall matters more than accumulation here

In a 3-document corpus:
- Most facts appear in exactly 1 fragment → noisy-OR doesn't help
- But 30–50% of correct facts are currently *never extracted* because they're
  "implied" rather than "explicit"
- The permissive prompt recaptures these at confidence 0.5–0.7
- They land in `graph/tentative` → visible to exploratory queries
- `validate-graph --include-tentative` shows dramatically better coverage

### The sweet spot: "one good document is enough"

With permissive extraction, a single well-written document about Pipeline
Architecture might produce:
- 10 explicit triples (confidence 0.8–1.0) → trusted
- 8 implied triples (confidence 0.5–0.7) → tentative
- 4 weak inferences (confidence 0.35–0.5) → tentative

vs. current conservative extraction:
- 10 explicit triples → trusted
- 0 implied/inferred → lost forever

Those 12 tentative triples are *correct* — they just can't be proven from a
single text excerpt. In a small corpus, preserving them (even at lower
confidence) is far better than losing them.

### When a second document is added

If a second document mentions some of the same concepts:
- 3–5 tentative triples get corroborated → confidence jumps to 0.75+ → PROMOTE
- The graph gets denser and more useful *without re-processing the first document*
- Incremental ingest (`riverbank ingest --mode delta`) naturally strengthens
  the graph over time

---

## 7. Implementation Plan

### Phase A: Permissive prompt + per-triple routing (v0.11.x)

**Effort:** 2–3 hours. Zero new dependencies.

1. Add `tentative_graph` field to `CompilerProfile` (default:
   `http://riverbank.example/graph/tentative`)
2. Add `extraction_strategy` config section to profile YAML
3. Replace batch-level SHACL routing with per-triple confidence routing
4. Add new prompt variant (permissive) selectable via
   `extraction_strategy.mode: permissive`
5. Add `--include-tentative` flag to `riverbank query`
6. Track stats: `triples_trusted`, `triples_tentative`, `triples_discarded`

### Phase B: Confidence accumulation + promotion (v0.12.x)

**Effort:** 4–6 hours.

1. Before writing a triple, check if it already exists (query by S, P, O)
2. If exists: apply noisy-OR consolidation, update confidence in-place
3. If consolidated confidence crosses threshold: move triple between graphs
4. Add `riverbank promote-tentative` CLI command
5. Add `pgc:PromotionEvent` provenance records
6. Add stats: `triples_promoted`, `triples_demoted`

### Phase C: Contradiction detection + demotion (v0.12.x)

**Effort:** 2–3 hours. Builds on existing v0.8.0 `ConflictRecord`.

1. For functional predicates: detect when new (s, p, o2) conflicts with
   existing (s, p, o1) where o1 ≠ o2
2. Reduce confidence of both triples by 30%
3. Demote if confidence drops below threshold
4. Create `pgc:ConflictRecord` (already exists in ontology)

### Phase D: TTL-based tentative cleanup (v0.13.x)

**Effort:** 1–2 hours.

1. Track `first_seen` timestamp for tentative triples
2. `riverbank gc-tentative --older-than 30d` archives stale tentative triples
3. Optional: auto-run after each ingest

---

## 8. Risk Mitigations

### Risk: Correlated hallucination promotion

**Scenario:** Three documents all say "Pipeline is maintained by Team X" (copied
from a template), but Team X was reassigned. Noisy-OR promotes this to 0.88
confidence.

**Mitigations:**
1. **Source diversity scoring** — only count corroboration from *distinct* source
   documents (not multiple fragments of the same doc).
2. **Self-critique at promotion time** — when a triple is about to be promoted,
   run one verification LLM call: "Is this fact consistent with the broader
   corpus context?" Cheap (one call per promotion, not per extraction).
3. **Temporal decay** — triples from older documents get reduced weight in the
   noisy-OR calculation. Fresh sources count more.

### Risk: Tentative graph becomes a junk drawer

**Mitigations:**
1. **TTL expiry** — tentative triples not promoted within N ingests are archived.
2. **SHACL validation on tentative** — structurally invalid tentative triples
   (wrong domain/range) are discarded immediately.
3. **Query default** — the standard `riverbank query` never touches tentative.
   Users must explicitly opt in with `--include-tentative`.

### Risk: Runaway extraction (too many triples per fragment)

**Mitigations:**
1. **Safety cap** — `max_triples_per_fragment: 50` in profile config. Beyond
   this, the pipeline logs a warning and keeps only the top 50 by confidence.
2. **Token budget** — if the LLM response exceeds token limits, instructor
   already handles truncation gracefully.

### Risk: Entity duplication increases

**Mitigations:**
1. **Ontology-grounded extraction (§1.1 of optimizing report)** constrains
   entities to the allowed vocabulary.
2. **Entity deduplication (Post-1)** runs after ingest and collapses duplicates.
3. **Phase 1 entity catalog** already provides canonical names to the extraction
   prompt.

---

## 9. Metrics & Success Criteria

### Primary metric: CQ coverage improvement

```bash
# Baseline (current conservative extraction)
riverbank ingest --profile docs-policy-v1-preprocessed.yaml
riverbank validate-graph --profile docs-policy-v1-preprocessed.yaml
# → Coverage: X/Y (e.g., 3/5 = 60%)

# After permissive extraction
riverbank ingest --profile docs-policy-v1-permissive.yaml
riverbank validate-graph --profile docs-policy-v1-permissive.yaml
# → Coverage (trusted): X+1/Y (e.g., 4/5 = 80%)
riverbank validate-graph --profile docs-policy-v1-permissive.yaml --include-tentative
# → Coverage (all): X+2/Y (e.g., 5/5 = 100%)
```

**Target:** CQ coverage (trusted+tentative) ≥ 80% for the example corpus.

### Secondary metrics

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Triples per fragment (mean) | 8 | 20+ | Count from stats |
| CQ coverage (trusted only) | ~50% | ≥65% | validate-graph |
| CQ coverage (trusted+tentative) | ~50% | ≥80% | validate-graph --include-tentative |
| Precision (trusted graph) | ~85% | ≥85% | Manual review sample |
| Precision (tentative graph) | N/A | ≥50% | Manual review sample |
| Promotion rate (after 2nd ingest) | N/A | ≥20% of tentative | promote-tentative --dry-run |
| False promotion rate | N/A | <5% | Manual review of promoted |

### Acceptance test

```bash
# The example corpus should produce at least 100 total triples (trusted+tentative)
# vs. current ~40–60 triples
riverbank ingest --profile docs-policy-v1-permissive.yaml
riverbank query --include-tentative "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
# → ?n ≥ 100
```

---

## Appendix: Comparison with Existing Systems

| System | Philosophy | Threshold Strategy |
|--------|-----------|-------------------|
| **Google Knowledge Vault** | Extract billions of candidates, score by multi-source agreement | Knowledge-Weighted Trust (KWT): facts above 0.9 enter the KG |
| **Microsoft GraphRAG** | Extract entities + relationships liberally, organize by community | No confidence filtering — community summarization handles noise |
| **Wikidata** | All claims accepted with references; quality is a community process | No extraction filtering; constraints enforced by shape expressions |
| **DBpedia** | Template-based extraction from Wikipedia infoboxes | High precision by design (structured source) — no confidence |
| **NELL (Never-Ending Language Learner)** | Extract continuously, promote by confidence accumulation over time | Beliefs promoted from "candidate" → "trusted" via multi-source agreement |
| **Riverbank (current)** | Conservative single-pass extraction, batch SHACL routing | 0.7 threshold, batch-level graph/trusted vs graph/draft |
| **Riverbank (proposed)** | Permissive extraction, per-triple routing, noisy-OR accumulation | 0.35 floor, 0.75 promotion threshold, per-triple routing |

The proposed model is closest to **NELL** (Carnegie Mellon's "Never-Ending Language
Learner") which has run since 2010 and accumulated 120M+ beliefs using exactly
this accumulate-and-promote pattern.

---

*Last updated: 2025-05-07*
