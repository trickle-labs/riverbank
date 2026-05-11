# Tune extraction quality

This guide walks through every lever you can pull to improve the quality, consistency, and volume of triples produced by `riverbank ingest`. It assumes you have a working profile and at least one ingest run to look at.

For a full explanation of what happens at each pipeline stage, see [How riverbank ingest works](../tutorials/ingestion-deep-dive.md).

> **Reduce cost before tuning quality:** If you're working with large documents (Wikipedia articles, long reports), consider enabling [document distillation](use-document-distillation.md) first. Distillation removes non-extractable sections *before* fragmentation, reducing the token budget spent on content that would never produce useful triples.

---

## The quality spectrum

riverbank lets you trade off along two axes:

```
Precision ◄─────────────────────────────► Recall
          fewer, more reliable triples     more triples, some uncertain

Conservative ◄──────────────────────────► Permissive
              strict evidence checking      accept plausible inference
```

You can tune both axes independently. A typical starting point for a new corpus is permissive + high recall, then tighten as you understand the domain.

---

## 1. Extraction volume — how many triples?

The single biggest quality problem with local models is **too few triples**. Without a volume signal, most models stop after 10–20 triples.

### Set an extraction target

```yaml
extraction_strategy:
  extraction_target:
    min_triples: 60      # Ask the LLM for at least this many
    max_triples: 150     # Cap to avoid runaway output
```

This injects an `EXTRACTION VOLUME REQUIREMENT` block into the prompt:

```
EXTRACTION VOLUME REQUIREMENT
Extract at least 60 triples. Do not stop early.
Target 60–150 triples. Be exhaustive.
CRITICAL — DO NOT SKIP EVIDENCE: every triple must include a verbatim excerpt.
A triple without an excerpt will be DISCARDED.
```

It also automatically raises Ollama's `num_predict` (output token budget) to accommodate the target:

```
num_predict = max(4096, max_triples × 160 + 512)
```

Without this, the default 2 048-token cap silently truncates output at ~12–15 triples.

**Recommended starting values by document type:**

| Document type | `min_triples` | `max_triples` |
|--------------|--------------|--------------|
| Short blog post (< 5 k chars) | 15 | 50 |
| Wikipedia biography | 60 | 150 |
| Research paper | 30 | 100 |
| Technical runbook | 40 | 120 |
| Full documentation site | 70 | 200 |

---

## 2. Vocabulary constraints — what predicates?

Without constraints, the LLM invents a new predicate for every fact: `coined_word`, `coined_term`, `coined_unit` all appear for the same relationship. This makes queries brittle.

### Option A: List allowed predicates in the profile

```yaml
allowed_predicates:
  - "ex:born_in"
  - "ex:born_on"
  - "ex:died_in"
  - "ex:died_on"
  - "ex:nationality"
  - "ex:discovered"
  - "ex:collaborated_with"
  - "ex:received_award"
  - "ex:known_for"
  - "ex:worked_at"
  - "ex:educated_at"
  - "ex:wrote"
  - "ex:parent_of"
  - "ex:married_to"
```

**Effect on the prompt:** A `VOCABULARY CONSTRAINTS` block is injected that lists the allowed predicates and instructs the LLM to use only these. Any triple with a predicate not in this list is rejected by the `OntologyFilter` before writing.

**Effect on quality:** Dramatically reduces predicate proliferation. A 150-triple run that would otherwise produce 80+ distinct predicates is constrained to your 14.

### Option B: Auto-induce a vocabulary

If you don't know the right predicates yet, do an unconstrained run first and then let riverbank propose a schema:

```bash
# 1. Run unconstrained to see what the LLM naturally produces
riverbank ingest my-corpus/ --profile my-profile.yaml

# 2. Inspect the predicates in the graph
riverbank query "SELECT ?p (COUNT(*) AS ?n) WHERE { ?s ?p ?o } GROUP BY ?p ORDER BY DESC(?n)"

# 3. Induce a schema from the statistics
riverbank induce-schema \
  --graph http://riverbank.example/graph/trusted \
  --output ontology/induced.ttl

# 4. Review and edit ontology/induced.ttl, then add to your profile
```

The induced ontology is an OWL Turtle file declaring `owl:ObjectProperty` or `owl:DatatypeProperty` for each significant predicate, with `rdfs:domain`/`rdfs:range` where the statistics support it. Copy the predicate list to `allowed_predicates` in your profile.

### Option C: Use standard vocabularies

You can use `schema:`, `dcterms:`, `foaf:`, or any other namespace in your allowlist:

```yaml
allowed_predicates:
  - "schema:birthDate"
  - "schema:birthPlace"
  - "schema:deathDate"
  - "schema:memberOf"
  - "schema:alumniOf"
  - "schema:award"
  - "foaf:knows"
```

The prompt will instruct the LLM to use these prefixes. Add the prefix declarations to the prompt if the model doesn't know them.

### Cardinality constraints

Prevent the LLM from writing two `birthDate` values for the same person:

```yaml
predicate_constraints:
  schema:birthDate:
    max_cardinality: 1
  schema:deathDate:
    max_cardinality: 1
  schema:birthPlace:
    max_cardinality: 1
```

