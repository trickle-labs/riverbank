# LLM Document Preprocessing Plan

## Problem Statement

Currently, riverbank's ingest pipeline fragments documents purely at heading boundaries (`HeadingFragmenter`), then hands each fragment to the extraction LLM with a generic prompt. This produces acceptable results on well-structured documents but suffers from several issues at scale:

1. **Fragment boundaries misalign with semantic units** — a heading section may contain multiple unrelated claims, or a single concept may span two headings.
2. **The extraction LLM receives no domain context** — it must infer entity types, valid predicates, and naming conventions cold from each fragment.
3. **Noise dilutes extraction quality** — boilerplate, navigation sections, and repetitive disclaimers generate low-value fragments that waste LLM calls and add noise to the graph.
4. **Terminology drift** — the same concept appears under different names across fragments (e.g. "Dataset", "data set", "datasets") producing duplicate or disconnected nodes.
5. **Predicate invention** — without constraints, the LLM invents ad-hoc natural-language predicates (e.g. "is a means of storage inside Sesam") instead of formal IRIs.

A preprocessing pass — run once per document before fragmentation — can address all five issues by giving the extraction step richer context and better-bounded input.

---

## Current Pipeline (Baseline)

```
Source File
    │
    ▼
MarkdownParser.parse()        → ParsedDocument (tokens + raw_text)
    │
    ▼
HeadingFragmenter.fragment()  → DocumentFragment[]  (split at # ## ###)
    │
    ▼
IngestGate.check()            → accept/reject per fragment
    │
    ▼
InstructorExtractor.extract() → ExtractedTriple[]  (LLM call per fragment)
    │
    ▼
load_triples_with_confidence() → pg_ripple RDF store
```

---

## Proposed Pipeline (With Preprocessing)

```
Source File
    │
    ▼
MarkdownParser.parse()            → ParsedDocument
    │
    ▼
╔══════════════════════════════════════════════════════════════════╗
║  NEW: LLM Preprocessing Pass (once per document)               ║
║                                                                  ║
║  1. Document Summarization   → executive summary                 ║
║  2. Entity Catalog           → canonical entity names + types    ║
║  3. Predicate Vocabulary     → allowed predicates for domain     ║
║  4. Noise Classification     → sections flagged as boilerplate   ║
║  5. Semantic Boundary Hints  → suggested split points            ║
╚══════════════════════════════════════════════════════════════════╝
    │
    ▼
HeadingFragmenter.fragment()      → DocumentFragment[]
    │
    ▼  (merge/split using boundary hints from preprocessing)
    │
    ▼
IngestGate.check()                → accept/reject
    │
    ▼
InstructorExtractor.extract()     → ExtractedTriple[]
    │                               (enriched with entity catalog +
    │                                predicate vocabulary in system prompt)
    ▼
load_triples_with_confidence()    → pg_ripple
```

---

## Strategy 1: Entity Catalog Extraction

### Concept

Before fragmentation, ask the LLM to scan the full document and produce a **canonical entity catalog**: a list of every named entity with its normalized IRI and type.

### Prompt Design

```
You are a knowledge graph ontologist. Analyze this document and extract a catalog
of all named entities, concepts, and technical terms.

For each entity provide:
- canonical_name: lowercase-hyphenated unique identifier (e.g. "sesam-dataset")
- label: human-readable name as it appears in the document
- type: one of [Concept, System, Component, Process, Role, Configuration, Event]
- aliases: other surface forms found in the document

Return a JSON array of entities. Include ONLY entities that appear in the text.
```

### Output Schema (Pydantic)

```python
class EntityCatalogEntry(BaseModel):
    canonical_name: str          # e.g. "sesam-dataset"
    label: str                   # e.g. "Dataset"
    type: str                    # e.g. "Concept"
    aliases: list[str] = []      # e.g. ["data set", "datasets"]
```

### How It Helps Extraction

The entity catalog is injected into the extraction prompt:

