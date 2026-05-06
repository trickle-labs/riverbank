# Learnings Report: Deeper Insights from the Strategic Documents

> **Source documents:** `plans/extract-more-triples.md`, `plans/optimizing-knowledge-graph.md`  
> **Date:** 2026-05-07  
> **Scope:** Insights beyond what's already captured in the roadmap — architectural
> principles, design patterns, research-backed techniques, and actionable strategies
> that inform how riverbank should evolve.

---

## 1. The Epistemic Shift: From "Trust the LLM" to "Trust the Evidence"

### What the documents reveal

The most fundamental insight across both documents is that riverbank's extraction
pipeline should transition from a **single-assessment model** (the LLM decides
what's true at extraction time) to an **evidence-based model** (truth emerges
from accumulation, corroboration, and contradiction over time).

### Why this matters for riverbank

The current pipeline asks the LLM to do two things simultaneously:
1. Extract facts from text
2. Judge whether those facts are reliable

Research (Zhu et al. 2023, Kadavath et al. 2022) shows LLMs are poor at task #2.
They over-score hallucinations (0.8+ confidence for fabricated facts) and
under-score true inferences (0.4–0.5 for implied but correct relationships).
Asking the LLM to self-assess is asking it to do something it's demonstrably bad at.

### How to take advantage

**Separate extraction from evaluation entirely.** The LLM's job is *extraction only*
— it should produce candidates aggressively. Quality assessment should happen
through independent mechanisms:

1. **Structural validation** (SHACL shapes, ontology conformance) — zero LLM cost
2. **Evidence accumulation** (noisy-OR across fragments) — zero LLM cost
3. **Contradiction detection** (functional predicate conflicts) — zero LLM cost
4. **Self-critique verification** (second LLM call with different framing) — only for borderline cases
5. **Human review** (Label Studio active learning) — highest signal, highest cost

This creates a **quality gradient** where the cheapest mechanisms handle the bulk
of quality control and expensive mechanisms (LLM verification, human review) are
reserved for genuinely ambiguous cases.

**Architectural implication:** The pipeline should be designed as:

```
Extract (aggressive) → Validate (structural) → Route (by confidence) →
Accumulate (noisy-OR) → Verify (selective) → Promote/Demote → Human Review (rare)
```

Each stage is independently testable, independently deployable, and independently
measurable. This is the architecture that v0.12.0–v0.13.0 should implement.

---

## 2. The NELL Precedent: Riverbank as a Never-Ending Learner

### What the documents reveal

The appendix in `extract-more-triples.md` compares the proposed architecture to
existing systems. The closest match is **NELL (Never-Ending Language Learner)**
from Carnegie Mellon — a system that continuously extracts facts from the web,
promotes them from "candidate" to "trusted" via multi-source agreement, and
improves its own extraction quality over time.

### Why this matters for riverbank

NELL's architecture demonstrates that the proposed approach (permissive
extraction → accumulation → promotion) is not theoretical — it ran for over a
decade and accumulated millions of beliefs. Key NELL lessons:

1. **Coupled learning:** NELL improved its extractors by learning from its own
   high-confidence extractions. Riverbank's "auto few-shot expansion" (v0.13.0)
   is exactly this pattern.
2. **Multi-source agreement beats single-source confidence:** A fact extracted
   by three independent methods/documents at 0.5 confidence each is more reliable
   than a single extraction at 0.9.
3. **Semantic drift is the long-term risk:** NELL gradually accumulated errors
   because bad extractions could pollute the training data. The mitigation is
   quality regression tracking (v0.13.0) and human-in-the-loop review (v0.6.0).

### How to take advantage

Riverbank is already better positioned than NELL because:
- **Fixed corpus** — unlike NELL's open web, riverbank corpora are bounded. Drift
  is controllable.
- **Ontology constraints** — NELL had no closed-world vocabulary constraint.
  Riverbank's ontology-grounded extraction (v0.12.0) prevents vocabulary explosion.
- **CQ-based evaluation** — NELL had no competency questions. Riverbank can
  *measure* whether its extractions are useful, not just whether they're correct.

**Actionable:** Design the auto few-shot expansion (v0.13.0) with NELL's drift
failure in mind:
- Never auto-add examples from a run where CQ coverage decreased
- Require diversity constraints (no two examples with same predicate+type)
- Implement a "quarantine" mechanism: new examples are probationary for one ingest
  cycle before becoming permanent
