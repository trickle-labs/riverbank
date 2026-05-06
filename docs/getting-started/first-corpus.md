# First corpus

You ran `riverbank ingest examples/markdown-corpus/` and got a summary table. This page explains what actually happened at each stage and how to inspect the results.

## What the pipeline did

```mermaid
flowchart LR
    A[Discover files] --> B[Parse Markdown]
    B --> C[Fragment at headings]
    C --> D[Editorial policy gate]
    D --> E[Hash check — skip unchanged]
    E --> F[LLM extraction]
    F --> G[SHACL validation]
    G --> H[Write to pg_ripple]
```

### 1. File discovery

The `examples/markdown-corpus/` directory contains three Markdown files:

- `01_introduction.md` — what riverbank is and why it exists
- `02_concepts.md` — core concepts like fragments, profiles, and provenance
- `03_architecture.md` — the three PostgreSQL extensions riverbank depends on

The filesystem connector discovered each `.md` file and registered it as a `pgc:Source` in the `_riverbank.sources` table.

### 2. Parsing

The Markdown parser (`riverbank.parsers.markdown`) processed each file using `markdown-it-py`. It preserves heading structure, code blocks, and inline formatting.

### 3. Fragmentation

The heading fragmenter (`riverbank.fragmenters.heading`) split each document at heading boundaries. Each heading and its content became a `pgc:Fragment` — the unit of compilation. Fragments are stored in `_riverbank.fragments` with an `xxh3_128` content hash.

### 4. Editorial policy gate

Before extraction, each fragment was checked against the profile's editorial policy:

- **Minimum length:** fragments shorter than 50 characters are skipped (too short to contain useful knowledge)
- **Maximum length:** fragments longer than 8000 characters are flagged for manual review
- **Heading depth:** controlled by `min_heading_depth` (default 0 = all headings)

Fragments that fail the gate are recorded as skipped — they appear in the ingest summary under "Fragments skipped (gate)".

### 5. Hash-based deduplication

Each fragment's `xxh3_128` hash is compared to the stored hash from the previous run. If the hash matches, the fragment is skipped entirely — zero LLM calls for unchanged content. This is what makes re-ingesting an unchanged corpus effectively free.

### 6. LLM extraction

For fragments that pass the gate and hash check, the extractor produces structured triples. With the default `noop` extractor (used in CI and testing), synthetic triples are generated. With the `instructor` extractor, a real LLM call produces typed facts with confidence scores and evidence spans.

Each extracted fact carries:

- **Subject, predicate, object** — the RDF triple
- **Confidence score** — a float in `[0.0, 1.0]`
- **Evidence span** — exact character offsets pointing back to the source text

### 7. SHACL validation

Extracted triples are validated against the SHACL quality contract. Triples with confidence below the profile threshold (default 0.7) are routed to the `draft` named graph instead of the `trusted` graph.

### 8. Graph write

Valid triples are written to pg-ripple via `load_triples_with_confidence()`. Each triple carries:

- A `prov:wasDerivedFrom` edge to its source fragment
- A `pgc:confidence` score
- A `pgc:compiledAt` timestamp
- A `pgc:byProfile` reference to the compiler profile used

## Inspecting the results

### Query the compiled graph

```bash
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 20"
```

### Check provenance for a specific fact

```sparql
SELECT ?fragment ?source ?excerpt
WHERE {
  <entity:SomeFact> prov:wasDerivedFrom ?fragment .
  ?fragment pgc:fromSource ?source .
  <entity:SomeFact> pgc:evidenceSpan ?span .
}
```

### View the compilation run

```bash
riverbank runs --since 1h
```

### Run a quality report

```bash
riverbank lint --shacl-only
```

This calls `pg_ripple.shacl_score()` against the trusted graph and reports the numeric quality score.

## What's next?

- [Compile a policy corpus](../tutorials/compile-a-policy-corpus.md) — use the `docs-policy-v1` profile with competency questions
- [Compiler profiles](../concepts/compiler-profiles.md) — understand how profiles control extraction
- [Pipeline stages](../concepts/pipeline-stages.md) — deeper dive into each stage