```
Use ONLY these entities as subjects/objects:
- ex:sesam-dataset (type: Concept, aliases: "Dataset", "data set")
- ex:sesam-pipe (type: Component, aliases: "Pipe", "pipes")
- ex:sesam-system (type: System)

If a fragment mentions "data set", map it to ex:sesam-dataset.
```

### Pros

- Eliminates duplicate nodes from terminology variation
- Forces consistent IRI naming across all fragments
- Provides type information to constrain extraction
- Single LLM call per document (amortized across many fragments)

### Cons

- Adds latency: one extra LLM call per document (~5-15s)
- May miss entities that appear in only one fragment
- Catalog size grows with document size (may exceed context window for very large docs)
- LLM may hallucinate entities not in the text

### Mitigation

- Cap catalog at 50 entities per document
- Validate each alias appears in the source text (same citation grounding as extraction)
- For large docs (>20k tokens), chunk into ~10k overlapping windows for catalog extraction

---

## Strategy 2: Predicate Vocabulary Extraction

### Concept

Extract a controlled vocabulary of relationship types (predicates) from the document before extraction begins. This prevents predicate explosion and natural-language predicates.

### Prompt Design

```
You are an ontology designer. Analyze this technical document and identify the
types of relationships described between concepts.

For each relationship type provide:
- predicate_iri: formal IRI using schema.org, Dublin Core, or custom namespace
  (e.g. schema:isPartOf, dcterms:creator, ex:consumes)
- label: human-readable description
- domain: what type of entity is the subject
- range: what type of entity/literal is the object
- evidence: a short excerpt showing this relationship

Return 5-15 predicate types. Prefer existing vocabularies (schema.org, Dublin Core,
SKOS) over custom predicates.
```

### Output Schema

```python
class PredicateEntry(BaseModel):
    predicate_iri: str         # e.g. "schema:isPartOf"
    label: str                 # e.g. "is part of"
    domain: str                # e.g. "Component"
    range: str                 # e.g. "System"
    evidence: str              # excerpt demonstrating the relationship
```

### How It Helps Extraction

Injected into the extraction prompt as a constraint:

```
Use ONLY these predicates:
- schema:isPartOf (Component → System)
- schema:hasPart (System → Component)
- ex:consumes (Pipe → Dataset)
- ex:produces (Pipe → Dataset)
- rdfs:label (any → string literal)
- rdf:type (any → Class)
- dcterms:description (any → string literal)

Do NOT invent new predicates.
```

### Pros

- Eliminates ad-hoc natural-language predicates completely
- Forces alignment with existing vocabularies
- Makes the resulting graph queryable with known predicates
- Enables schema validation downstream

### Cons

- Over-constraining may miss legitimate relationships
- LLM may select inappropriate schema.org mappings
- Requires the preprocessing LLM to be smarter than the extraction LLM
- Small documents may not have enough context to identify all relationship types

### Mitigation

- Allow a `ex:relatedTo` catch-all with lower confidence for uncategorized relationships
- Include 2-3 "generic" predicates always (rdfs:label, rdf:type, dcterms:description)
- Let users pre-define predicates in the profile YAML (override LLM extraction)

---

## Strategy 3: Noise Classification

### Concept

Classify each document section as "content" or "boilerplate" before fragmentation. Skip boilerplate sections entirely.

### Prompt Design

```
Classify each section of this document as one of:
- CONTENT: contains factual claims worth extracting
- BOILERPLATE: navigation, table of contents, disclaimers, repetitive templates
- METADATA: authorship, dates, version numbers (extract as document-level metadata only)

For each section provide:
- heading: the section heading text
- classification: CONTENT | BOILERPLATE | METADATA
- reason: brief explanation
```

### How It Helps Extraction

Sections classified as BOILERPLATE are skipped entirely (no LLM extraction call). METADATA sections generate only document-level triples (e.g., `ex:doc dcterms:creator "Author"`).