- Quality regression tracking acts as the safety net — if a bad example degrades
  the benchmark, it surfaces immediately

---

## 3. Schema Induction: The Cold-Start Problem

### What the documents reveal

Strategy 5.3 (Schema Induction) addresses a problem riverbank doesn't currently
solve: **what happens when a user brings a new corpus with no pre-existing
ontology?** Currently, they must either write an ontology by hand or use the
generic `pgc:` vocabulary, which produces an unstructured grab-bag of triples.

### Why this matters for riverbank

Every new corpus adoption starts with the same friction:
1. User has documents
2. User doesn't know what predicates/classes to use
3. User creates a minimal profile with generic vocabulary
4. Extraction produces low-quality, inconsistent triples
5. User loses confidence in the tool

This is the **adoption bottleneck**. The onboarding experience determines whether
riverbank gets a second chance.

### How to take advantage

**Two-pass bootstrap workflow:**

```bash
# Pass 1: Extract everything with generic vocabulary (permissive, no ontology constraints)
riverbank ingest --profile generic-v1.yaml

# Pass 2: Induce an ontology from the extracted graph
riverbank induce-schema --graph http://example/graph/trusted \
  --output ontology/my-corpus.ttl \
  --review  # opens interactive review before committing

# Pass 3: Re-extract with the induced ontology as constraints
riverbank ingest --profile my-corpus-v1.yaml  # now uses ontology/my-corpus.ttl
```

The `induce-schema` command would:
1. Collect all unique predicates and entity types from the graph
2. Compute frequency statistics (which predicates connect which type pairs)
3. Ask the LLM to propose a minimal OWL ontology (class hierarchy, domain/range,
   cardinality constraints)
4. Present the proposal for human review (CLI interactive or file-based)
5. Write the approved ontology to `ontology/`

**Why this is high-leverage:**
- Research shows a second extraction pass with schema constraints produces 2x
  better precision than the first unconstrained pass
- The user gets a domain-specific ontology without needing ontology expertise
- The first pass (even if low quality) provides the data the LLM needs to
  *induce* a good schema — a bootstrapping loop

**Placement:** This could slot into v0.13.0 or v0.14.0 as a "new corpus
onboarding" feature. Low complexity (one LLM call to propose the schema),
high adoption impact.

---

## 4. The Coreference Problem: Fragment Boundaries Destroy Context

### What the documents reveal

Strategy 1.4 (Coreference Resolution) identifies a problem that none of the
roadmap items currently address: after fragmentation, **pronouns and anaphoric
references cannot be resolved** because the referent is in a different fragment.

The result is triples like:
- `ex:_it rdf:type pgc:Component` (what is "it"?)
- `ex:_the_system schema:hasPart ex:Module` (which system?)

### Why this matters for riverbank

This is particularly devastating for:
- **Procedural documents** (runbooks, SOPs) — heavy use of "it", "the step",
  "this process"
- **Multi-paragraph descriptions** — the subject introduced in paragraph 1 is
  referred to by pronoun in paragraph 3, which is in a different fragment
- **Documents with long-range references** — "as described above", "the previously
  mentioned component"

The overlapping fragment windows (v0.12.0) partially mitigate this by providing
context from the previous fragment, but they don't solve long-range anaphora.

### How to take advantage

**Pre-fragmentation coreference resolution:**

```python
# Before fragmenting, resolve pronouns in the full document
resolved_text = resolve_coreferences(original_text)
# Then fragment the resolved text as normal
fragments = fragmenter.fragment(resolved_text)
```

Two implementation paths:

1. **LLM-based (high quality, higher cost):** One LLM call per document:
   "Replace all pronouns and anaphoric references with the entity they refer to.
   Keep the text otherwise unchanged." Cost: ~500 tokens per document.

2. **Classical NLP (lower quality, zero LLM cost):** spaCy's `coreferee` or
   HuggingFace `neuralcoref`. Faster, deterministic, but less accurate for
   complex references.

**Risk mitigation:** Only apply high-confidence resolutions. A wrong coreference
resolution creates confidently incorrect triples that are harder to detect than
missing triples. The safe default is to leave ambiguous pronouns unresolved
rather than risk propagation errors.

**Placement:** This fits naturally into Phase 1 preprocessing (v0.11.0 already has
`DocumentPreprocessor`). Adding a `coreference_resolution: true` option to the
preprocessing config would run it before fragmentation.

**Expected impact:** 20–40% reduction in orphan/anonymous entities. Particularly
impactful for the `procedural-v1` profile (runbooks, SOPs).