---

## 3. Evidence grounding — how strict on citations?

Every extracted triple must cite a verbatim excerpt from the source. The similarity between the excerpt and the source text is scored 0–100.

### The two-tier citation policy

```yaml
extraction_strategy:
  citation_floor: 40    # Default: 40
```

| Score | Outcome |
|-------|---------|
| Below `citation_floor` | Hard reject — excerpt absent or fabricated |
| At or above floor | Soft penalty: `conf_final = conf_llm × (sim / 100)` |

**Example:** A triple with `conf_llm = 0.85` and `sim = 65` gets `conf_final = 0.55` — routed to tentative, not discarded.

### Tuning the floor

| Goal | `citation_floor` |
|------|-----------------|
| Accept anything plausible | 20 |
| Default (catches fabrications) | 40 |
| Strict grounding required | 60 |
| Near-verbatim only | 80 |

Setting `citation_floor: 0` turns off hard rejection entirely (only the soft penalty applies). Setting `citation_floor: 100` requires exact matches — too strict for real use since the LLM almost always paraphrases slightly.

---

## 4. Ontology-grounded validation — SHACL

After triples are written, you can validate them against a SHACL shapes graph to catch structural violations: missing required properties, wrong datatypes, cardinality violations.

### Write a shapes file

```turtle
# ontology/biography-shapes.ttl
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix ex:    <http://riverbank.example/entity/> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .

ex:PersonShape
    a                sh:NodeShape ;
    sh:targetClass   ex:Person ;

    sh:property [
        sh:path      ex:born_in ;
        sh:maxCount  1 ;
        sh:message   "A person can only have one birthplace." ;
    ] ;

    sh:property [
        sh:path      ex:born_on ;
        sh:datatype  xsd:date ;
        sh:maxCount  1 ;
        sh:message   "ex:born_on must be an xsd:date." ;
    ] .
```

### Enable in the profile

```yaml
shacl_validation:
  enabled: true
  shapes_path: ontology/biography-shapes.ttl
  reduce_confidence: true       # Penalise violating triples
  confidence_penalty: 0.15     # Subtract this from their confidence
```

### Run on demand

```bash
riverbank validate-shapes \
  --graph http://riverbank.example/graph/trusted \
  --shapes ontology/biography-shapes.ttl
```

---

## 5. Precision vs. recall trade-off — extraction focus

```yaml
extraction_focus: "comprehensive"    # Default — all factual claims
extraction_focus: "high_precision"   # Explicit statements only, conf ≥ 0.90, no inference
extraction_focus: "facts_only"       # Stated facts only, excludes opinions/hedging
```

Each value injects a different guidance block at the top of the prompt. `high_precision` also raises the effective confidence floor by instructing the LLM not to assign confidence below 0.90 unless it is genuinely uncertain.

---

## 6. Conservative vs. permissive extraction

```yaml
extraction_strategy:
  mode: "conservative"    # Default — explicit assertions only
  mode: "permissive"      # Accept strong inferences and confident implications
```

Permissive mode injects tiered guidance that explicitly invites the LLM to reason beyond literal statements:

```
EXTRACTION TIERS
- Tier 1 (conf ≥ 0.85): Explicitly stated facts
- Tier 2 (conf 0.65–0.84): Strong implications
- Tier 3 (conf 0.45–0.64): Reasonable inferences that are well-supported
```

Use permissive mode when you want maximum recall and are happy to review tentative triples before promoting them to trusted.

---

## 7. Preprocessing — better context for the LLM

Preprocessing runs before the main extraction call and injects two types of supporting context into the prompt.

### NLP backend (fast, no extra LLM cost)

```yaml
preprocessing:
  enabled: true
  backend: "nlp"    # sumy LexRank summarizer + spaCy NER
  max_tokens_for_preprocessing: 4000
```

Produces:
- A 3–5 sentence extractive summary using LexRank
- A named entity catalog (persons, organisations, locations, dates) from spaCy

The entity catalog normalises entity labels before extraction, which significantly reduces IRI proliferation (`ex:Marie_Curie` vs. `ex:MarieCurie` vs. `ex:Marie_S_Curie`).

### LLM backend (slower, higher quality)

```yaml
preprocessing:
  enabled: true
  backend: "llm"
  coreference: "llm"    # Resolve "she", "her" to entity names
```

Use when:
- The document has heavy pronoun use ("she later moved to…")
- Entity names are highly ambiguous or multilingual
- You need abstractive (not extractive) summaries

### Coreference resolution

```yaml
preprocessing:
  coreference: "spacy"    # Fast — uses spaCy coref model
  coreference: "llm"      # Slow — rewrites pronouns before extraction
  coreference: "disabled" # Default
```

Coreference resolution rewrites the source text before extraction so `"she"` → `"Marie Curie"` throughout. This eliminates subjects like `ex:She` appearing in triples.

---

## 8. NLI verification

A cross-encoder model (`cross-encoder/nli-distilroberta-base`) checks whether each extracted claim is entailed by the source text. This runs locally, with no LLM cost.