### Pros

- Reduces LLM calls (skip 20-40% of fragments in typical documentation)
- Eliminates noise triples from navigation/boilerplate
- Faster pipeline execution
- Lower cost

### Cons

- Risk of false positives (useful content classified as boilerplate)
- Adds one LLM call per document
- Classification accuracy depends on model quality
- May not help for well-curated corpora with no boilerplate

### Mitigation

- Conservative threshold: only skip sections classified with >0.9 confidence
- Log skipped sections for human review
- Allow override via profile: `skip_boilerplate: false`

---

## Strategy 4: Semantic Boundary Detection

### Concept

Ask the LLM to identify optimal semantic boundaries for fragmentation, supplementing or overriding heading-based splitting.

### Prompt Design

```
This document is fragmented at heading boundaries for knowledge extraction.
Some headings create fragments that mix multiple unrelated topics, while
related content sometimes spans multiple headings.

Analyze the document structure and suggest:
- merge: pairs of adjacent sections that should be combined
- split: sections that contain multiple distinct topics (suggest split points)

For each suggestion provide:
- action: "merge" | "split"
- sections: list of heading paths involved
- reason: brief explanation
- split_after: (for splits) the text after which to split
```

### How It Helps Extraction

Fragments become semantically coherent units. The extraction LLM receives focused context rather than mixed-topic sections.

### Pros

- Better fragment quality → better extraction quality
- Handles documents where heading structure doesn't match semantic structure
- Can detect when a long section should be split for better LLM focus

### Cons

- Complex implementation: must modify fragment boundaries post-hoc
- May break fragment key stability (invalidates hash-based skip)
- Adds significant latency for the preprocessing call
- Difficult to validate correctness automatically

### Mitigation

- Use as advisory only: suggest splits but keep heading-based fragments as primary
- Only split fragments exceeding `max_fragment_tokens`
- Only merge fragments below `min_fragment_length`

### Extension: Embedding-Based Semantic Chunker

Instead of (or alongside) an LLM boundary call, use **embedding similarity** between adjacent sentence windows to detect semantic shift points without any LLM cost:

```python
# Compute rolling cosine similarity between sentence-window embeddings.
# Fire a boundary where similarity drops below threshold (e.g. 0.75).
for i in range(len(windows) - 1):
    sim = cosine_similarity(windows[i].embed, windows[i+1].embed)
    if sim < BOUNDARY_THRESHOLD:
        boundaries.append(windows[i+1].start_char)
```

Boundaries produced this way can be used as secondary split points inside the heading-fragmented text. Because no LLM call is needed, this adds negligible latency.

### Extension: Overlapping Sliding Windows

For fragments that exceed `max_fragment_tokens`, emit **overlapping windows** (20% overlap) instead of hard cuts. This ensures triples that straddle a boundary are captured by at least one window, at the cost of a small number of duplicate triples (de-duplicated in the post-extraction pass).

---

## Strategy 5: Document Summary as Global Context

### Concept

Generate a 2-3 sentence document summary and inject it into every extraction call as global context. This helps the extraction LLM understand what domain it's working in.

### Prompt Design

```
Summarize this document in 2-3 sentences. Focus on:
- What domain/system it describes
- The main concepts and their relationships
- The purpose of the documentation
```

### How It Helps Extraction

Added to the extraction system prompt:

```
Document context: This document describes Sesam's data integration platform,
focusing on how Pipes consume data from Sources and write to Datasets.
The main concepts are Pipe, Dataset, System, and Transformer.

Now extract triples from this specific section:
[fragment text]
```

### Pros

- Minimal cost: one very short LLM call per document
- Provides domain grounding for every fragment extraction
- Helps disambiguate terms that are generic in isolation
- Easy to implement (just prepend to extraction prompt)

### Cons

- Limited impact if documents are already well-titled
- Summary may be inaccurate and mislead extraction
- Slight increase in prompt token count per extraction call

### Mitigation