---

## 5. Linearized Triples: The Output Format Matters More Than We Think

### What the documents reveal

Strategy 1.6 cites Dai et al. (2025) and Meyer et al. (2023) showing that:
- LLMs produce **more valid RDF** when outputting Turtle syntax directly
  (fewer structural errors than JSON)
- LLMs **comprehend** linearized triples better than fluent natural language
  descriptions of the same facts
- Local models (llama3.2, mistral) particularly benefit because they often
  return schema *definitions* instead of *instances* when asked for JSON

### Why this matters for riverbank

Riverbank currently uses instructor with Pydantic response models (JSON output).
This works well for cloud models (GPT-4, Claude) but causes frequent failures
with local models. The failure mode is:

1. LLM is asked to produce JSON conforming to the `ExtractedTriple` schema
2. Instead of producing instances (`{"subject": "Pipeline", ...}`), it produces
   the *schema itself* or a malformed hybrid
3. instructor retries, increasing latency and cost
4. Eventually gives up or returns partial results

### How to take advantage

**Dual output mode:**

```yaml
extraction:
  output_format: json      # default, uses instructor + Pydantic
  # output_format: turtle  # linearized triple format, parsed with rdflib
```

For `turtle` mode:
```
Extract facts as one triple per line in this format:
<subject> <predicate> <object> .

Example:
ex:Pipeline rdf:type pgc:Component .
ex:Pipeline schema:hasPart ex:Transformer .
ex:Transformer rdfs:label "JSON Transform" .
```

Parse with a simple N-Triples parser (regex or rdflib). This eliminates the
class of failures where the model produces valid output that doesn't conform to
the JSON schema.

**The tradeoff:** linearized triples lose the structured confidence score per
triple that the JSON format provides. Possible solutions:
- Append confidence as a comment: `ex:A ex:b ex:C . # 0.85`
- Use a two-part response: triples first, then a confidence table
- Use the LLM's token-level log probabilities as a proxy for confidence
  (available via Ollama API)

**Placement:** This is low-complexity and high-impact for local model users.
Could ship in v0.12.0 alongside constrained decoding as part of a "local model
reliability" feature set. Or v0.14.0 as currently planned.

---

## 6. The Safety Cap: Runaway Extraction Is a Real Risk

### What the documents reveal

Section 8 of `extract-more-triples.md` identifies a specific risk: with
permissive extraction, the LLM might produce an unbounded number of triples per
fragment, especially for dense technical documents. The mitigation is a safety
cap:

```yaml
extraction_strategy:
  max_triples_per_fragment: 50
```

### Why this matters for riverbank

Without a cap, a single adversarial or unusually dense fragment could:
- Produce 200+ triples, blowing up response token usage
- Overwhelm the downstream pipeline with noise
- Cause instructor to timeout or OOM on the response parsing
- Create a single fragment that dominates the graph (skewing all statistics)

### How to take advantage

**Implement the cap as a hard limit in the extraction loop:**

```python
triples = result.triples
if len(triples) > profile.extraction_strategy.max_triples_per_fragment:
    logger.warning(f"Fragment produced {len(triples)} triples, capping at {cap}")
    triples = sorted(triples, key=lambda t: t.confidence, reverse=True)[:cap]
    stats["triples_capped"] += 1
```

Keep the top-N by confidence — this naturally preserves the highest-value
extractions and discards the noise tail.

**Additional safeguard:** Track the `triples_per_fragment` distribution in stats.
If the mean suddenly jumps (e.g., > 3x the running average), emit a warning.
This catches prompt regressions or model changes that produce verbose output.

**Placement:** This should ship with v0.12.0's permissive extraction. It's a
one-liner safety mechanism that prevents catastrophic failure modes.

---

## 7. Source Diversity Scoring: Not All Corroboration Is Equal

### What the documents reveal

The risk mitigation section in `extract-more-triples.md` (§8) identifies
**correlated hallucination** as the most dangerous failure mode of noisy-OR
accumulation:

> "Three documents all say 'Pipeline is maintained by Team X' (copied from a
> template), but Team X was reassigned. Noisy-OR promotes this to 0.88 confidence."

The mitigation is **source diversity scoring**: only count corroboration from
*distinct* source documents, not multiple fragments of the same document.

### Why this matters for riverbank

In real-world corpora:
- Documents are often copied, templated, or derived from each other
- The same incorrect claim can appear verbatim in 5 documents because they all
  copied from one source
