# Pipeline stages

The riverbank compilation pipeline transforms raw documents into governed knowledge through a sequence of well-defined stages.

```mermaid
flowchart TD
    A[Source discovery] --> B[Parsing]
    B --> C[Fragmentation]
    C --> D[Editorial policy gate]
    D --> E[Hash deduplication]
    E --> F[Vocabulary pass<br>optional]
    F --> G[LLM extraction]
    G --> H[SHACL validation]
    H --> I[Graph write]
    I --> J[Artifact dependency<br>registration]
```

## 1. Source discovery

The configured connector discovers documents. The filesystem connector walks a directory tree; custom connectors can pull from APIs, S3, or message queues.

Each discovered file is registered as a `pgc:Source` in `_riverbank.sources` with an IRI, content hash, and optional tenant ID.

## 2. Parsing

The parser converts the raw format into a normalized text representation with heading positions. Parsers are pluggable:

- `markdown` — uses `markdown-it-py`, preserves heading structure
- `docling` — handles PDF, DOCX, HTML via the Docling library

## 3. Fragmentation

The fragmenter splits parsed content into compilation units. The heading fragmenter creates one fragment per heading section. Each fragment gets:

- A stable `fragment_key` (heading path)
- An `xxh3_128` content hash for change detection
- Character offsets for evidence span validation

## 4. Editorial policy gate

Before LLM extraction (which costs money), the editorial policy filters fragments:

- **`min_fragment_length`** — skip fragments too short to contain useful knowledge
- **`max_fragment_length`** — flag fragments that exceed context window limits
- **`min_heading_depth`** — skip top-level headings that are just titles
- **`allowed_languages`** — skip content in unsupported languages

Skipped fragments are recorded in the run stats, not silently dropped.

## 5. Hash deduplication

Each fragment's `xxh3_128` hash is compared to the stored hash from the previous run. Unchanged fragments are skipped entirely — zero LLM calls for stable content.

This is the core of incremental compilation: re-ingesting a 1000-document corpus where 3 documents changed produces only 3 fragments worth of LLM calls.

## 6. Vocabulary pass (optional)

When `run_mode_sequence` includes `vocabulary`, a first pass extracts `skos:Concept` triples into the `<vocab>` named graph. This establishes canonical entity IRIs before the full extraction pass, so that relationship extraction can reference consistent entities rather than creating duplicates.

## 7. LLM extraction

The extractor sends the fragment text and profile prompt to the configured LLM and parses the response into structured triples. Each triple carries:

- **Subject, predicate, object** — the RDF statement
- **Confidence** — a float in `[0.0, 1.0]`
- **EvidenceSpan** — exact character offsets + verbatim excerpt from the source

The `EvidenceSpan` contract is enforced: the excerpt must match the text at the declared offset. Fabricated citations are rejected.

## 8. SHACL validation

Extracted triples are validated against SHACL shapes:

- Triples meeting the confidence threshold → `trusted` named graph
- Triples below threshold → `draft` named graph (pending review)
- Triples violating shape constraints → rejected with a `pgc:LintFinding`

## 9. Graph write

Valid triples are written to pg-ripple via `load_triples_with_confidence()`. Each carries:

- `prov:wasDerivedFrom` → source fragment
- `pgc:confidence` → extraction confidence
- `pgc:compiledAt` → timestamp
- `pgc:byProfile` → compiler profile reference

## 10. Artifact dependency registration

The artifact dependency graph (`_riverbank.artifact_deps`) records which compiled facts depend on which fragments. This enables:

- **Incremental invalidation** — when a fragment changes, exactly the right facts are recompiled
- **`riverbank explain`** — trace any fact back to its sources
- **Staleness detection** — rendered pages know when their source facts changed