- Keep summary to <100 tokens
- Validate summary mentions entities found in the entity catalog

---

## Strategy 6: Few-Shot Golden Examples in Extraction Prompt

### Concept

Inject 2-3 verified (subject, predicate, object) triples from `tests/golden/` directly into the extraction prompt as **correct examples for this domain and profile**. This is the highest-leverage single-prompt change for local models — it gives the extraction LLM concrete evidence of the expected output format and ontology, grounded in the actual corpus vocabulary.

### How It Helps Extraction

```
EXAMPLES (correct triples for this corpus):
  ex:sesam-pipe  schema:isPartOf  ex:sesam-system    confidence: 0.95
  ex:sesam-dataset  rdf:type  ex:DataStore           confidence: 0.90
  ex:sesam-pipe  ex:consumes  ex:sesam-dataset       confidence: 0.85

Now extract triples from this section using the same style:
[fragment text]
```

### Implementation

Golden triples are read from the profile's `competency_questions` results or from a dedicated `examples/golden/*.ttl` file. The `DocumentPreprocessor` (or a new `ExemplarSelector`) selects the 2-3 most semantically similar golden triples to the current fragment (using embedding similarity) before each extraction call.

```yaml
# profile YAML extension
few_shot:
  enabled: true
  source: tests/golden/       # directory of .ttl files with verified triples
  max_examples: 3
  selection: semantic         # "semantic" | "random" | "fixed"
```

### Pros

- Biggest quality jump for local models with essentially zero extra LLM calls
- Anchors predicate naming to the corpus vocabulary
- Fixes the schema-vs-instance confusion bug in llama3.2/mistral
- Trivially composable with Phase 1 preprocessing

### Cons

- Requires at least a few verified golden triples to exist upfront (cold-start problem)
- Wrong golden examples can mislead the LLM
- Semantic selection requires embedding calls per fragment

### Mitigation

- Bootstrap golden triples via `riverbank ingest --dry-run` + manual review on small corpus
- Fall back to `selection: random` when no embeddings are available
- Gate on `few_shot.enabled: true` in profile; off by default

---

## Recommended Implementation

### Phase 2: Hierarchical Corpus Preprocessing

Before processing individual documents, run a **corpus-level analysis** that produces a context hierarchy injected into every extraction:

```
Corpus (N docs)
    │
    ▼
1. Embed all doc summaries (pgvector / sentence-transformers)
    │
    ▼
2. Cluster documents (hierarchical, ~15 docs per cluster)
    │
    ├──→ Corpus Summary    "This corpus covers Sesam data integration…"
    │
    └──→ Cluster Summaries (per group)
            │
            └──→ Document Summaries + Entity Catalogs
                    │
                    └──→ Fragment extraction with tiered context
```

Each fragment extraction call receives:

```
CORPUS CONTEXT:
"This corpus documents Sesam, a data integration platform with
three main components: Pipes (transformers), Datasets (storage),
and Systems (sources/sinks)."

CLUSTER CONTEXT:
"You're in the ARCHITECTURE cluster. Documents here describe system
design patterns. Expected entities: System, Pipe, Dataset.
Expected predicates: hasComponent, connectedTo, orchestrates."

DOCUMENT CONTEXT:
"This document 'System Architecture Overview' describes how
Sesam's core components interact…"

Now extract from this fragment:
[fragment text]
```

**Benefits over doc-level only:**
- Entity deduplication becomes **corpus-wide** (not just per-document)
- Predicate vocabulary unified across the whole corpus
- Cross-document relationships detected (e.g., "config docs depend on architecture docs")
- Cluster-specific predicate vocabularies prevent cross-contamination

**Cost:**
- Upfront clustering: ~7k tokens (one-time per corpus ingestion)
- Per-fragment overhead: +200 tokens (tiered context added to every extraction)
- For 100-doc, 500-fragment corpus: ~107k extra tokens total (~$0.03 GPT-4o)

