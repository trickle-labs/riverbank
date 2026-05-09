# How riverbank ingest works — a deep dive

This tutorial traces a single `riverbank ingest` call from a raw Markdown file to written triples. At every stage it explains what happens, what appears in the log, and what you can configure to change the outcome.

**What you'll learn:**

- The exact sequence of operations inside `riverbank ingest`
- What each pipeline stage produces and how they connect
- Which profile fields control each stage
- How to read the summary stats line to diagnose problems

## The document we'll trace

```bash
riverbank ingest ~/.riverbank/article_cache/marie_curie.md \
  --profile examples/profiles/docs-policy-v1-llm-biography.yaml \
  --set llm.model=gemma4:e2b-mlx-bf16
```

A ~40 KB Wikipedia biography. Single LLM call (`fragmenter: noop`). We'll follow one document all the way through.

---

## Pipeline overview

```
Raw file
   │
   ▼
① Source registration + parsing        → normalised text, heading positions
   │
   ▼
② Fragmentation                        → list of Fragment objects
   │
   ▼
③ Editorial policy gate                → skip or keep each fragment
   │
   ▼
④ Hash deduplication                   → skip unchanged fragments
   │
   ▼
⑤ Preprocessing                        → document summary + entity catalog
   │
   ▼
⑥ Prompt assembly                      → combined system prompt
   │
   ▼
⑦ LLM extraction                       → raw triples with confidence + evidence
   │
   ▼
⑧ Post-extraction quality filters      → evidence grounding, ontology filter,
   │                                      NLI verification
   ▼
⑨ Confidence routing                   → trusted / tentative / discard
   │
   ▼
⑩ Graph write + entity resolution      → pg-ripple named graphs
   │
   ▼
⑪ SHACL validation (optional)          → shape conformance report
```

---

## Stage 1 — Source registration and parsing

The file is registered in `_riverbank.sources`. Its IRI is derived from the path:

```
http://riverbank.example/source/marie_curie_md
```

The **parser** converts the raw format to a normalised internal representation. The default parser for `.md` files is `markdown`, which uses `markdown-it-py` to:

- Preserve heading positions (byte offsets of every `#`, `##`, etc.)
- Strip HTML comment markers and wiki syntax markers
- Record the detected language code

**What you can configure here:**

| Goal | Configuration |
|------|--------------|
| Parse PDF/DOCX instead of Markdown | `parser: docling` in the profile |
| Add a custom format | See [Add a custom parser](add-a-custom-parser.md) |

---

## Stage 2 — Fragmentation

The fragmenter divides the parsed document into **fragments** — the compilation units that are individually tracked and hashed.

```yaml
fragmenter: noop           # Treat whole document as one fragment
# OR
fragmenter: heading        # One fragment per heading section (default)
```

With `fragmenter: noop` (aliased to `direct` in v0.15.1+), the entire document becomes one fragment. This is the right choice for:

- Medium documents (< ~50 k characters / 15 k tokens)
- Documents where cross-section context matters (biographies, papers)
- When you want consistent predicates — no vocabulary drift across fragments

With `fragmenter: heading`, each `##` section becomes its own fragment. Unchanged sections are skipped on re-ingest, so only edited sections cost LLM calls.

Each fragment carries:
- A stable `fragment_key` (e.g., the heading path `Early life / Childhood`)
- An `xxh3_128` content hash for change detection
- Character offsets so the extractor can validate evidence spans

**What you can configure here:**

| Goal | Configuration |
|------|--------------|
| Single-call extraction | `fragmenter: noop` |
| Incremental (re-ingest only changed sections) | `fragmenter: heading` |
| Semantic split points (not heading-based) | `fragmenter: semantic` |
| LLM-driven splitting | `fragmenter: llm_statement` |
| Cap document size for noop | `direct_extraction.max_doc_chars: 200000` |

---

## Stage 3 — Editorial policy gate

Before any LLM call, each fragment passes through a set of rules that decide whether to skip it:

