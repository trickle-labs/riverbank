# Preprocessing

Before LLM extraction runs on individual fragments, riverbank can optionally run a **preprocessing pass** over each full document. Preprocessing makes one or two cheap LLM calls per document — not per fragment — and uses the results to enrich every extraction call in that document.

The feature is opt-in and controlled entirely through the compiler profile.

---

## Why preprocessing?

The standard pipeline sends each fragment to the extraction LLM cold: no context about the document's domain, no canonical entity names, no constraints on which predicates to use. This produces:

- **Terminology drift** — `"Dataset"`, `"data set"`, and `"datasets"` become three separate nodes
- **Predicate invention** — the LLM uses natural-language predicates like `"is a means of storage inside Sesam"` instead of `schema:isPartOf`
- **Weak grounding** — the LLM must infer the domain from a single fragment, often missing the point

Preprocessing addresses all three by giving the extraction LLM:

1. **A document summary** — 2-3 sentences of domain context injected into every fragment prompt
2. **An entity catalog** — canonical names and aliases, so all fragments refer to the same IRIs

---

## Pipeline position

```
MarkdownParser.parse()
        │
        ▼
╔══════════════════════════════════════════╗
║  Distillation Pass (optional, v0.15.2)   ║
║  Reduces document size pre-fragmentation ║
╚══════════════════════════════════════════╝
        │
        ▼
╔══════════════════════════════════════════╗
║  LLM Preprocessing Pass (once/document) ║
║  1. Document summary                     ║
║  2. Entity catalog                       ║
╚══════════════════════════════════════════╝
        │
        ▼
HeadingFragmenter.fragment()     → fragments
        │
        ▼
IngestGate.check()               → accept/reject
        │
        ▼
InstructorExtractor.extract()    → triples
  (uses enriched prompt with
   summary + entity catalog)
```

Preprocessing runs **before** fragmentation and **once per document**. The cost is amortised across all fragments in that document.

> **Distillation vs preprocessing:** Distillation (v0.15.2) reduces the *input document* before fragmentation — it removes non-extractable sections. Preprocessing enriches the *extraction prompt* with a summary and entity catalog. Both run before fragmentation and are complementary. See [Use document distillation](../how-to/use-document-distillation.md).

---

## Enabling preprocessing

Add a `preprocessing` block to your compiler profile:

```yaml
preprocessing:
  enabled: true
  strategies:
    - document_summary   # 2-3 sentence domain context
    - entity_catalog     # canonical entity names + aliases
  max_entities: 50
  predefined_predicates:
    - "rdf:type"
    - "rdfs:label"
    - "schema:isPartOf"
    - "schema:hasPart"
    - "dcterms:description"
    - "schema:relatedTo"
```

See `examples/profiles/docs-policy-v1-preprocessed.yaml` for a complete example.

---

## Strategies

### `document_summary`

Sends the first 8 000 characters of the document to the LLM and asks for a 2-3 sentence summary focused on domain, main concepts, and purpose.

The summary is prepended to every fragment extraction call as `DOCUMENT CONTEXT`.

**Token cost:** ~500 prompt + ~100 completion per document.

### `entity_catalog`

Sends the first 12 000 characters of the document to the LLM and asks for a list of canonical entity entries. Each entry has:

| Field | Description |
|-------|-------------|
| `canonical_name` | lowercase-hyphenated IRI slug, e.g. `sesam-dataset` |
| `label` | human-readable name |
| `entity_type` | one of `Concept`, `System`, `Component`, `Process`, `Role`, `Configuration`, `Event` |
| `aliases` | surface variants found in the text |

Aliases are validated against the source text — any alias not literally present in the document is discarded before the catalog is injected into extraction prompts.

The catalog is injected as `ENTITY CATALOG` into every fragment extraction call. The extraction LLM is instructed to map all surface variants to the canonical `ex:` IRI.

**Token cost:** ~1 000 prompt + ~500 completion per document (varies with document size and entity count).

---

## Predefined predicates

When `predefined_predicates` is set in the profile, they are injected into the extraction prompt as `ALLOWED PREDICATES`. The extraction LLM is instructed to use only these predicates, falling back to `ex:relatedTo` (confidence ≤ 0.6) for uncategorized relationships.

This eliminates ad-hoc natural-language predicates and forces alignment with existing vocabularies (`schema.org`, Dublin Core, SKOS).

---

## Enriched prompt template

The preprocessing output is assembled into an enriched prompt that replaces the profile's `prompt_text` for all fragments in that document:

```
You are a knowledge graph compiler.

DOCUMENT CONTEXT:
<2-3 sentence summary>

ENTITY CATALOG (map all mentions to these canonical names):
  - ex:sesam-pipe [Component] label="Pipe" (aliases: 'pipes')
  - ex:sesam-dataset [Concept] label="Dataset" (aliases: 'data set', 'datasets')

ALLOWED PREDICATES (use only these):
  - rdf:type
  - rdfs:label
  - schema:isPartOf
  - ex:relatedTo  (fallback, confidence ≤ 0.6)

<original prompt_text from profile, with generic intro stripped>
```

---

## Cost

For a typical 10-document corpus with 50 fragments:

| Phase | Calls | Tokens (est.) |
|-------|-------|---------------|
| Preprocessing (summary) | 10 | 6 000 |
| Preprocessing (entity catalog) | 10 | 15 000 |
| Extraction (with enriched prompt) | 50 | +10 000 overhead |
| **Total overhead** | +20 calls | **~31 000 tokens** |

At GPT-4o pricing, 31k tokens costs ~$0.01. For Ollama (local), cost is zero.

---

## Statistics

After an ingest run with preprocessing enabled, the summary table shows additional rows:

```
Preprocessing calls              10
Preprocessing prompt tokens    5 840
Preprocessing completion tokens  480
```

---

## Graceful fallback

If the preprocessing LLM call fails (network error, model timeout, JSON parse failure), the preprocessor returns `None` and extraction continues with the unmodified `prompt_text` from the profile. No fragments are lost.

This makes preprocessing safe to enable on production corpora: worst case is the same extraction quality as without preprocessing.

---

## Implementation

- **`src/riverbank/preprocessors/__init__.py`** — `DocumentPreprocessor`, `PreprocessingResult`, `EntityCatalogEntry`
- **`src/riverbank/pipeline/__init__.py`** — preprocessing integrated into `_process_source()`, called once per document before the fragment loop
- **`tests/unit/test_preprocessor.py`** — unit tests (all LLM calls mocked)
- **`examples/profiles/docs-policy-v1-preprocessed.yaml`** — ready-to-use example profile

---

## Roadmap

Phase 1 (implemented) covers document-level preprocessing. See [plans/pre-processing.md](../../plans/pre-processing.md) for the full roadmap, including:

- **Phase 2** — hierarchical corpus clustering (corpus → cluster → document context hierarchy)
- **Post-extraction** — embedding-based entity deduplication, self-critique verification, OWL inference