**When to use:**
- ✅ Corpus ≥ 50 documents
- ✅ Multiple topic areas in corpus
- ✅ Cross-document entity consistency matters
- ❌ Small corpora (<20 docs) — overhead not justified
- ❌ Streaming / real-time ingestion

**Cluster stability:** Cluster assignments are cached by corpus hash. Re-clustering triggers only when >20% of documents change. A new document added to an existing corpus joins the nearest cluster without full re-run.

**Implementation:**

```python
@dataclass
class ClusterSummary:
    cluster_id: int
    label: str                       # e.g. "Architecture"
    doc_iris: list[str]              # documents in this cluster
    summary: str                     # cluster-level summary
    entity_vocabulary: list[str]     # canonical entities in this cluster
    predicate_vocabulary: list[str]  # predicates seen in this cluster

@dataclass
class CorpusAnalysis:
    corpus_summary: str
    clusters: list[ClusterSummary]
    doc_cluster_map: dict[str, int]  # source_iri → cluster_id

class CorpusPreprocessor:
    def analyze(self, doc_summaries: dict[str, str]) -> CorpusAnalysis:
        """Cluster docs by embedding similarity, summarize each cluster."""
        embeddings = self._embed_all(doc_summaries)
        cluster_assignments = self._cluster(embeddings)
        cluster_summaries = self._summarize_clusters(
            cluster_assignments, doc_summaries
        )
        corpus_summary = self._summarize_corpus(cluster_summaries)
        return CorpusAnalysis(...)
```

---

### Phase 1: Document Summary + Entity Catalog (MVP)

Combine Strategy 1 and Strategy 5 as they have the best cost/benefit ratio:

```python
@dataclass
class PreprocessingResult:
    """Output of the LLM preprocessing pass."""
    summary: str                           # 2-3 sentence document summary
    entity_catalog: list[EntityCatalogEntry]  # canonical entities with aliases
    predicate_vocabulary: list[str] | None    # optional predicate constraints
    noise_sections: list[str]                 # heading paths to skip
```

**Implementation location:** `src/riverbank/preprocessors/__init__.py`

**Profile configuration:**

```yaml
preprocessing:
  enabled: true
  strategies:
    - document_summary
    - entity_catalog
  max_entities: 50
  predefined_predicates:
    - "rdf:type"
    - "rdfs:label"
    - "schema:isPartOf"
    - "schema:hasPart"
    - "dcterms:description"
```

**Pipeline integration:**

```python
# In _run_inner(), after parsing but before fragmentation:
if profile.preprocessing_enabled:
    preprocessor = DocumentPreprocessor(settings)
    preprocess_result = preprocessor.preprocess(doc.raw_text, profile)
    
    # Enrich extraction prompt with preprocessing output
    enriched_prompt = _build_enriched_prompt(
        base_prompt=profile.prompt_text,
        summary=preprocess_result.summary,
        entity_catalog=preprocess_result.entity_catalog,
    )
    
    # Pass enriched prompt to extractor via profile override
    profile_with_context = replace(profile, prompt_text=enriched_prompt)
```

**Enriched extraction prompt template:**

```
You are a knowledge graph compiler.

DOCUMENT CONTEXT:
{summary}

ENTITY CATALOG (use these canonical names):
{entity_catalog_formatted}

ALLOWED PREDICATES:
{predicate_list}

Extract factual claims from the following section as RDF triples.
Map all entity mentions to their canonical names from the catalog above.
Use ONLY predicates from the allowed list.

For each claim provide subject, predicate, object_value, confidence, and evidence.
Only extract claims directly supported by the text.
```

### Phase 2: Add Noise Classification

Once Phase 1 is validated, add noise classification as a second preprocessing output. Flagged sections skip extraction entirely.

### Phase 3: Semantic Boundary Detection

Only implement if Phase 1+2 measurements show fragment boundary issues are a significant error source.

---

## Cost Analysis