```yaml
editorial_policy:
  min_fragment_length: 50       # Characters — skip stubs/empty sections
  max_fragment_length: 500000   # Characters — flag fragments too large for context window
  min_heading_depth: 0          # 0 = all headings; 2 = skip top-level H1
  confidence_threshold: 0.7     # Below this → tentative/discard, not trusted graph
  allowed_languages:
    - en
```

For the Marie Curie biography with `fragmenter: noop`, there is one fragment of ~40 KB, which passes all rules. For heading-fragmented documents, common skip reasons are:

- "See also" sections (too short + no useful content)
- "References" sections (short stubs of citation markup)
- Non-English sections flagged by language detection

Skipped fragments appear in the run stats as `fragments_skipped_policy`.

**What you can configure here:**

| Goal | Configuration |
|------|--------------|
| Skip short noise sections | Lower `min_fragment_length` |
| Accept large documents | Raise `max_fragment_length` |
| Skip top-level title headings | Set `min_heading_depth: 2` |
| Filter non-English content | Add language codes to `allowed_languages` |

---

## Stage 4 — Hash deduplication

Each fragment's current `xxh3_128` hash is compared to the stored hash from the previous ingest. If the hashes match, the fragment is skipped entirely — no LLM call, no processing cost.

On a first run (`riverbank reset-database --yes` followed by `ingest`) all fragments are new. On subsequent runs, only changed content triggers extraction.

This is the core of **incremental compilation**: re-ingesting a 1 000-document corpus where 3 documents changed produces exactly 3 fragments' worth of LLM calls.

Force re-extraction even for unchanged content:

```bash
riverbank ingest ... --force
```

---

## Stage 5 — Preprocessing

Before building the extraction prompt, a preprocessing pass scans the document to produce two pieces of supporting context:

1. **Document summary** — a 3–5 sentence abstract of the document's topic and scope
2. **Entity catalog** — a list of named entities (persons, organisations, locations, dates) detected in the document, formatted as candidate IRI labels

This context is injected into the extraction prompt so the LLM:
- Knows what the document is about before extracting triples
- Has consistent entity labels to use as subject/object IRIs (reducing `ex:Marie_Curie` vs. `ex:MarieCurie` drift)

```yaml
preprocessing:
  enabled: true
  backend: "nlp"     # sumy LexRank + spaCy NER (no LLM cost — fast)
  # OR
  backend: "llm"     # LLM-driven summary + coreference (better, but costs a call)
  max_tokens_for_preprocessing: 4000
```

**Log line you'll see:**

```
Preprocessing: 12 entities detected, summary injected (384 tokens)
```

**What you can configure here:**

| Goal | Configuration |
|------|--------------|
| Disable preprocessing (speed) | `preprocessing.enabled: false` |
| Higher-quality entity catalog | `preprocessing.backend: "llm"` |
| Token budget for preprocessing | `preprocessing.max_tokens_for_preprocessing: 4000` |
| Resolve coreference ("she" → "Marie Curie") | `preprocessing.coreference: "llm"` or `"spacy"` |

---

## Stage 6 — Prompt assembly

The extractor assembles the final prompt from several building blocks, combined in this order:

```
[Vocabulary constraints block]         ← from allowed_predicates
[Extraction focus block]               ← from extraction_focus
[Permissive-mode guidance block]       ← from extraction_strategy.mode
[Extraction volume requirement block]  ← from extraction_target
[Few-shot examples block]              ← from few_shot
[Base prompt_text]                     ← from profile
[Known graph context]                  ← triples already in the graph, to avoid repeats
[Document summary + entity catalog]    ← from preprocessing
[Document text]                        ← the fragment itself
```

Each block is only injected when the corresponding feature is enabled. A typical biography profile produces a prompt of ~6 000–10 000 tokens.

**What you can configure here:**