```yaml
verification:
  enabled: true
  backend: "nli"
```

Triples scored as _contradiction_ by the NLI model have their confidence reduced. Triples confirmed as _entailment_ get a confidence boost:

```yaml
verification:
  enabled: true
  backend: "nli"
  confidence_boost: 0.15    # Confirmed triples get +0.15
```

Use NLI verification when:
- You're using a weaker/smaller model prone to hallucination
- You want extra confidence in the trusted graph
- You're willing to spend a few extra seconds per document

---

## 9. Entity resolution — merge aliases

After writing, an embedding model merges entity aliases across the graph with `owl:sameAs`:

```yaml
entity_resolution:
  enabled: true
  backend: "embeddings"          # all-MiniLM-L6-v2 (no LLM cost)
  similarity_threshold: 0.94     # Cosine similarity to assert sameAs
  confidence_threshold: 0.80
```

This automatically discovers:
- `ex:Marie_Curie` ≡ `ex:Maria_Salomea_Sklodowska-Curie`
- `ex:Pierre_Curie` ≡ `ex:P_Curie`
- `ex:Radium_Institute` ≡ `ex:Institut_du_Radium`

The `similarity_threshold` of 0.94 is intentionally high to avoid false merges. Lower it only if you know your aliases are very similar in spelling:

```yaml
entity_resolution:
  similarity_threshold: 0.90    # More aggressive merging — watch for false positives
```

---

## 10. Few-shot examples — teach the LLM your style

```yaml
few_shot:
  enabled: true
  path: "examples/golden/biography-examples.yaml"
  max_examples: 3
  selection: "semantic"    # Pick the most relevant examples per fragment
```

The golden examples file contains hand-curated triple extractions from similar documents. The LLM uses them as a style guide: what your predicates look like, how you format dates, how you handle uncertain claims.

Creating a golden examples file:

```bash
# After a good run, export some triples you're happy with
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
# Manually curate into examples/golden/biography-examples.yaml
```

---

## Putting it together — the tuning workflow

A practical iteration loop for a new corpus:

### Step 1: Unconstrained discovery run

```yaml
# profile-v1-unconstrained.yaml
extraction_target:
  min_triples: 30
  max_triples: 100
# No allowed_predicates — see what emerges
```

```bash
riverbank reset-database --yes
riverbank ingest my-corpus/ --profile profile-v1-unconstrained.yaml
riverbank query "SELECT ?p (COUNT(*) AS ?n) WHERE { ?s ?p ?o } GROUP BY ?p ORDER BY DESC(?n) LIMIT 30"
```

### Step 2: Analyse predicate distribution

Look for:
- Synonymous predicates doing the same job (`coined_word`, `coined_term`) → pick one
- Inverted triples (subject/object swapped) → fix in `prompt_text`
- Invented metadata predicates (`named_element_1`) → block with `allowed_predicates`
- Markdown artifacts (`[French Academy]` as IRI) → already filtered by bracket-detection

### Step 3: Lock the vocabulary

```yaml
allowed_predicates:
  - "ex:born_in"
  - "ex:discovered"
  # ... your curated list
```

```bash
riverbank reset-database --yes
riverbank ingest my-corpus/ --profile profile-v2-constrained.yaml
```

### Step 4: Validate with SHACL (optional)

```bash
riverbank induce-schema \
  --graph http://riverbank.example/graph/trusted \
  --output ontology/induced.ttl
# Edit ontology/induced.ttl to add constraints
riverbank validate-shapes --shapes ontology/induced.ttl
```

### Step 5: Add competency questions

Once you're happy with the vocabulary, add SPARQL assertions the graph must pass on every re-ingest:

```yaml
competency_questions:
  - id: cq-birth-place
    description: "Marie Curie's birthplace is recorded"
    sparql: ASK { ex:Marie_Curie ex:born_in ?place . }
  - id: cq-nobelprize
    description: "Nobel Prize award is recorded"
    sparql: ASK { ex:Marie_Curie ex:received_award ?award . FILTER(CONTAINS(STR(?award), "Nobel")) }
```

These become regression tests:

```bash
pytest tests/golden/ -v
```

---

## Quick reference — quality knobs

| Goal | Profile field | Typical value |
|------|--------------|---------------|
| More triples | `extraction_target.min_triples` | 60–100 |
| Consistent predicates | `allowed_predicates` | domain-specific list |
| Strict cardinality | `predicate_constraints` | `max_cardinality: 1` |
| Looser evidence grounding | `citation_floor` | 30 |
| Stricter evidence grounding | `citation_floor` | 60 |
| All claims including inference | `extraction_focus` | `"comprehensive"` |
| Stated facts only | `extraction_focus` | `"facts_only"` |
| More recall, review later | `extraction_strategy.mode` | `"permissive"` |
| Better entity labels | `preprocessing.backend` | `"nlp"` or `"llm"` |
| Resolve pronouns | `preprocessing.coreference` | `"spacy"` |
| Halucination filter | `verification.backend` | `"nli"` |
| Alias merging | `entity_resolution.enabled` | `true` |
| Post-write shape check | `shacl_validation.enabled` | `true` |