- Naive noisy-OR treats each occurrence as independent evidence — it's not
- The mathematical consequence: `1 - (1-0.5)^5 = 0.97` — a single copied
  template creates near-certainty from no actual evidence

### How to take advantage

**Implement source-aware accumulation:**

```python
def consolidate_confidence(existing_triples: list[TripleRecord], new_triple: TripleRecord) -> float:
    """Only count corroboration from distinct source documents."""
    # Deduplicate by source document IRI (not fragment IRI)
    unique_sources = set()
    confidence_per_source = {}
    
    for t in [*existing_triples, new_triple]:
        source_doc = t.provenance.source_document_iri
        if source_doc not in unique_sources:
            unique_sources.add(source_doc)
            confidence_per_source[source_doc] = max(
                confidence_per_source.get(source_doc, 0), t.confidence
            )
    
    # Noisy-OR only over distinct sources
    result = 1.0
    for c in confidence_per_source.values():
        result *= (1.0 - c)
    return 1.0 - result
```

**Additional sophistication (future):**
- **Textual similarity scoring:** If two evidence spans are > 0.95 cosine
  similarity, they're likely copied — count as one vote
- **Temporal decay:** Older sources get reduced weight (facts may be outdated)
- **Source authority weighting:** Some documents are more authoritative than
  others (e.g., official documentation vs. meeting notes)

**Placement:** Source diversity scoring is part of v0.12.0's noisy-OR
implementation. The additional sophistication (textual similarity, temporal
decay, authority weighting) can be deferred to v0.13.0 or later.

---

## 8. The Graph Store as a First-Class Quality Signal

### What the documents reveal

Several strategies (knowledge-prefix adapter §6.3, incremental entity linking
§2.2, contradiction detection §4.4) share a pattern: **reading from the existing
graph at extraction time to improve future extractions.**

### Why this matters for riverbank

Currently, extraction is a one-way flow: text → LLM → graph. The graph is a
write-only sink during extraction. But the graph *already contains information*
that could make extraction better:

1. **Entity consistency:** The graph already has `ex:DataPipeline` — why let
   the LLM mint `ex:data-pipeline` for the same entity?
2. **Predicate patterns:** The graph shows that `schema:hasPart` is used 67 times
   while `schema:contains` appears 0 times — this preference should inform
   extraction.
3. **Contradiction avoidance:** If `(Pipeline, version, "2.0")` already exists
   in the trusted graph, extracting `(Pipeline, version, "1.0")` from an older
   document should be flagged immediately, not after ingest.

### How to take advantage

**Three levels of graph-informed extraction (progressive implementation):**

**Level 1: Entity injection (v0.13.0 — incremental entity linking)**
```
KNOWN ENTITIES (prefer these IRIs when the text refers to these concepts):
- ex:DataPipeline (type: pgc:Component, aliases: "data pipeline", "pipeline")
- ex:TransformStep (type: pgc:Process, aliases: "transform", "transformation")
```

**Level 2: Graph context injection (v0.13.0 — knowledge-prefix adapter)**
```
KNOWN GRAPH CONTEXT (already established facts near this fragment's entities):
ex:DataPipeline → schema:hasPart → ex:TransformStep
ex:TransformStep → rdf:type → pgc:Process
ex:DataPipeline → schema:dependsOn → ex:Database
```

**Level 3: Constraint injection (v0.12.0 — already in the ontology-grounded design)**
```
ALLOWED PREDICATES: rdf:type, schema:hasPart, schema:dependsOn, ...
FUNCTIONAL PREDICATES (at most one value): schema:version, schema:dateCreated
```

These three levels form a **progressively richer context window** for extraction.
Level 3 ships first (v0.12.0), Level 1 and 2 ship in v0.13.0. Together, they
transform extraction from a stateless function call into a **graph-aware
reasoning step** where the LLM has full context of what's already known.

**The key insight:** The marginal cost of injecting graph context is ~150 tokens
per fragment. The quality improvement (fewer contradictions, better entity
consistency, more relevant predicates) is substantial. This is high ROI because
it's just prompt injection — no new models, no new infrastructure.

---

## 9. Multi-Pass Extraction: When Quality > Cost

### What the documents reveal

Strategy 1.5 proposes decomposing extraction into specialized passes:
1. **Entity Pass:** "What entities are mentioned?" → types and labels
2. **Relationship Pass:** "Given these entities, what relationships exist?"
3. **Attribute Pass:** "For each entity, what are its properties?"