| Block | Configuration |
|-------|--------------|
| Which predicates the LLM may use | `allowed_predicates: [...]` |
| Precision vs. recall trade-off | `extraction_focus: "high_precision"` / `"facts_only"` / `"comprehensive"` |
| Target triple count | `extraction_strategy.extraction_target.min_triples` / `max_triples` |
| Custom few-shot examples | `few_shot.enabled: true`, `few_shot.path: examples/golden/...` |
| Custom prompt | `prompt_text: |` |

See [Tune extraction quality](tune-extraction-quality.md) for the full guide to each block.

---

## Stage 7 — LLM extraction

The assembled prompt is sent to the configured model. The response is parsed into a list of **candidate triples**, each with:

| Field | Description |
|-------|-------------|
| `subject` | Prefixed IRI (e.g., `ex:Marie_Curie`) |
| `predicate` | Prefixed IRI (e.g., `ex:born_in`) |
| `object_value` | IRI or literal (e.g., `ex:Warsaw` or `"1867-11-07"`) |
| `confidence` | Float 0.0–1.0 reported by the LLM |
| `evidence.start_char` | Character offset of the supporting text in the source |
| `evidence.end_char` | End character offset |
| `evidence.excerpt` | Verbatim quote from the source |

**Log line you'll see:**

```
Extracted 82 candidate triples from 1 fragment(s)
```

**Ollama-specific: num_predict budget**

When `extraction_target` is set, the extractor automatically raises Ollama's `num_predict` (output token cap) to match the requested volume:

```
num_predict = max(4096, max_triples × 160 + 512)
```

Without this, the default 2 048-token cap silently truncates output at ~12–15 triples.

---

## Stage 8 — Post-extraction quality filters

Candidate triples pass through three sequential filters before any triple is routed to a graph.

### 8a. Evidence grounding (citation similarity)

For each triple, the verbatim `evidence.excerpt` is searched in the source text using `rapidfuzz.partial_ratio` — a fuzzy sliding-window match that tolerates minor LLM paraphrasing (stripped markdown, em-dash variants, decimal-space differences).

```
similarity score = rapidfuzz.partial_ratio(excerpt, source_text)   [0–100]
```

**Two-tier outcome:**

| Score | Outcome |
|-------|---------|
| Below `citation_floor` (default 40) | Hard reject — excerpt is absent or fabricated |
| At or above floor | Soft penalty: `conf_final = conf_llm × (sim / 100)` |

The soft penalty means a triple with 80% LLM confidence but only 60% citation similarity gets `conf_final = 0.48` — routed to tentative rather than trusted, not discarded.

**Log lines you'll see:**

```
Rejecting triple — no excerpt provided: ex:Pierre_Curie ex:discovered "radioactivity phenomena"
Rejecting triple — citation similarity 28 < floor 40: ex:Marie_Curie ex:born_in ex:Paris
```

**What you can configure here:**

```yaml
extraction_strategy:
  citation_floor: 40     # Hard rejection threshold (0 = accept all, 100 = exact match only)
```

### 8b. Ontology filter (predicate allowlist)

If `allowed_predicates` is non-empty, any triple whose predicate is not in the list is rejected before writing.

```yaml
allowed_predicates:
  - "ex:born_in"
  - "ex:discovered"
  - "ex:received_award"
```

The match is case-insensitive on the local name, and handles `ex:born_in`, `born_in`, and `<http://riverbank.example/entity/born_in>` as equivalent.

**Log line you'll see:**

```
OntologyFilter: rejecting triple (predicate not in allowlist): ex:coined_word
```

### 8c. NLI verification

When `verification.backend: "nli"` is enabled, a cross-encoder model (`cross-encoder/nli-distilroberta-base` by default, running locally) checks whether each extracted claim is entailed by the source text.

Triples that the NLI model scores as _contradiction_ or _neutral_ below a threshold are either discarded or have their confidence reduced. This catches hallucinations that passed the fuzzy citation check.

```yaml
verification:
  enabled: true
  backend: "nli"
```