| Corpus Size | Current (extraction only) | With Preprocessing (Phase 1) | Overhead |
|------------|--------------------------|-------------------------------|----------|
| 10 docs, 50 fragments | 50 LLM calls | 10 + 50 = 60 LLM calls | +20% |
| 50 docs, 200 fragments | 200 LLM calls | 50 + 200 = 250 LLM calls | +25% |
| 100 docs, 500 fragments | 500 LLM calls | 100 + 500 = 600 LLM calls | +20% |

**Token cost increase:** Preprocessing prompts are ~500 tokens input + ~500 tokens output per document. Enriched extraction prompts add ~200 tokens to each fragment call.

**Net cost for 100-doc corpus:**
- Preprocessing: 100 × (500 + 500) = 100k tokens
- Enriched prompts: 500 × 200 = 100k tokens
- Total overhead: ~200k tokens (~$0.06 at GPT-4o pricing, negligible for Ollama)

**Expected quality improvement:** 30-50% reduction in:
- Duplicate entities (from alias normalization)
- Ad-hoc predicates (from vocabulary constraints)
- Low-value triples (from noise filtering)

---

## Measurement Plan

To validate preprocessing effectiveness, compare:

1. **Baseline:** Ingest corpus without preprocessing
2. **With preprocessing:** Same corpus, same model, preprocessing enabled

Metrics:
- Triple count (expect ~20% fewer but higher quality)
- Unique predicates (expect 60-80% reduction in predicate vocabulary)
- Unique subjects (expect ~30% reduction from alias deduplication)
- Competency question pass rate (expect improvement)
- Manual precision/recall on 20 randomly sampled triples

```bash
# Baseline
riverbank clear-graph --yes
riverbank ingest corpus/ --profile baseline.yaml
riverbank query "SELECT (COUNT(DISTINCT ?p) AS ?predicates) WHERE { ?s ?p ?o }"
riverbank query "SELECT (COUNT(DISTINCT ?s) AS ?subjects) WHERE { ?s ?p ?o }"

# With preprocessing
riverbank clear-graph --yes
riverbank ingest corpus/ --profile preprocessed.yaml
riverbank query "SELECT (COUNT(DISTINCT ?p) AS ?predicates) WHERE { ?s ?p ?o }"
riverbank query "SELECT (COUNT(DISTINCT ?s) AS ?subjects) WHERE { ?s ?p ?o }"
```

---

## Implementation Checklist

- [ ] Create `src/riverbank/preprocessors/__init__.py` with `DocumentPreprocessor` class
- [ ] Define `PreprocessingResult` dataclass
- [ ] Implement entity catalog extraction prompt
- [ ] Implement document summary extraction prompt
- [ ] Add `preprocessing` section to `CompilerProfile` dataclass
- [ ] Add YAML support for preprocessing configuration in profiles
- [ ] Integrate preprocessing into `_run_inner()` pipeline step
- [ ] Build enriched prompt template with entity catalog injection
- [ ] Add `--enable-preprocessing` CLI flag (or profile-based toggle)
- [ ] Add preprocessing diagnostics to stats (preprocessing_tokens, preprocessing_calls)
- [ ] Write unit tests for entity catalog parsing
- [ ] Write integration test comparing extraction with/without preprocessing
- [ ] Create example profile: `examples/profiles/docs-policy-v1-preprocessed.yaml`
- [ ] Update progress callback to report preprocessing step
- [ ] Document in `docs/concepts/preprocessing.md`

---

## Risks and Open Questions

1. **Context window limits:** For documents >30k tokens, the preprocessing LLM may truncate or hallucinate. Mitigation: chunk large documents into overlapping windows for preprocessing.

2. **Model dependency:** Preprocessing quality depends heavily on model capability. Small local models (llama3.2, mistral) may produce poor entity catalogs. Consider using a larger model for preprocessing even when using a smaller model for extraction.