Research (Zhu et al. 2023, AutoKG) shows 15–25% F1 improvement from
decomposition vs. joint extraction.

### Why this matters for riverbank

The current single-pass approach asks the LLM to do three things at once:
identify entities, determine their types, AND extract relationships between
them. This creates:
- **Entity inconsistency:** The same entity gets different names in different
  triples within the same fragment
- **Missed relationships:** The LLM "uses up" its attention budget on entity
  identification and produces fewer relationship triples
- **Type confusion:** Complex documents where an entity plays multiple roles
  get confused type assignments

### How to take advantage

**Profile-selectable extraction strategy:**

```yaml
extraction_strategy:
  mode: multi_pass    # "single" (default), "permissive", "multi_pass"
  passes:
    - entity          # first: identify all entities + types
    - relationship    # second: relationships between identified entities
    - attribute       # optional third: properties per entity
```

**Implementation approach:**
- Each pass uses a specialized Pydantic response model
- The entity pass output is injected into the relationship pass prompt
- Results are merged with deduplication before writing
- Total token cost: 2–3x per fragment (justified for high-value corpora)

**When to use it:**
- **Single pass (default):** Low-value or large corpora where cost matters
- **Permissive (v0.12.0):** Medium-value corpora where recall matters
- **Multi-pass:** High-value corpora where both precision and recall are critical

**The synergy with permissive extraction:** Multi-pass + permissive creates the
highest-quality extraction possible. The entity pass establishes canonical names
(reducing duplication), and the permissive relationship pass extracts broadly
but consistently (using the entity pass output as anchors).

**Placement:** Long-term (v1.x in the current roadmap). But consider offering it
as an opt-in "premium" extraction mode earlier — it's not complex to implement
(three sequential LLM calls with different prompts), just expensive to run.

---

## 10. SHACL on Tentative: Structural Validation Before Accumulation

### What the documents reveal

Risk mitigation §8 in `extract-more-triples.md` mentions:

> "SHACL validation on tentative — structurally invalid tentative triples
> (wrong domain/range) are discarded immediately."

This is separate from the post-ingest SHACL validation in v0.14.0. This is
**pre-write structural filtering** that catches obviously wrong triples before
they ever enter the tentative graph.

### Why this matters for riverbank

Without pre-write SHACL filtering, the tentative graph accumulates structurally
invalid triples that:
- Can never be promoted (they violate the schema)
- Waste storage and query time
- Confuse users who explore with `--include-tentative`
- Pollute noisy-OR calculations (a wrong triple + another wrong triple = higher
  confidence wrong triple)

### How to take advantage

**Lightweight structural check at write time:**

```python
def should_write_triple(triple, allowed_predicates, predicate_constraints):
    """Fast structural validation before writing to tentative graph."""
    # 1. Predicate must be in allowed set
    if triple.predicate not in allowed_predicates:
        return False, "predicate_not_allowed"
    
    # 2. Domain/range type check (if declared in constraints)
    constraint = predicate_constraints.get(triple.predicate)
    if constraint:
        if constraint.domain and triple.subject_type not in constraint.domain:
            return False, "domain_violation"
        if constraint.range and triple.object_type not in constraint.range:
            return False, "range_violation"
    
    # 3. Functional predicate check (max_cardinality: 1)
    # Defer to contradiction detection if existing value present
    
    return True, None
```

This is NOT full SHACL validation (which requires the whole graph). It's a
**fast structural filter** using profile-defined constraints. Zero graph queries,
zero LLM calls, microsecond latency.

**Placement:** Ships with v0.12.0 as part of the per-triple routing logic. The
predicate allowlist is already defined for ontology-grounded extraction — this
just reuses it as a write-time filter.

---

## 11. The Measurement Gap: Quality You Can't Measure, You Can't Improve

### What the documents reveal

Section 7 of `optimizing-knowledge-graph.md` defines 10 quality metrics:

| Metric | Target |
|--------|--------|
| Precision | > 0.85 |
| Recall | > 0.70 |
| F1 Score | > 0.75 |
| CQ Coverage | > 0.80 |
| Entity Duplication Rate | < 1.3x |
| Predicate Vocabulary Size | < 1.5x |
| Confidence Distribution | > 0.75 (mean) |
| SHACL Conformance | > 0.90 |
| Cross-Doc Entity Consistency | > 0.85 |
| Triple Consolidation Ratio | > 0.20 |