---

## Stage 9 — Confidence routing

After all quality filters, the final `conf_final` for each triple determines which named graph it enters:

| `conf_final` range | Destination |
|--------------------|-------------|
| ≥ `trusted_threshold` (default 0.75) | `http://riverbank.example/graph/trusted` |
| ≥ `tentative_threshold` (default 0.35) | `http://riverbank.example/graph/tentative` |
| < `tentative_threshold` | Discarded (logged as `triple_discarded_confidence`) |

**Log lines you'll see:**

```
Trusted: 63    Tentative: 16    Written: 79    Rejected (no excerpt): 3
```

**What you can configure here:**

```yaml
extraction_strategy:
  confidence_routing:
    trusted_threshold: 0.75
    tentative_threshold: 0.35
```

---

## Stage 10 — Graph write and entity resolution

Valid triples are written to pg-ripple via `load_triples_with_confidence()`. Each triple carries provenance metadata:

- `prov:wasDerivedFrom` → source fragment IRI
- `pgc:confidence` → final confidence score
- `pgc:compiledAt` → ingest timestamp
- `pgc:byProfile` → compiler profile reference

**Entity resolution** runs after the write. An embedding model computes cosine similarity between entity IRIs across the graph. Pairs above `similarity_threshold` get an `owl:sameAs` assertion:

```yaml
entity_resolution:
  enabled: true
  backend: "embeddings"
  similarity_threshold: 0.94    # high to avoid Pierre/Marie false match
  confidence_threshold: 0.80
```

This automatically merges `ex:Marie_Curie` ≡ `ex:Maria_Salomea_Sklodowska-Curie` without a manual mapping file.

---

## Stage 11 — SHACL validation (optional)

After writing, the named graph can be validated against a SHACL shapes file:

```yaml
shacl_validation:
  enabled: true
  shapes_path: ontology/my-shapes.ttl
  reduce_confidence: true
  confidence_penalty: 0.15
```

Or on demand:

```bash
riverbank validate-shapes \
  --graph http://riverbank.example/graph/trusted \
  --shapes ontology/my-shapes.ttl
```

Violations are reported as structured diagnostics. With `reduce_confidence: true`, triples whose subject node violates a shape have their confidence reduced by `confidence_penalty`.

---

## Reading the summary stats

A typical run ends with a line like:

```
Extracted 82 | Rejected (no excerpt) 3 | Trusted 63 | Tentative 16 | Written 79
```

| Number | What it means |
|--------|---------------|
| Extracted 82 | Raw candidates from the LLM |
| Rejected (no excerpt) 3 | LLM omitted the evidence field — hard reject |
| Trusted 63 | `conf_final ≥ 0.75`, written to `graph/trusted` |
| Tentative 16 | `0.35 ≤ conf_final < 0.75`, written to `graph/tentative` |
| Written 79 | Total triples written (trusted + tentative) |

### Common diagnosis patterns

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Extracted 0 | LLM returned empty / bad JSON | Check `RIVERBANK_DEBUG_LLM` env var |
| Extracted 12, Written 12 | Ollama `num_predict` too low (2 048) | Set `extraction_target` |
| Written 0, many "no excerpt" | LLM dropped excerpts under volume pressure | Already mitigated by the CRITICAL prompt warning; try lowering `min_triples` |
| Many low confidence, few trusted | High citation penalty from paraphrased excerpts | Lower `citation_floor` to 30 |
| Predicate not in allowlist (many) | LLM used non-listed predicates | Broaden `allowed_predicates` or unset it |

---

## Next steps

- [Tune extraction quality](tune-extraction-quality.md) — hands-on guide to every quality lever
- [Write a compiler profile](write-a-compiler-profile.md) — profile field reference
- [Run incremental recompile](run-incremental-recompile.md) — change detection and re-ingest
- [Compiler profile schema](../reference/compiler-profile-schema.md) — exhaustive field documentation