3. **Preprocessing cache invalidation:** If a document changes, the preprocessing result must be recomputed. Should preprocessing results be persisted? Suggestion: store in `_riverbank.preprocessing_cache` table, keyed by document hash.

4. **Circular dependency:** The vocabulary pass (`mode: vocabulary`) already extracts SKOS concepts. Should preprocessing replace or complement the vocabulary pass? Recommendation: preprocessing complements — vocabulary pass populates a persistent graph-backed vocabulary, preprocessing produces ephemeral per-document context.

5. **Multi-document consistency:** Entity catalogs are per-document. The same concept may get different canonical names in different documents. Mitigation: after preprocessing, run a deduplication pass across all entity catalogs to merge equivalent entries.

---

## Post-Extraction Quality Strategies

The following strategies run **after** `load_triples_with_confidence()` has written to pg_ripple. They improve graph quality without re-running extraction.

---

### Post-1: Embedding-Based Entity Deduplication

**Problem:** The entity catalog deduplicates within a document, but the same concept may receive different canonical names across documents (e.g., `ex:sesam-dataset` in doc A and `ex:dataset` in doc B).

**Approach:** After a full corpus ingest:
1. Embed all unique subject/object IRIs (using their `rdfs:label` values as text).
2. Cluster by cosine similarity (threshold ~0.92).
3. Promote the most common IRI in each cluster as canonical; rewrite the others as `owl:sameAs` links.

```bash
# Planned CLI command
riverbank deduplicate-entities --graph http://riverbank.example/graph/trusted \
  --threshold 0.92 --dry-run
```

**Implementation location:** `src/riverbank/postprocessors/dedup.py`  
**Dependency:** `sentence-transformers` (already a transitive dep via `nomic-embed-text`)  
**Cost:** One embedding call per unique entity IRI (typically 50–500 per corpus)

---

### Post-2: Self-Critique Verification Pass

**Problem:** Low-confidence triples (0.5–0.75) are extracted but may not be well-supported by the source text.

**Approach:** After extraction, run a second cheap LLM call per low-confidence triple:

```
Given the text: "[evidence excerpt]"
Does the following claim hold?
  subject:   ex:sesam-pipe
  predicate: schema:isPartOf
  object:    ex:sesam-system

Answer YES or NO and give your confidence (0.0–1.0).
```

Triples confirmed YES get their confidence boosted; NO responses drop the triple into quarantine for human review.

```yaml
# profile YAML extension
verification:
  enabled: true
  confidence_threshold: 0.75   # only verify triples below this score
  drop_below: 0.4              # quarantine triples where verifier scores < 0.4
```

**Expected effect:** ~15–25% of low-confidence triples eliminated; ~5% false-positive rate (triples incorrectly dropped).

---

### Post-3: OWL/RDFS Inference

**Problem:** The raw extracted graph contains only asserted triples. Many derivable facts are missing (e.g., inverse relationships, transitive hierarchies, type assertions from domain/range).

**Approach:** After ingest, run a lightweight OWL 2 RL forward-chaining reasoner over the named graph:

```python
# Using owlrl (pure Python, MIT license)
import owlrl
from rdflib import ConjunctiveGraph

g = ConjunctiveGraph()
# load from pg_ripple via SPARQL CONSTRUCT
owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
# write inferred triples back to a separate named graph
```

**What gets derived automatically:**
- `owl:inverseOf`: if `ex:pipe schema:hasPart ex:dataset` → infers `ex:dataset schema:isPartOf ex:pipe`
- `rdfs:subClassOf` transitivity: type hierarchies propagate through inheritance chains
- `rdfs:domain`/`rdfs:range`: if `ex:consumes rdfs:domain ex:Pipe` → infers `rdf:type ex:Pipe` for all subjects of `ex:consumes`

Inferred triples are written to a separate named graph (e.g., `http://riverbank.example/graph/inferred`) so they never contaminate the asserted evidence base.

