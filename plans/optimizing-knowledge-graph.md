# Optimizing Knowledge Graph Quality

> Comprehensive strategies for improving the precision, recall, consistency, and
> completeness of knowledge graphs produced by riverbank's LLM-based extraction
> pipeline. Each strategy includes a detailed description, expected impact,
> implementation sketch, and references to relevant research.

---

## Table of Contents

1. [Extraction-Time Strategies](#1-extraction-time-strategies)
2. [Corpus-Level / Cross-Document Strategies](#2-corpus-level--cross-document-strategies)
3. [Post-Extraction Graph Refinement](#3-post-extraction-graph-refinement)
4. [Reasoning & Inference Strategies](#4-reasoning--inference-strategies)
5. [Feedback Loop & Continuous Learning](#5-feedback-loop--continuous-learning)
6. [Structural & Format Optimizations](#6-structural--format-optimizations)
7. [Evaluation & Measurement](#7-evaluation--measurement)
8. [Summary Matrix](#8-summary-matrix)
9. [Recommended Implementation Sequence](#9-recommended-implementation-sequence)
10. [References](#10-references)

---

## 1. Extraction-Time Strategies

### 1.1 Ontology-Grounded Constrained Extraction

**Problem:** LLMs hallucinate predicates and classes not defined in the target
ontology. A free-text extraction prompt yields triples like `ex:pipe ex:uses ex:dataset`
when the ontology only defines `schema:hasPart`.

**Approach:**
- Load the relevant ontology fragment (from `ontology/pgc.ttl` or profile-defined
  namespace prefixes) and inject it as a closed-world constraint in the extraction
  prompt:

  ```
  ALLOWED PREDICATES (use ONLY these):
    rdf:type, rdfs:label, rdfs:comment, schema:isPartOf, schema:hasPart,
    schema:name, schema:description, pgc:hasConfidence, pgc:hasEvidence

  ALLOWED CLASSES:
    pgc:Concept, pgc:Process, pgc:Component, pgc:Document, pgc:EvidenceSpan

  If a relationship does not fit any allowed predicate, SKIP it.
  ```

- Validate extracted triples against the allowed set; reject non-conforming ones
  before writing to the store.

**Expected Impact:**
- Eliminates ~30–50% of hallucinated predicates (based on findings in
  Meyer et al. 2023 — LLMs struggle with strict output formatting but improve
  dramatically when given closed vocabularies).
- Zero cost increase — purely prompt engineering.

**Implementation in riverbank:**
- Add `allowed_predicates` and `allowed_classes` to the profile YAML schema.
- In `build_extraction_prompt()`, append the ontology constraint block.
- In the triple-writing step, filter triples whose predicate is not in the
  allowed set (log as `triple_rejected_ontology`).

**Complexity:** Low  
**ROI:** ⭐⭐⭐⭐⭐

---

### 1.2 Competency-Question-Guided Extraction

**Problem:** Open-ended "extract all triples" prompts produce a large volume of
low-value triples. The signal-to-noise ratio is poor.

**Approach:**
- Transform the profile's `competency_questions` (already defined for
  `validate-graph`) into extraction guidance:

  ```
  EXTRACTION OBJECTIVES — extract triples that would help answer:
  1. "What components does the system have?" → look for schema:hasPart relationships
  2. "What depends on what?" → look for schema:dependsOn relationships
  3. "What is the confidence of each fact?" → attach pgc:hasConfidence
  ```

- This turns extraction from exhaustive to goal-directed. The LLM focuses on
  relationships that matter for downstream queries.

**Expected Impact:**
- Higher precision (fewer irrelevant triples).
- Better `validate-graph` coverage scores (extraction is aligned with evaluation).
- Modest token savings (shorter responses when the LLM doesn't attempt to extract
  everything).

**Implementation in riverbank:**
- During prompt building, extract CQ patterns from the profile and append as
  "EXTRACTION OBJECTIVES" section.
- Weight CQ-aligned triples with higher confidence (e.g., +0.1 boost).

**Complexity:** Low  
**ROI:** ⭐⭐⭐⭐

---

### 1.3 Relationship Cardinality & Functional Property Hints

**Problem:** The LLM extracts multiple objects for predicates that should be
functional (exactly one value). For example, `ex:doc schema:version "1.0"` and
`ex:doc schema:version "2.0"` extracted from the same fragment.

**Approach:**
- Annotate predicates in the ontology/profile with cardinality constraints:
  ```yaml
  predicate_constraints:
    schema:version: { max_cardinality: 1 }
    schema:dateCreated: { max_cardinality: 1 }
    schema:hasPart: { max_cardinality: null }  # unbounded
  ```
- Include in the prompt: "schema:version is a FUNCTIONAL property — each subject
  has at most one version value. Pick the most specific/recent one."
- Post-extraction: if multiple values exist for a functional property, keep only
  the one with highest confidence.

**Expected Impact:**
- Reduces contradictory triples by ~10–15%.
- Improves downstream SPARQL query correctness.

**Complexity:** Low  
**ROI:** ⭐⭐⭐

---

### 1.4 Coreference Resolution Pre-Pass

**Problem:** After fragmentation, pronouns and anaphoric references ("it", "the
system", "this component") cannot be resolved because the referent is in a
different fragment. This produces triples like `ex:_it rdf:type pgc:Component`.

**Approach:**
- Before fragmentation, run a lightweight coreference resolution step that
  replaces pronouns with their resolved entity names:
  - Use a dedicated LLM call: "Replace all pronouns and anaphoric references in
    the following text with the entity they refer to. Keep the text otherwise
    unchanged."
  - Alternatively, use a classical NLP coreference model (e.g., spaCy's
    `coreferee` or HuggingFace `neuralcoref`) for cost efficiency.
- The resolved text is then fragmented and extracted normally.

**Expected Impact:**
- Reduces orphan/anonymous entities by ~20–40%.
- Improves entity linking across fragments.
- Particularly impactful for narrative documents (procedures, runbooks).

**Risks:**
- Increases token cost (one extra LLM call per document).
- Resolution errors can propagate (a wrong resolution creates confident but
  incorrect triples). Mitigation: only apply to high-confidence resolutions.

**Complexity:** Medium–High  
**ROI:** ⭐⭐⭐

---

### 1.5 Multi-Pass Extraction with Specialized Prompts

**Problem:** A single generic extraction prompt cannot optimize for both entity
identification and relationship extraction simultaneously. Research (Zhu et al.
2023) shows GPT-4 performs better with decomposed tasks.

**Approach:**
Run extraction in two or three focused passes per fragment:

1. **Entity Pass:** "List all entities mentioned in this text with their types."
   → Produces `(entity_name, entity_type)` pairs.
2. **Relationship Pass:** "Given these entities: [list]. What relationships exist
   between them? For each, state subject, predicate, object."
3. **Attribute Pass (optional):** "For each entity, extract its properties
   (labels, descriptions, dates, versions)."

Merge results into a unified triple set per fragment.

**Expected Impact:**
- Research shows 15–25% improvement in F1 score for relation extraction when
  decomposed vs. joint extraction (Zhu et al. 2023, AutoKG).
- Better entity consistency (entity pass establishes canonical names before
  relationship extraction).

**Tradeoffs:**
- 2–3x token cost per fragment.
- Higher latency (sequential LLM calls).
- Best suited for high-value corpora where quality > cost.

**Implementation:**
- New extraction mode in profile: `extraction_strategy: multi_pass`
- Each pass uses a specialized Pydantic response model.
- Results merged with deduplication before writing.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐

---

### 1.6 Linearized Triple Format Instead of JSON

**Problem:** Research (Dai et al. 2025 — "LLMs Can Better Understand Knowledge
Graphs Than We Thought") demonstrates that LLMs process **linearized triples**
(subject-predicate-object one per line) more accurately than fluent natural
language descriptions of the same facts.

**Approach:**
- Instead of asking for JSON output with nested objects, use linearized Turtle-like
  output format:
  ```
  Extract facts as one triple per line in this format:
  <subject> <predicate> <object> .

  Example:
  ex:Pipeline rdf:type pgc:Component .
  ex:Pipeline schema:hasPart ex:Transformer .
  ex:Transformer rdfs:label "JSON Transform" .
  ```
- Parse the output with a simple regex/Turtle parser rather than JSON.

**Expected Impact:**
- Meyer et al. (2023) found that LLMs produce more valid RDF when outputting
  Turtle syntax directly (fewer structural errors than JSON).
- Reduces parsing failures for local models that struggle with nested JSON.
- Especially beneficial for ollama/llama3.2 which often return schema definitions
  instead of instances.

**Tradeoffs:**
- Requires a robust Turtle/N-Triples parser (rdflib can parse Turtle).
- Loss of structured confidence scores per triple (would need a separate field).

**Complexity:** Low–Medium  
**ROI:** ⭐⭐⭐

---

### 1.7 Structured Output with Constrained Decoding

**Problem:** Even with `instructor` enforcing JSON schemas, local models
(llama3.2, mistral) frequently return malformed JSON or schema definitions instead
of instances.

**Approach:**
- Use **grammar-constrained decoding** (supported by llama.cpp / Ollama's
  `format` parameter) to force the model to only generate tokens that conform to
  a JSON schema or BNF grammar at decode time.
- Ollama supports `"format": "json"` and custom JSON schemas in the API:
  ```python
  response = client.chat(
      model="llama3.2",
      messages=[...],
      format={
          "type": "object",
          "properties": {
              "triples": {
                  "type": "array",
                  "items": {
                      "type": "object",
                      "properties": {
                          "subject": {"type": "string"},
                          "predicate": {"type": "string"},
                          "object": {"type": "string"}
                      },
                      "required": ["subject", "predicate", "object"]
                  }
              }
          },
          "required": ["triples"]
      }
  )
  ```

**Expected Impact:**
- Eliminates 100% of JSON parsing failures for supported backends.
- Particularly impactful for local model deployments where `instructor`'s
  retry mechanism adds latency.

**Complexity:** Low  
**ROI:** ⭐⭐⭐⭐ (for local models)

---

## 2. Corpus-Level / Cross-Document Strategies

### 2.1 Community Detection & Hierarchical Summarization (GraphRAG-Inspired)

**Problem:** Entity and relationship extraction at the fragment level misses
global patterns, themes, and cross-document connections.

**Approach (inspired by Microsoft GraphRAG):**
- After initial extraction, build a preliminary entity graph from all extracted
  triples.
- Run **Leiden community detection** on the entity co-occurrence graph to discover
  natural topic communities.
- Generate **community summaries** at multiple hierarchy levels (leaf → intermediate
  → root).
- Use community summaries to:
  1. Enrich subsequent extraction passes (feedback loop).
  2. Answer "global sensemaking" queries ("What are the main themes?").
  3. Identify entities that bridge communities (important connectors).

**Relation to Phase 2:**
This extends our existing Phase 2 (document-level clustering via K-Means on
summaries) to operate on the *extracted entity graph itself* rather than document
summaries. It runs *after* initial extraction and feeds back into re-extraction.

**Expected Impact:**
- Substantial improvement in cross-document entity consistency.
- Enables global queries that RAG alone cannot answer.
- Microsoft's evaluation shows GraphRAG outperforms baseline RAG on
  comprehensiveness and diversity for global questions.

**Complexity:** High  
**ROI:** ⭐⭐⭐⭐

---

### 2.2 Incremental Entity Linking with a Growing Vocabulary

**Problem:** Phase 1's per-document entity catalog doesn't know about entities
discovered in *other* documents. Document N may mint `ex:data-pipeline` while
document 1 already established `ex:DataPipeline` as the canonical IRI.

**Approach:**
- Maintain a **persistent entity registry** (stored in the database) that grows
  as documents are processed.
- Before extracting from a new document, retrieve the top-K most relevant
  entities from the registry (by embedding similarity to the document summary).
- Inject these into the extraction prompt as "KNOWN ENTITIES — prefer these IRIs
  if the text refers to the same concept."
- After extraction, add newly discovered entities to the registry.

**Expected Impact:**
- Dramatic reduction in entity duplication across documents (estimated 40–60%
  fewer duplicate IRIs).
- Works even in streaming/incremental ingest scenarios.
- Enables the graph to converge toward a stable vocabulary over time.

**Implementation:**
- New table: `entity_registry(iri, label, type, embedding, first_seen, doc_count)`
- Query by vector similarity at preprocessing time.
- Exposed as `riverbank entities list` and `riverbank entities merge` CLI commands.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐⭐

---

### 2.3 Cross-Document Relationship Inference

**Problem:** Some relationships span documents. Document A says "Pipeline X reads
from Dataset Y" and Document B says "Dataset Y is stored in System Z." The
transitive relationship "Pipeline X depends on System Z" is never stated in any
single document.

**Approach:**
- After all documents are extracted, run a **graph completion** pass:
  1. Identify entity pairs that are connected by short paths (2–3 hops) but lack
     a direct edge.
  2. For each candidate pair, ask the LLM: "Given that A→B and B→C, is there a
     direct relationship A→C? If so, what predicate?"
  3. Write inferred triples to a separate named graph (e.g.,
     `graph/inferred`) with provenance marking them as derived.

- Alternatively, use **link prediction** via knowledge graph embeddings:
  - Embed entities and relations using TransE/RotatE/ComplEx.
  - Predict missing links where the embedding score exceeds a threshold.
  - More scalable but less interpretable than LLM-based inference.

**Expected Impact:**
- Increases graph connectivity by 10–30% (depending on corpus).
- Particularly valuable for procedural/operational corpora where dependencies
  cross document boundaries.

**Complexity:** High  
**ROI:** ⭐⭐⭐

---

## 3. Post-Extraction Graph Refinement

### 3.1 Embedding-Based Entity Deduplication

**Problem:** The same real-world entity gets multiple IRIs across documents
(e.g., `ex:sesam-dataset`, `ex:dataset`, `ex:Dataset`, `ex:data-set`).

**Approach:**
1. Embed all unique subject/object IRIs using their `rdfs:label` values.
2. Compute pairwise cosine similarity.
3. Cluster entities above a threshold (e.g., 0.92).
4. For each cluster, select the most frequent IRI as canonical.
5. Rewrite non-canonical IRIs as `owl:sameAs` links, or fully merge them.

```bash
riverbank deduplicate-entities --graph http://riverbank.example/graph/trusted \
  --threshold 0.92 --dry-run
```

**Expected Impact:**
- 20–40% reduction in unique entity count.
- Dramatically improves SPARQL query recall.
- Enables meaningful entity-centric views.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐

---

### 3.2 Predicate Normalization & Synonym Collapse

**Problem:** Similar to entity deduplication, but for predicates. The LLM may
emit `ex:hasPart`, `ex:contains`, `ex:includes`, `schema:hasPart` for the same
semantic relationship.

**Approach:**
1. Collect all unique predicates from the graph.
2. For each predicate, retrieve its label and any `rdfs:subPropertyOf` or
   `owl:equivalentProperty` declarations from the ontology.
3. Embed predicate labels and cluster by similarity.
4. Map non-canonical predicates to the ontology-defined canonical form.
5. Rewrite triples in-place (or add `owl:equivalentProperty` links).

**Expected Impact:**
- Reduces predicate vocabulary by 30–50%.
- Makes SPARQL queries more predictable (users don't need to query all synonyms).
- Works synergistically with ontology-grounded extraction (Strategy 1.1).

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐

---

### 3.3 Self-Critique Verification Pass

**Problem:** Low-confidence triples (0.5–0.75) may be hallucinated. The initial
extraction has no mechanism to self-verify.

**Approach:**
For each triple below a confidence threshold:
1. Retrieve the original evidence span from the source document.
2. Ask a second LLM call: "Given the text: '[evidence]', does the following
   claim hold? `subject predicate object`. Answer YES/NO with confidence 0–1."
3. If the verifier says NO or gives confidence < 0.4: quarantine the triple.
4. If YES with high confidence: boost the original confidence.

```yaml
verification:
  enabled: true
  confidence_threshold: 0.75   # only verify triples below this
  drop_below: 0.4              # quarantine if verifier scores < this
  model: gpt-4o-mini           # cheap model for verification
```

**Expected Impact:**
- Eliminates 15–25% of low-quality triples.
- ~5% false-positive rate (correct triples incorrectly dropped).
- Net precision improvement: +10–15%.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐

---

### 3.4 Confidence-Weighted Triple Consolidation

**Problem:** The same triple extracted from multiple fragments gets multiple
confidence scores but only one survives (last-write-wins).

**Approach:**
- When a triple `(s, p, o)` is extracted N times from different fragments with
  confidence scores $c_1, c_2, \ldots, c_n$, consolidate using Bayesian
  combination (noisy-OR):

  $$c_{final} = 1 - \prod_{i=1}^{n} (1 - c_i)$$

  For example: extracted twice with 0.6 and 0.7 → consolidated = 0.88.

- Store the evidence span list for each triple (multi-provenance).
- Expose in SPARQL: `?triple pgc:hasConfidence ?c FILTER(?c > 0.8)`.

**Expected Impact:**
- Triples confirmed by multiple sources get appropriately high confidence.
- Single-source low-confidence triples remain flagged for review.
- Enables confidence-based filtering at query time.

**Complexity:** Low  
**ROI:** ⭐⭐⭐⭐

---

### 3.5 SHACL Constraint Validation

**Problem:** The extracted graph may violate structural constraints that the
ontology defines (wrong domain/range, missing required properties, cardinality
violations).

**Approach:**
- Define a SHACL shapes graph alongside the ontology:
  ```turtle
  pgc:ConceptShape a sh:NodeShape ;
    sh:targetClass pgc:Concept ;
    sh:property [
      sh:path rdfs:label ;
      sh:minCount 1 ;
      sh:datatype xsd:string ;
    ] ;
    sh:property [
      sh:path schema:isPartOf ;
      sh:class pgc:Document ;
    ] .
  ```
- After ingest, run a SHACL validation engine (e.g., `pyshacl`) against the
  named graph.
- Report violations as diagnostics. Optionally: reduce confidence of violating
  triples, or quarantine them.

```bash
riverbank validate-shapes --graph http://riverbank.example/graph/trusted \
  --shapes ontology/pgc-shapes.ttl
```

**Expected Impact:**
- Catches structural errors that CQ-based validation misses.
- Provides actionable feedback to improve extraction prompts.
- Establishes a formal contract between the ontology and the extracted data.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐

---

### 3.6 Triple Deduplication via Canonical Form Normalization

**Problem:** Minor variations in literal values create duplicate triples:
- `ex:Pipe rdfs:label "Data Pipe"` vs. `ex:Pipe rdfs:label "data pipe"`
- `ex:Doc schema:dateCreated "2024-01-15"` vs. `"2024-01-15T00:00:00Z"`

**Approach:**
- Normalize literals before writing:
  - Lowercase + trim whitespace for string labels.
  - Parse dates to ISO 8601 canonical form.
  - Normalize IRIs (lowercase scheme/host, resolve `../`).
- Deduplicate on the normalized form; keep the highest-confidence instance.

**Complexity:** Low  
**ROI:** ⭐⭐⭐

---

## 4. Reasoning & Inference Strategies

### 4.1 OWL 2 RL Forward-Chaining

**Problem:** The extracted graph contains only asserted triples. Many derivable
facts are missing (inverse relationships, transitive hierarchies, type assertions
from domain/range).

**Approach:**
- After ingest, run a lightweight OWL 2 RL forward-chaining reasoner:
  ```python
  import owlrl
  from rdflib import ConjunctiveGraph

  g = ConjunctiveGraph()
  # Load from pg_ripple via SPARQL CONSTRUCT
  owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
  # Write inferred triples to a separate named graph
  ```

- What gets derived:
  - `owl:inverseOf`: `A hasPart B` → `B isPartOf A`
  - `rdfs:subClassOf` transitivity
  - `rdfs:domain`/`rdfs:range` type assertions
  - `owl:TransitiveProperty` closure

- Write to `graph/inferred` (never contaminate the asserted evidence base).

**Expected Impact:**
- 2–5x increase in queryable triples (most are type assertions).
- Enables queries that assume the closed-world assumption.
- Zero hallucination risk (purely deductive).

**Complexity:** Low  
**ROI:** ⭐⭐⭐

---

### 4.2 Knowledge Graph Embedding for Link Prediction

**Problem:** The graph is inherently incomplete. Not all relationships are
explicitly stated in the source text.

**Approach:**
- Train a knowledge graph embedding model (TransE, RotatE, or ComplEx) on the
  extracted triples.
- Score all possible `(s, p, ?)` and `(?, p, o)` candidates.
- Surface top-K predicted links with score > threshold as "suggested triples."
- Present to human reviewers or add with low confidence to a `graph/predicted`
  named graph.

**Tools:** PyKEEN, DGL-KE, or TorchKGE.

**Expected Impact:**
- Can discover relationships that are implicit in the corpus but never explicitly
  stated.
- Useful for exploratory analysis: "What connections is the graph missing?"

**Tradeoffs:**
- Requires sufficient graph density (>500 triples) to train meaningful embeddings.
- Predicted links have no provenance (no evidence span) — purely structural.
- Best used as a suggestion mechanism, not automatic insertion.

**Complexity:** High  
**ROI:** ⭐⭐

---

### 4.3 Rule-Based Inference (SPARQL CONSTRUCT)

**Problem:** Some domain-specific derivations are known a priori but too specific
for OWL reasoning (e.g., "if a document describes a process that has inputs and
outputs, it's a Procedure").

**Approach:**
- Define profile-specific inference rules as SPARQL CONSTRUCT queries:
  ```sparql
  CONSTRUCT {
    ?doc rdf:type pgc:Procedure .
  }
  WHERE {
    ?doc rdf:type pgc:Document .
    ?doc schema:hasPart ?step .
    ?step pgc:hasInput ?input .
    ?step pgc:hasOutput ?output .
  }
  ```
- Run rules after ingest, writing results to `graph/inferred`.
- Rules are defined per profile (different corpora need different rules).

**Expected Impact:**
- Enables domain-specific reasoning without full ontology engineering.
- Transparent and auditable (rules are SPARQL, not black-box ML).
- Cheap to execute.

**Complexity:** Low  
**ROI:** ⭐⭐⭐

---

## 5. Feedback Loop & Continuous Learning

### 5.1 Active Learning: Uncertainty Sampling for Human Review

**Problem:** Manual review of all extracted triples is impractical. Which triples
should humans prioritize?

**Approach:**
- Score each triple by uncertainty:
  - Low confidence (< 0.6)
  - Disagreement between extraction passes (if multi-pass)
  - Novel predicates not seen in golden examples
  - Triples that would change the answer to a competency question
- Surface the top-N most uncertain triples in a review UI (e.g., Label Studio
  integration already documented in `docs/how-to/configure-label-studio.md`).
- Confirmed triples become new golden examples (automatic few-shot expansion).
- Rejected triples become negative examples (teach the model what NOT to extract).

**Expected Impact:**
- Each human review session directly improves extraction quality.
- Creates a virtuous cycle: better golden examples → better extraction → fewer
  uncertain triples → less review needed.
- Maximizes human effort ROI (only review what matters).

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐⭐

---

### 5.2 Automatic Few-Shot Example Expansion

**Problem:** Golden examples are hand-crafted and limited. The `examples/golden/`
directory has only 4 examples for `docs-policy-v1`.

**Approach:**
- After each validated ingest (where `validate-graph` coverage > threshold):
  1. Identify triples that are:
     - High confidence (> 0.9)
     - Satisfy a competency question
     - Involve diverse predicates and entity types
  2. Sample the best candidates and format as few-shot examples.
  3. Append to the profile's golden examples file (with provenance).
- Over time, the few-shot bank grows organically from high-quality extractions.

**Guardrails:**
- Never auto-add if `validate-graph` coverage < 0.8.
- Cap at 10–15 examples per profile (beyond that, diminishing returns).
- Require diversity: no two examples with the same predicate+type combination.

**Complexity:** Low  
**ROI:** ⭐⭐⭐⭐

---

### 5.3 Schema Induction (Bootstrap Ontology from Data)

**Problem:** For new corpora, there's no pre-existing ontology. Writing one
manually requires domain expertise and time.

**Approach:**
- After the first full-corpus extraction (even with low quality):
  1. Collect all unique predicates and entity types.
  2. Compute frequency statistics: which predicates connect which type pairs.
  3. Ask the LLM to propose an ontology:
     ```
     Given these extracted entity types and their frequencies:
       pgc:Concept (45), pgc:Process (23), pgc:Component (18)...
     And these predicates:
       schema:hasPart (67), rdf:type (120), schema:isPartOf (54)...
     
     Propose a minimal OWL ontology with:
     - Class hierarchy
     - Property domain/range declarations
     - Cardinality constraints where obvious
     ```
  4. Human reviews and approves the proposed ontology.
  5. Re-run extraction with the new ontology constraints (Strategy 1.1).

**Expected Impact:**
- Bootstraps quality improvement for corpora that start with zero schema.
- Second extraction pass with schema constraints typically 2x better precision.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐

---

### 5.4 Extraction Quality Regression Tracking

**Problem:** Model upgrades, prompt changes, and code updates can silently
degrade extraction quality. There's no continuous signal.

**Approach:**
- Maintain a **golden test corpus** with known-good triples (ground truth).
- On every CI run / release:
  1. Re-extract the golden corpus.
  2. Compare against ground truth (precision, recall, F1).
  3. Fail the build if quality drops below threshold.
- Store historical metrics for trend analysis.

```bash
riverbank benchmark --profile docs-policy-v1 \
  --golden tests/golden/docs-policy-v1/ \
  --fail-below-f1 0.85
```

**Expected Impact:**
- Prevents silent quality regressions.
- Enables confident model upgrades (try new model → run benchmark → accept/reject).
- Creates accountability: every change is measured.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐

---

## 6. Structural & Format Optimizations

### 6.1 Semantic Chunking (Boundary-Aware Fragmentation)

**Problem:** Fixed-size or heading-based fragmentation splits semantic units
across fragments. A paragraph about "Pipeline architecture" gets cut in half.

**Approach:**
- Use embedding-based boundary detection:
  1. Embed each sentence in the document.
  2. Compute cosine similarity between consecutive sentences.
  3. Split where similarity drops below a threshold (topic transition).
- Alternatively, use the LLM: "Where are the natural topic boundaries in this
  text? Return line numbers."
- Fragments align with semantic units → better extraction quality.

**Expected Impact:**
- Research shows semantic chunking improves retrieval quality by 10–20% vs.
  fixed-size chunks (relevant to both RAG and extraction).
- Fewer "orphan" triples that reference entities introduced in a different
  fragment.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐

---

### 6.2 Overlapping Fragment Windows

**Problem:** Entities mentioned at fragment boundaries lose context. The subject
of a sentence may be in fragment N while the predicate/object are in fragment N+1.

**Approach:**
- When fragmenting, include an **overlap window** (e.g., last 2 sentences of the
  previous fragment prepended to the current one).
- Deduplicate triples extracted from overlapping regions (by content hash).

```yaml
fragmenter:
  strategy: heading_aware
  overlap_sentences: 2        # prepend last 2 sentences of previous fragment
  max_fragment_tokens: 1500
```

**Expected Impact:**
- Reduces boundary-effect entity loss by ~15%.
- Minimal token cost increase (2 sentences ≈ 50 tokens per fragment).

**Complexity:** Low  
**ROI:** ⭐⭐⭐

---

### 6.3 Knowledge-Prefix Adapter (Structure Injection)

**Problem:** LLMs lack structural awareness of the knowledge graph they're
building into. Research (Zhang et al. 2023, KoPA) shows that injecting structural
embeddings as prompt prefixes significantly improves KG completion.

**Approach:**
- Encode the local neighborhood of already-extracted entities as a "knowledge
  prefix" in the extraction prompt:
  ```
  KNOWN GRAPH CONTEXT (entities near this fragment):
  ex:Pipeline → schema:hasPart → ex:Transformer
  ex:Transformer → rdf:type → pgc:Component
  ex:Pipeline → schema:dependsOn → ex:Database

  Now extract additional triples from this fragment, consistent with
  the above context.
  ```
- Retrieved from the graph store (pg_ripple) at extraction time.

**Expected Impact:**
- Improves consistency of new extractions with existing graph.
- Reduces contradictory triples (the model sees what's already asserted).
- Particularly valuable for incremental/streaming ingest.

**Complexity:** Medium  
**ROI:** ⭐⭐⭐⭐

---

## 7. Evaluation & Measurement

### 7.1 Multi-Dimensional Quality Metrics

Define and track these metrics per ingest:

| Metric | Definition | Target |
|--------|-----------|--------|
| **Precision** | Fraction of extracted triples that are factually correct | > 0.85 |
| **Recall** | Fraction of ground-truth triples that are extracted | > 0.70 |
| **F1 Score** | Harmonic mean of precision and recall | > 0.75 |
| **CQ Coverage** | Fraction of competency questions answerable | > 0.80 |
| **Entity Duplication Rate** | Unique entities / total entity mentions | < 1.3x |
| **Predicate Vocabulary Size** | Unique predicates / allowed predicates | < 1.5x |
| **Confidence Distribution** | Mean confidence of retained triples | > 0.75 |
| **SHACL Conformance** | % of entities that pass shapes validation | > 0.90 |
| **Cross-Doc Entity Consistency** | Same entity → same IRI across docs | > 0.85 |
| **Triple Consolidation Ratio** | Multi-source triples / total triples | > 0.20 |

### 7.2 Automated Benchmark Pipeline

```bash
# Run after every ingest or as CI step
riverbank benchmark --profile $PROFILE --golden tests/golden/$PROFILE/ --output metrics.json

# Outputs:
# { "precision": 0.87, "recall": 0.72, "f1": 0.79,
#   "cq_coverage": 0.83, "entity_dup_rate": 1.2, ... }
```

---

## 8. Summary Matrix

| # | Strategy | Stage | ROI | Complexity | Token Cost | Prerequisites |
|---|----------|-------|-----|-----------|-----------|---------------|
| 1.1 | Ontology-grounded extraction | Extraction | ⭐⭐⭐⭐⭐ | Low | 0 | Ontology |
| 1.2 | CQ-guided extraction | Extraction | ⭐⭐⭐⭐ | Low | 0 | Competency Qs |
| 1.3 | Cardinality hints | Extraction | ⭐⭐⭐ | Low | 0 | Ontology |
| 1.4 | Coreference resolution | Pre-extraction | ⭐⭐⭐ | High | +1 call/doc | NLP model |
| 1.5 | Multi-pass extraction | Extraction | ⭐⭐⭐⭐ | Medium | 2–3x | — |
| 1.6 | Linearized triple format | Extraction | ⭐⭐⭐ | Low | 0 | Turtle parser |
| 1.7 | Constrained decoding | Extraction | ⭐⭐⭐⭐ | Low | 0 | Ollama 0.5+ |
| 2.1 | Community detection (GraphRAG) | Corpus | ⭐⭐⭐⭐ | High | ~10k tokens | Graph lib |
| 2.2 | Incremental entity linking | Corpus | ⭐⭐⭐⭐⭐ | Medium | +200 tok/doc | Embedding model |
| 2.3 | Cross-doc relationship inference | Post | ⭐⭐⭐ | High | +1 call/pair | — |
| 3.1 | Entity deduplication | Post | ⭐⭐⭐⭐ | Medium | 0 | Embedding model |
| 3.2 | Predicate normalization | Post | ⭐⭐⭐⭐ | Medium | 0 | Ontology |
| 3.3 | Self-critique verification | Post | ⭐⭐⭐⭐ | Medium | +1 call/triple | — |
| 3.4 | Confidence consolidation | Post | ⭐⭐⭐⭐ | Low | 0 | — |
| 3.5 | SHACL validation | Post | ⭐⭐⭐ | Medium | 0 | SHACL shapes |
| 3.6 | Literal normalization | Post | ⭐⭐⭐ | Low | 0 | — |
| 4.1 | OWL 2 RL inference | Reasoning | ⭐⭐⭐ | Low | 0 | owlrl |
| 4.2 | KG embedding link prediction | Reasoning | ⭐⭐ | High | 0 | PyKEEN |
| 4.3 | SPARQL CONSTRUCT rules | Reasoning | ⭐⭐⭐ | Low | 0 | — |
| 5.1 | Active learning | Feedback | ⭐⭐⭐⭐⭐ | Medium | 0 | Review UI |
| 5.2 | Auto few-shot expansion | Feedback | ⭐⭐⭐⭐ | Low | 0 | validate-graph |
| 5.3 | Schema induction | Feedback | ⭐⭐⭐ | Medium | ~5k tokens | — |
| 5.4 | Quality regression tracking | CI | ⭐⭐⭐⭐ | Medium | Re-extract | Golden corpus |
| 6.1 | Semantic chunking | Fragmentation | ⭐⭐⭐ | Medium | 0 | Embedding model |
| 6.2 | Overlapping fragments | Fragmentation | ⭐⭐⭐ | Low | +50 tok/frag | — |
| 6.3 | Knowledge-prefix adapter | Extraction | ⭐⭐⭐⭐ | Medium | +150 tok/frag | Graph queries |

---

## 9. Recommended Implementation Sequence

### Immediate (v0.11.x — prompt engineering, zero new deps)

1. **Ontology-grounded extraction (1.1)** — Highest ROI, lowest effort. Add
   `allowed_predicates`/`allowed_classes` to profile and inject into prompt.
2. **CQ-guided extraction (1.2)** — Reuse existing competency questions.
3. **Confidence consolidation (3.4)** — Simple aggregation logic in
   `load_triples_with_confidence()`.
4. **Literal normalization (3.6)** — Normalize before write.
5. **Overlapping fragments (6.2)** — Add `overlap_sentences` to fragmenter config.

### Short-term (v0.12.x — entity quality)

6. **Entity deduplication (3.1)** — Already planned as Post-1.
7. **Predicate normalization (3.2)** — Natural companion to dedup.
8. **Incremental entity linking (2.2)** — Persistent entity registry.
9. **Auto few-shot expansion (5.2)** — Organic quality improvement.
10. **Self-critique verification (3.3)** — For triples below confidence threshold.

### Medium-term (v0.13.x — structural improvements)

11. **Constrained decoding (1.7)** — For Ollama users.
12. **Semantic chunking (6.1)** — Better fragment boundaries.
13. **SHACL validation (3.5)** — Define shapes, run after ingest.
14. **Knowledge-prefix adapter (6.3)** — Graph-aware extraction.
15. **Quality regression tracking (5.4)** — CI benchmark.

### Long-term (v1.x — advanced reasoning)

16. **Multi-pass extraction (1.5)** — Decomposed entity/relation passes.
17. **OWL 2 RL inference (4.1)** — Deductive closure.
18. **Community detection (2.1)** — GraphRAG-style hierarchical summarization.
19. **Active learning (5.1)** — Human-in-the-loop with Label Studio.
20. **Cross-doc inference (2.3)** — Link prediction across documents.

---

## 10. References

1. **Zhu, Y. et al. (2023)** — "LLMs for Knowledge Graph Construction and Reasoning: Recent Capabilities and Future Opportunities." *arXiv:2305.13168*. Proposes AutoKG multi-agent framework; shows GPT-4 excels at inference over extraction.

2. **Meyer, L.-P. et al. (2023)** — "Benchmarking the Abilities of Large Language Models for RDF Knowledge Graph Creation and Comprehension: How Well Do LLMs Speak Turtle?" *DL4KG @ ISWC 2023, arXiv:2309.17122*. Finds LLMs struggle with strict output formatting; Turtle syntax more natural than JSON for RDF tasks.

3. **Edge, D. et al. (2024)** — "From Local to Global: A Graph RAG Approach to Query-Focused Summarization." *arXiv:2404.16130*. Introduces GraphRAG: hierarchical community summarization via Leiden algorithm for global sensemaking over private corpora.

4. **Pan, S. et al. (2024)** — "Unifying Large Language Models and Knowledge Graphs: A Roadmap." *IEEE TKDE, arXiv:2306.08302*. Three frameworks: KG-enhanced LLMs, LLM-augmented KGs, and synergized approaches.

5. **Zhang, Y. et al. (2024)** — "Making Large Language Models Perform Better in Knowledge Graph Completion." *arXiv:2310.06671*. Knowledge Prefix Adapter (KoPA): structural embeddings as virtual tokens improve LLM reasoning.

6. **Dai, X. et al. (2025)** — "Large Language Models Can Better Understand Knowledge Graphs Than We Thought." *arXiv:2402.11541*. Linearized triples outperform fluent NL for LLM comprehension of KG information; larger models more susceptible to noisy subgraphs.

7. **Jiang, X. et al. (2025)** — "On the Evolution of Knowledge Graphs: A Survey and Perspective." *arXiv:2310.04835*. Comprehensive survey covering static, dynamic, temporal, and event KGs; discusses KG + LLM synergies.

8. **Microsoft Research (2024)** — "GraphRAG: Unlocking LLM Discovery on Narrative Private Data." Blog + open-source implementation at github.com/microsoft/graphrag.

---

*Last updated: 2025-05-06*