### Why this matters for riverbank

Currently, riverbank tracks **operational metrics** (triples written, LLM calls,
token counts, cost) but not **quality metrics** (precision, recall, F1, CQ
coverage). Without quality metrics:

- We can't know if v0.12.0 actually improved extraction
- We can't compare models (is llama3.2 better than mistral for this corpus?)
- We can't detect quality regressions from code changes
- We can't justify the cost of more expensive models or multi-pass extraction
- We can't set quality SLOs for production deployments

### How to take advantage

**`riverbank benchmark` command (v0.13.0) should output all 10 metrics:**

```json
{
  "precision": 0.87,
  "recall": 0.72,
  "f1": 0.79,
  "cq_coverage": 0.83,
  "entity_dup_rate": 1.2,
  "predicate_vocab_ratio": 1.3,
  "mean_confidence": 0.78,
  "shacl_conformance": 0.91,
  "cross_doc_entity_consistency": 0.86,
  "triple_consolidation_ratio": 0.24,
  "triples_total": 142,
  "triples_trusted": 89,
  "triples_tentative": 53,
  "fragments_processed": 12,
  "cost_usd": 0.03
}
```

**Store historical metrics for trend analysis.** Each `riverbank ingest` run
should append quality metrics to a timeseries (stored in `_riverbank.metrics`
table or as triples in the graph). This enables:

- Before/after comparison: "Did the prompt change improve recall?"
- Model comparison: "Which model gives better F1 for this corpus?"
- Regression detection: "Quality dropped after the last code change"
- SLO monitoring: "Is our production graph maintaining > 0.85 precision?"

**The golden corpus is essential.** Without ground-truth triples, precision and
recall are unknowable. The existing `tests/golden/` directory provides this for
`docs-policy-v1`, but every production profile needs its own golden set.

**Actionable for v0.12.0:** Even before `riverbank benchmark` ships, start
tracking metrics that don't require ground truth:
- CQ coverage (already exists via `validate-graph`)
- Entity duplication rate (count unique subjects / total subject mentions)
- Predicate vocabulary ratio (unique predicates / allowed predicates)
- Confidence distribution (mean, median, p10, p90)
- Triples per fragment distribution

These are computable from the existing graph with zero ground truth.

---

## 12. The Comparison to GraphRAG: What We Can Learn

### What the documents reveal

Strategy 2.1 describes Microsoft's GraphRAG approach and compares it to
riverbank's Phase 2 corpus clustering. The key difference:

- **Riverbank Phase 2:** Clusters *documents* by summary embeddings before
  extraction
- **GraphRAG:** Clusters *extracted entities* after initial extraction, then uses
  community summaries for global sensemaking

### Why this matters for riverbank

Riverbank currently does Phase 2 (document clustering) **before** extraction.
GraphRAG does community detection **after** extraction. Both are valuable, but
they serve different purposes:

- **Before extraction (Phase 2):** Helps the LLM understand corpus-level context.
  "This document is about Pipeline Architecture, which is in the same cluster as
  these other documents about system design."
- **After extraction (GraphRAG-style):** Helps users understand the graph.
  "The extracted knowledge naturally organizes into these communities: System
  Architecture (45 entities), Data Flow (32 entities), Operations (18 entities)."

### How to take advantage

**Post-extraction community detection as a query/exploration tool:**

```bash
riverbank communities --graph http://example/graph/trusted \
  --algorithm leiden \
  --output communities.json

# Output:
# { "communities": [
#     { "id": 1, "label": "System Architecture", "entities": [...], "summary": "..." },
#     { "id": 2, "label": "Data Flow", "entities": [...], "summary": "..." }
#   ]}
```

This is NOT a quality improvement strategy (unlike everything else in this
report). It's a **user experience** feature that helps humans understand what
the compiled graph contains. But it has a subtle quality benefit:

- Communities that contain only 1–2 entities with no connections to other
  communities are likely **extraction artifacts** (orphan entities, duplicates)
- Community detection surfaces these naturally: "Why is there a community with
  just `ex:_it` and `ex:_the_system`?" → these are unresolved coreferences
- This provides **diagnostic feedback** to improve extraction quality

**Placement:** This is a long-term feature (v1.x in the current roadmap) but the
diagnostic value suggests it could be useful earlier as a quality analysis tool.

---

## 13. The Inverse Relationship Problem

### What the documents reveal