**CLI:**
```bash
riverbank infer --ontology ontology/pgc.ttl \
  --graph http://riverbank.example/graph/trusted \
  --output-graph http://riverbank.example/graph/inferred
```

---

### Post-4: Provenance-Aware Confidence Decay

**Problem:** Triples extracted from older documents remain in the graph at full confidence even when the source may be outdated.

**Approach:** Attach a `dcterms:modified` timestamp to each source document at ingest time. At query time, apply a half-life decay function to reported confidence:

$$
c_{\text{effective}} = c_{\text{extracted}} \times e^{-\lambda \cdot \Delta t}
$$

where $\lambda$ is a `decay_half_life_days` parameter in the profile and $\Delta t$ is days since `dcterms:modified`.

This is implemented as a SPARQL expression function rather than modifying stored values, so historical evidence is never deleted.

```yaml
# profile YAML extension
confidence:
  decay_half_life_days: 365   # confidence halves after 1 year; 0 = no decay
```

```sparql
# Example: query with decay applied
SELECT ?s ?p ?o ?effective_confidence WHERE {
  GRAPH <http://riverbank.example/graph/trusted> {
    ?s ?p ?o .
    ?triple pgc:confidence ?raw_confidence ;
            pgc:sourceModified ?modified .
  }
  BIND(NOW() - ?modified AS ?age_days)
  BIND(?raw_confidence * EXP(-0.00190 * ?age_days) AS ?effective_confidence)
  FILTER(?effective_confidence > 0.5)
}
```

---

### Post-5: Cross-Validation via Competency Questions

**Problem:** Extraction quality regresses silently across re-ingests and model upgrades.

**Approach:** Run the profile's `competency_questions` (SPARQL ASK/SELECT) after every ingest and report a **coverage score**. This turns CQs from a one-off CI check into a continuous quality metric.

```bash
riverbank validate-graph --profile docs-policy-v1.yaml
# → CQ-01: PASS  (The corpus defines a concept called 'Confidence')
# → CQ-02: PASS  (Evidence spans have character offsets)
# → CQ-03: FAIL  (Pipe → Dataset relationship not found)
# Coverage: 2/3 (67%)
```

Failed CQs are surfaced as `WARNING` in the CLI output and emitted as OpenTelemetry events so they appear in Langfuse traces. A `--fail-below` threshold option can cause the command to exit non-zero (for CI gating).

**Implementation location:** extend `src/riverbank/cli.py` and `src/riverbank/catalog/graph.py`  
**Cost:** Negligible — CQs are cheap SPARQL queries against the existing store

---

## Quality Improvement Roadmap

| Strategy | Scope | Phase | Est. ROI | Complexity |
|----------|-------|-------|----------|------------|
| Few-Shot Golden Examples (Strategy 6) | Extraction prompt | Phase 1 | ⭐⭐⭐⭐⭐ | Low |
| Entity Catalog (Strategy 1) | Per-document | Phase 1 ✅ | ⭐⭐⭐⭐ | Medium |
| Document Summary (Strategy 5) | Per-document | Phase 1 ✅ | ⭐⭐⭐ | Low |
| Embedding-Based Deduplication (Post-1) | Post-ingest | Phase 2 | ⭐⭐⭐⭐ | Medium |
| Competency Question Validation (Post-5) | Post-ingest | Phase 2 | ⭐⭐⭐ | Low |
| Self-Critique Verification (Post-2) | Post-extraction | Phase 3 | ⭐⭐⭐ | Medium |
| Semantic Chunker (Strategy 4 ext.) | Fragmentation | Phase 3 | ⭐⭐⭐ | Medium |
| OWL/RDFS Inference (Post-3) | Post-ingest | Phase 3 | ⭐⭐ | Low |
| Corpus Clustering (Phase 2 preprocessing) | Corpus-level | Phase 4 | ⭐⭐⭐⭐ | High |
| Confidence Decay (Post-4) | Query-time | Phase 4 | ⭐⭐ | Low |