Section 2.1 of `extract-more-triples.md` identifies that the conservative prompt
causes the LLM to extract only one direction of a symmetric relationship:

> "Text says 'B is part of A' → should also produce `A hasPart B`, but only one
> direction is extracted."

### Why this matters for riverbank

Missing inverse relationships make SPARQL queries fail silently. A user queries:

```sparql
SELECT ?part WHERE { ex:System schema:hasPart ?part }
```

This returns nothing — but the graph has `ex:Module schema:isPartOf ex:System`.
The triple exists but in the opposite direction. The user concludes the graph is
incomplete when it's actually a traversal problem.

### How to take advantage

**Three approaches (use in combination):**

1. **OWL 2 RL forward-chaining (v0.14.0):** Declare `schema:hasPart
   owl:inverseOf schema:isPartOf` in the ontology. The reasoner automatically
   derives the inverse triple. Zero extraction cost, purely deductive.

2. **Prompt instruction (v0.12.0):** Add to the permissive extraction prompt:
   "For part-whole relationships, always extract BOTH directions: `A hasPart B`
   AND `B isPartOf A`." Simple but increases token output.

3. **Post-extraction rule (v0.14.0, SPARQL CONSTRUCT):**
   ```sparql
   CONSTRUCT { ?parent schema:hasPart ?child }
   WHERE { ?child schema:isPartOf ?parent }
   ```

**Recommendation:** Option 1 (OWL 2 RL) is the cleanest because it's
declarative, automatic, and handles ALL inverse pairs defined in the ontology
(not just hasPart/isPartOf). But it requires the ontology to declare inverse
relationships, which it should anyway.

**For v0.12.0:** Include a note in the permissive prompt that says "extract both
directions for asymmetric relationships." This provides immediate benefit before
OWL reasoning ships in v0.14.0.

---

## 14. Cost-Quality Tradeoff: The Profile as an Economics Decision

### What the documents reveal

The summary matrix in `optimizing-knowledge-graph.md` (§8) reveals a clear
pattern: strategies cluster into three cost tiers:

| Tier | Token Cost | Examples |
|------|-----------|----------|
| **Zero-cost** | 0 extra tokens | Ontology grounding, CQ guidance, constrained decoding, literal normalization, SHACL validation |
| **Low-cost** | +50–200 tokens/fragment | Overlapping windows, knowledge prefix, entity injection |
| **High-cost** | 2–3x per fragment | Multi-pass, coreference resolution, self-critique per triple |

### Why this matters for riverbank

Different corpora have different value densities:
- **Compliance documents** (high value): Worth 3x extraction cost for maximum precision
- **Meeting notes** (medium value): Standard permissive extraction is sufficient
- **Log data** (low value): Conservative single-pass with no extras

### How to take advantage

**Make the profile YAML explicitly an economics decision:**

```yaml
# High-value corpus: maximize quality regardless of cost
extraction_strategy:
  mode: multi_pass
  overlapping_windows: true
  knowledge_prefix: true
  coreference_resolution: true
  verification: { enabled: true, confidence_threshold: 0.6 }
  # Expected cost: ~$0.10/document with GPT-4o-mini, $0/document with Ollama

# Standard corpus: good quality at reasonable cost
extraction_strategy:
  mode: permissive
  overlapping_windows: true
  knowledge_prefix: false
  coreference_resolution: false
  verification: { enabled: true, confidence_threshold: 0.75 }
  # Expected cost: ~$0.03/document with GPT-4o-mini, $0/document with Ollama

# Budget corpus: maximum throughput
extraction_strategy:
  mode: conservative
  overlapping_windows: false
  knowledge_prefix: false
  coreference_resolution: false
  verification: { enabled: false }
  # Expected cost: ~$0.01/document with GPT-4o-mini, $0/document with Ollama
```

**The Ollama advantage:** For local model users, the cost tier is always zero.
The tradeoff becomes purely latency vs. quality. This is why constrained decoding
(v0.14.0) and coreference resolution are particularly valuable for Ollama users
— they get quality improvements at zero marginal cost.

---

## 15. The Feedback Loop That Ties Everything Together

### What the documents reveal

Reading both documents holistically, there's an emergent architecture that
neither document states explicitly but that becomes visible when you trace the
data flows across all proposed strategies:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE QUALITY IMPROVEMENT LOOP                       │
│                                                                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │ Ontology │    │    CQs   │    │  Golden  │    │ Entity   │      │
│  │ (v0.12)  │◄───┤  (v0.12) │◄───┤ Examples │◄───┤ Registry │      │
│  └────┬─────┘    └────┬─────┘    │  (v0.13) │    │  (v0.13) │      │
│       │               │          └────┬─────┘    └────┬─────┘      │
│       ▼               ▼               ▼               ▼             │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                   EXTRACTION PROMPT                        │       │
│  │  Ontology constraints + CQ objectives + Few-shot examples │       │
│  │  + Known entities + Graph context + Permissive guidance   │       │
│  └─────────────────────────┬────────────────────────────────┘       │
│                            │                                         │
│                            ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                   LLM EXTRACTION                           │       │
│  └─────────────────────────┬────────────────────────────────┘       │
│                            │                                         │
│                            ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │           STRUCTURAL VALIDATION + ROUTING                  │       │
│  │  Ontology filter → Per-triple routing → Literal norm       │       │
│  └─────────────────────────┬────────────────────────────────┘       │
│                            │                                         │
│                            ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                 GRAPH (trusted + tentative)                 │       │
│  └─────────────────────────┬────────────────────────────────┘       │
│                            │                                         │
│       ┌────────────────────┼────────────────────┐                   │
│       ▼                    ▼                    ▼                    │
│  ┌─────────┐      ┌──────────────┐      ┌──────────┐              │
│  │ Dedup   │      │ Accumulation │      │Benchmark │              │
│  │ (v0.11) │      │   (v0.12)    │      │ (v0.13)  │              │
│  └────┬────┘      └──────┬───────┘      └────┬─────┘              │
│       │                  │                    │                      │
│       ▼                  ▼                    ▼                      │
│  Entity Registry    Promotion/Demotion   Quality Metrics            │
│       │                  │                    │                      │
│       └──────────────────┴────────────────────┘                     │
│                          │                                           │
│                          ▼                                           │
│              ┌────────────────────────┐                             │
│              │  AUTO FEW-SHOT (v0.13) │                             │
│              │  Only from high-quality│                             │
│              │  CQ-satisfying triples │                             │
│              └───────────┬────────────┘                             │
│                          │                                           │
│                          └──────── feeds back to ────────►          │
│                                    Golden Examples                    │
└─────────────────────────────────────────────────────────────────────┘
```

### The key insight

**Every component in v0.12.0–v0.13.0 is both a consumer and a producer of quality
signals.** Nothing exists in isolation:

- The ontology constrains extraction AND validates output AND detects contradictions
- CQs guide extraction AND evaluate output AND select few-shot examples
- The entity registry informs extraction AND is built by extraction
- The benchmark measures quality AND gates few-shot expansion
- Deduplication cleans the graph AND populates the entity registry
- Accumulation improves confidence AND enables promotion AND triggers contradiction detection

**This is not a linear pipeline — it's a feedback loop.** Each ingest run makes
the next ingest run better, without any human intervention. The system
improves itself by extracting, measuring, and learning from its own output.

**Design principle:** Every new feature should both consume AND produce a quality
signal. If it only consumes (pure filter), it's a dead end. If it only produces
(pure generator), it's disconnected. The highest-value features are those that
participate in the feedback loop.

---

## Summary: Top 5 Non-Obvious Actions

1. **Ship Phase A of v0.12.0 standalone** — permissive prompt + per-triple
   routing delivers the full small-corpus recall improvement without needing
   accumulation. Don't wait for noisy-OR to ship the prompt change.

2. **Add `riverbank induce-schema` for cold-start onboarding** — this removes
   the biggest adoption bottleneck (users must write an ontology before they
   can get quality results). Two-pass bootstrap: extract generically → induce
   schema → re-extract with constraints.

3. **Pre-write structural filtering in v0.12.0** — don't let structurally
   invalid triples into the tentative graph. The ontology allowlist is already
   there; reuse it as a write-time filter. This prevents noise accumulation
   and keeps noisy-OR calculations clean.

4. **Track quality metrics from v0.12.0 onward** — even without ground truth,
   CQ coverage + entity duplication rate + predicate vocab ratio + confidence
   distribution are all computable and provide a quality signal. Store them per
   run. This creates the measurement infrastructure that `riverbank benchmark`
   (v0.13.0) will build on.

5. **Design auto few-shot expansion with drift protection** — NELL's failure
   mode (bad extractions polluting training data) is exactly the risk here.
   Never auto-add examples from runs where quality metrics decreased.
   Probationary period before examples become permanent.
