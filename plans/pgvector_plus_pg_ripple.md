# pgvector + pg_ripple: Integration Deep Dive

> Research date: 2026-05-07 (updated with pg_trickle v0.37–v0.49 embedding features)  
> Status: Research / Planning

---

## 1. What pgvector Is

[pgvector](https://github.com/pgvector/pgvector) (current stable: v0.8.2) is an open-source PostgreSQL extension that adds first-class vector similarity search to Postgres. Instead of exporting data to a dedicated vector store (Pinecone, Weaviate, Qdrant, Milvus), embeddings live in the same database as all other structured data, inheriting ACID guarantees, WAL replication, point-in-time recovery, and all standard Postgres indexing and join capabilities.

### 1.1 Vector Types

| Type | Storage | Max Dimensions | Use Case |
|------|---------|---------------|----------|
| `vector(n)` | 4 bytes × n + 8 | 16,000 | General purpose (all-MiniLM-L6-v2: 384) |
| `halfvec(n)` | 2 bytes × n + 8 | 16,000 | Memory-efficient; nomic-embed-text: 768 |
| `bit(n)` | n/8 + 8 bytes | 64,000 | Binary quantized; fast pre-filter |
| `sparsevec(n)` | 8 bytes × nnz + 16 | 16,000 non-zero | Sparse embeddings (SPLADE, BM25 encodings) |

### 1.2 Distance Operators

| Operator | Metric | Typical Use |
|----------|--------|-------------|
| `<->` | L2 / Euclidean | General geometric distance |
| `<=>` | Cosine distance | Most embedding models (normalize first) |
| `<#>` | Negative inner product | Pre-normalized vectors (fastest) |
| `<+>` | L1 / Taxicab | Robust outlier-tolerant similarity |
| `<~>` | Hamming | Binary quantized vectors |
| `<%>` | Jaccard | Binary set similarity |

### 1.3 Index Types

**HNSW (Hierarchical Navigable Small World)**
- Multilayer graph structure
- Best query performance (speed vs. recall tradeoff)
- Slower build; can build on empty table (no training phase)
- Key parameters:
  - `m` — connections per layer (default 16; higher = better recall, more memory)
  - `ef_construction` — candidate list size during build (default 64)
  - `hnsw.ef_search` — candidate list size during query (default 40; tune per query)
- Supports iterative index scans (v0.8.0+) for filtered queries

**IVFFlat (Inverted File Index)**
- Divides vectors into lists (Voronoi cells), searches nearest cells
- Faster build, less memory than HNSW, lower recall
- Requires data to exist before building (k-means training step)
- Key parameters:
  - `lists` — number of cells; start with `rows/1000` up to 1M rows, `sqrt(rows)` above
  - `ivfflat.probes` — cells to search at query time (default 1; start with `sqrt(lists)`)

**Choosing between them for riverbank:**
- HNSW is recommended for riverbank's entity embedding use case because:
  - Entity counts grow incrementally (no full rebuild needed)
  - Entity lookup is latency-sensitive (query-time users)
  - Better recall is worth the memory cost at typical corpus sizes (<1M entities)

### 1.4 Key SQL Patterns

```sql
-- Nearest-neighbor lookup (index-friendly)
SELECT entity_iri, embedding <=> '[0.1, 0.2, ...]'::vector AS distance
FROM pg_ripple.entity_embeddings
ORDER BY distance
LIMIT 10;

-- Similarity threshold filter (use iterative scan for filtered queries)
SET hnsw.iterative_scan = strict_order;
SELECT entity_iri
FROM pg_ripple.entity_embeddings
WHERE category = 'trusted'
ORDER BY embedding <=> $1
LIMIT 20;

-- Centroid of a cluster (aggregate)
SELECT AVG(embedding) AS centroid FROM pg_ripple.entity_embeddings
WHERE cluster_id = 42;

-- Hybrid: binary pre-filter + full-precision re-rank (2-stage ANN)
SELECT * FROM (
  SELECT entity_iri
  FROM pg_ripple.entity_embeddings
  ORDER BY binary_quantize(embedding)::bit(384) <~> binary_quantize($1)::bit(384)
  LIMIT 100
) pre
ORDER BY embedding <=> $1
LIMIT 10;
```

---

## 2. pg_ripple's Native pgvector Integration

pg_ripple ships with pgvector as a first-class dependency. The integration is deep — pgvector is not an optional add-on but a core part of pg_ripple's storage and retrieval architecture.

### 2.1 Functions riverbank Already Calls

| pg_ripple Function | What it Does | riverbank Usage |
|---|---|---|
| `pg_ripple.store_embedding(iri, vector)` | Writes an entity embedding into the entity-cluster table | `embeddings/__init__.py: store_entity_embedding()` |
| `pg_ripple.rag_retrieve(query_text, graph, limit)` | Vector-similarity retrieval over compiled graph using pgvector | `docs/reference/sparql-helpers.md`; available for query expansion |
| `pg_ripple.suggest_sameas(iri [, graph])` | Vector-based `owl:sameAs` candidates | `catalog/graph.py: suggest_sameas()`, `fuzzy/__init__.py` |
| `pg_ripple.pagerank_find_duplicates(graph)` | Centrality-guided entity dedup (uses PageRank + vector similarity) | `catalog/graph.py: find_duplicate_entities()` |

### 2.2 pg_trickle's Incremental pgvector Feature Set (v0.37–v0.49)

pg_trickle is already a core dependency of riverbank (auto-created by `catalog/migrations/versions/0004_create_extensions.py`). Across versions v0.37–v0.48 it has built a comprehensive suite of pgvector-specific capabilities that go well beyond the basic centroid IVM mentioned in the codebase. v0.49.0 is a test infrastructure and scheduler decomposition release with no new vector features.

#### v0.37.0 — pgVector Incremental Aggregates (F4)

The foundation: stream tables can incrementally maintain `avg(embedding)` and `sum(embedding)` over `vector`, `halfvec`, and `sparsevec` columns. The DVM planner detects vector-typed aggregate arguments at plan time and reclassifies them to use pgvector-native differential operators (`VectorAvg`, `VectorSum`) that maintain a running `(count, sum_vector)` auxiliary state — no full scan on each INSERT.

```sql
-- Enable incremental vector aggregates (session-level opt-in)
SET pg_trickle.enable_vector_agg = on;

-- This stream table is maintained incrementally — no full scan on INSERT
SELECT pgtrickle.create_stream_table(
    'cluster_centroids',
    'SELECT cluster_id, avg(embedding)::vector AS centroid
     FROM pg_ripple.entity_embeddings GROUP BY cluster_id',
    schedule => '5s'
);
```

**Important:** Distance operators (`<=>`, `<->`, `<#>`) in WHERE clauses trigger automatic full-refresh fallback because they are non-monotone. The planner emits a WARNING so operators know the mode downgrade occurred.

This is the feature already referenced in riverbank's `embeddings/__init__.py` module docstring: *"Entity-cluster centroid views are maintained as `avg(embedding)::vector` in pg_trickle stream tables (pgVector IVM, v0.37+)."*

#### v0.47.0 — Embedding Pipeline Infrastructure & ANN Maintenance (VP-1–VP-4)

Three capabilities directly useful for managing the entity embedding corpus:

**Post-refresh actions (VP-1):** Specify what happens after each successful refresh cycle:

| Action | Behaviour |
|--------|-----------|
| `'none'` | Default; no post-refresh step |
| `'analyze'` | Runs ANALYZE to keep planner statistics current |
| `'reindex'` | Always rebuilds the HNSW/IVFFlat index |
| `'reindex_if_drift'` | Rebuilds only when ≥ `reindex_drift_threshold` fraction of rows have changed |

```sql
-- Configure drift-aware reindex for an embedding stream table
SELECT pgtrickle.alter_stream_table(
    'cluster_centroids',
    post_refresh_action     => 'reindex_if_drift',
    reindex_drift_threshold => 0.20  -- reindex when >20% of rows changed
);
```

**Drift detection (VP-2):** Two new catalog columns on `pgtrickle.pgt_stream_tables`:
- `rows_changed_since_last_reindex` — running count reset after each REINDEX
- `last_reindex_at` — timestamp of last REINDEX

**`pgtrickle.vector_status()` monitoring view (VP-3):**

```sql
SELECT name, post_refresh_action, drift_pct, embedding_lag, last_reindex_at,
       rows_changed_since_last_reindex
FROM pgtrickle.vector_status();
```

Returns embedding lag, ANN index age, drift percentage, and estimated row count — one row per stream table with a non-`none` post_refresh_action. Essential for production observability of the entity embedding corpus.

**pgvector RAG Cookbook (VP-4):** `docs/tutorials/PGVECTOR_RAG_COOKBOOK.md` — copy-paste patterns for pre-computed embeddings, tenant-isolated corpus with RLS, drift-aware HNSW reindexing, centroid maintenance, and operational sizing.

#### v0.48.0 — Complete Embedding Programme: Hybrid Search, Sparse Vectors & Ergonomic API

The most significant release for pgvector in pg_trickle. Five major capabilities:

**VA-1: `embedding_stream_table()` — One-Line Embedding Pipeline**

Creates a stream table, HNSW or IVFFlat index, and post-refresh drift monitoring in a single SQL call:

```sql
SELECT pgtrickle.embedding_stream_table(
    name             => 'riverbank_entity_embeddings',
    source_table     => 'pg_ripple.entity_embeddings',
    vector_column    => 'embedding',
    extra_columns    => ARRAY['entity_iri', 'cluster_id'],
    refresh_interval => '5s',
    index_type       => 'hnsw',
    dry_run          => false  -- set true to preview SQL without executing
);
```

This is the ergonomic front-end for the VP-1/VP-2 infrastructure: it generates the stream table DDL, creates the chosen index type, and configures `reindex_if_drift` monitoring. The `dry_run` mode is useful for validating the generated SQL in CI.

**VH-1: Sparse and Half-Precision Vector Aggregates**

`avg(halfvec_col)` and `avg(sparsevec_col)` stream tables now produce output columns typed `halfvec(N)` and `sparsevec(N)` respectively — no silent coercion to `vector`. The DVM engine correctly propagates vector type names through `extract_vector_agg_output_dims`. Relevant when riverbank adopts `halfvec` storage (Strategy 5) or SPLADE sparse embeddings.

**VH-2: Reactive Distance Subscriptions**

After each refresh cycle, the scheduler fires NOTIFY on a registered channel whenever rows in the storage table satisfy a distance predicate. This enables push-based workflows instead of polling:

```sql
-- Fire 'potential_duplicates' NOTIFY after each refresh when
-- any embedding pair has cosine distance < 0.08
SELECT pgtrickle.subscribe_distance(
    stream_table  => 'riverbank_entity_embeddings',
    channel       => 'potential_duplicates',
    vector_column => 'embedding',
    query_vector  => NULL,  -- NULL = all-pairs monitoring
    op            => '<=>',
    threshold     => 0.08
);

-- Inspect and clean up subscriptions
SELECT * FROM pgtrickle.list_distance_subscriptions('riverbank_entity_embeddings');
SELECT pgtrickle.unsubscribe_distance('riverbank_entity_embeddings', 'potential_duplicates');
```

**VA-4: Embedding Outbox**

Extends pg_trickle's outbox (via pg_tide) with an `event_type: "embedding_change"` event that includes the vector column name in event headers. Downstream systems — ML retraining pipelines, external vector stores — can consume via pg_tide's consumer group API:

```sql
SELECT pgtrickle.attach_embedding_outbox(
    stream_table          => 'riverbank_entity_embeddings',
    vector_column         => 'embedding',
    retention_hours       => 24,
    inline_threshold_rows => 1000
);
```

**VH-3 & VA-5: Cookbooks Added**
- `docs/tutorials/HYBRID_SEARCH_PATTERNS.md` — three hybrid search patterns (BM25 + vector + graph) with worked SQL
- `docs/tutorials/VECTOR_RAG_STARTER.md` — quick-start RAG pipeline guide
- `docs/research/KNN_GRAPH_TRADEOFFS.md` — storage/latency/maintenance analysis for materialised k-NN graphs
- `docs/tutorials/PER_TENANT_ANN_PATTERNS.md` — per-tenant ANN with RLS and security checklist

#### v0.49.0 — Test Infrastructure Hardening & Scheduler Decomposition

v0.49.0 has no new vector features. It focuses on test infrastructure: concurrency test synchronization overhaul (replacing `tokio::time::sleep` with `pg_stat_activity`-polling), new fuzz targets for merge SQL codegen and row identity, and scheduler module decomposition (`src/scheduler/mod.rs` split into `dispatch.rs`, `scheduler_loop.rs`, `watermark.rs`). No API or behaviour changes for embedding workloads.

### 2.3 `rag_retrieve()` — End-to-End Vector RAG

`pg_ripple.rag_retrieve(query_text, named_graph, limit)` performs:
1. Embed `query_text` inside PostgreSQL (no round-trip to Python)
2. HNSW approximate nearest neighbor against entity embeddings
3. Graph walk from matched entities to gather related facts
4. Return facts formatted for LLM prompt injection

This means riverbank can expose a complete semantic query path without writing a single line of embedding or retrieval code beyond a SPARQL call:

```sql
SELECT * FROM pg_ripple.rag_retrieve(
  'What does Ariadne produce?',
  'http://riverbank.example/graph/trusted',
  5
);
```

### 2.4 Vector Index Configuration in pg_ripple

pg_ripple creates pgvector indexes during extension initialization. The exact index type (HNSW vs IVFFlat) and parameters are configurable. For riverbank's entity-embedding table, pg_ripple uses HNSW with cosine distance (`vector_cosine_ops`) since sentence-transformer embeddings are best compared via cosine similarity.

---

## 3. How riverbank Currently Uses Embeddings

### 3.1 Embedding Generation (Pipeline)

During ingest, `pipeline/__init__.py: _generate_and_store_embeddings()` runs after each fragment's triples are written:
1. Iterates unique triple subjects
2. Calls `EmbeddingGenerator.generate(object_value or fragment_text)` — sentence-transformers via `all-MiniLM-L6-v2` (default)
3. Calls `store_entity_embedding(conn, subject_iri, embedding)` → `pg_ripple.store_embedding()`

The model is lazy-loaded and cached per pipeline run. Falls back silently when `sentence-transformers` is not installed.

### 3.2 Entity Deduplication (Post-processor)

`postprocessors/dedup.py: EntityDeduplicator` runs as a post-ingest pass:
1. SPARQL query to fetch all entity IRIs + `rdfs:label` values from the named graph
2. `model.encode(labels)` — batch embedding in Python memory
3. Greedy single-pass clustering by cosine similarity (`threshold: 0.92` default)
4. Promotes shortest IRI as canonical per cluster
5. Writes `owl:sameAs` triples for aliases

**Current limitation:** Step 2 and 3 happen entirely in Python. All entity IRIs and labels must be fetched into memory before similarity can be computed. At 10,000+ entities this becomes slow and memory-intensive.

### 3.3 Semantic Chunking (Fragmenter)

`fragmenter: semantic` in profile YAML uses sentence-transformers (`all-MiniLM-L6-v2`) to detect semantically coherent chunk boundaries before the LLM extraction pass. Embeddings here are purely in Python — they don't touch the database.

### 3.4 RAG Context (Query Path)

`pg_ripple.rag_context()` and `pg_ripple.rag_retrieve()` are available via `sparql_query()` but not yet called from riverbank's query CLI. They are documented in `docs/reference/sparql-helpers.md` as the intended retrieval interface.

---

## 4. The Gap: Where pgvector Integration Is Incomplete

### 4.1 Python-Side Dedup vs. Database-Side ANN

The `EntityDeduplicator` fetches all entities into Python, embeds them, then clusters in Python. pg_ripple's `suggest_sameas()` already calls into its own pgvector index to find similar entity candidates server-side — but riverbank's deduplicator does not use it, instead re-doing the similarity computation in Python.

**The opportunity:** Replace or supplement the Python clustering step with a database query:

```sql
-- For each entity, find similar candidates within threshold
SELECT a.entity_iri, b.entity_iri, 1 - (a.embedding <=> b.embedding) AS similarity
FROM pg_ripple.entity_embeddings a
CROSS JOIN LATERAL (
  SELECT entity_iri, embedding
  FROM pg_ripple.entity_embeddings
  WHERE entity_iri != a.entity_iri
  ORDER BY embedding <=> a.embedding
  LIMIT 5
) b
WHERE 1 - (a.embedding <=> b.embedding) >= 0.92;
```

This executes on the HNSW index — sub-millisecond per entity — with no Python memory pressure.

### 4.2 RAG Retrieve Not Wired to Query CLI

`riverbank query <sparql>` passes SPARQL directly to `pg_ripple.sparql()`. Natural-language queries that could benefit from `rag_retrieve()` (which does embedding + vector lookup + graph walk) are not exposed.

### 4.3 Centroid Views Not Queried

The pg_trickle-maintained `avg(embedding)::vector` centroid views exist inside pg_ripple but riverbank never queries them directly. They are the intended first step for `rag_retrieve()` — find the nearest cluster centroid, then fetch facts from that cluster — but this path is not yet wired in riverbank's CLI or pipeline.

### 4.4 Predicate Normalization Dedup Also Python-Side

`postprocessors/predicate_norm.py: PredicateNormalizer` does the same Python-side embedding + clustering as `EntityDeduplicator` but for predicates. Same limitation applies.

---

## 5. Improvement Strategies

### Strategy 1: Migrate Entity Dedup to Database-Side (High ROI)

**Current:** `EntityDeduplicator` fetches all entities → Python → cluster → write `owl:sameAs`

**Target:** Call `pg_ripple.suggest_sameas()` per entity cluster + use pgvector LATERAL join for batch similarity queries

**Implementation approach:**

```python
# In EntityDeduplicator.deduplicate(), replace Python clustering with:
def _find_similar_db(self, conn, named_graph: str, threshold: float) -> list[tuple[str, str, float]]:
    """Find similar entity pairs using pgvector via pg_ripple."""
    from sqlalchemy import text
    rows = conn.execute(text("""
        SELECT a_iri, b_iri, similarity
        FROM pg_ripple.find_similar_entities(
            cast(:graph as text),
            cast(:threshold as float8)
        )
    """), {"graph": named_graph, "threshold": threshold}).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]
```

This requires pg_ripple to expose `find_similar_entities()` (already implied by `suggest_sameas()` internals). Alternatively, use the raw pgvector SQL via a custom function in the migration.

**Fallback:** If the pg_ripple function is unavailable, fall back to the existing Python path — consistent with riverbank's graceful-degradation pattern.

**Expected impact:** 10–100× faster dedup at >1,000 entities; eliminates Python memory pressure; enables live dedup during ingest rather than post-processing only.

### Strategy 2: Wire `rag_retrieve()` to the Query Path (Medium ROI)

Add a `--semantic` flag to `riverbank query` that routes to `rag_retrieve()` instead of raw SPARQL:

```bash
# Current
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . } LIMIT 5"

# Proposed
riverbank query --semantic "What does Ariadne produce?"
```

Internally:

```python
# cli.py
if semantic_mode:
    rows = conn.execute(
        text("SELECT * FROM pg_ripple.rag_retrieve(:q, :g, :n)"),
        {"q": query_text, "g": named_graph, "n": limit}
    ).fetchall()
```

This exposes the full pgvector → graph walk → LLM-formatted context pipeline that pg_ripple provides, through riverbank's CLI, with zero embedding code required.

**Expected impact:** Makes riverbank immediately useful as a semantic search tool without any LLM call at query time (embeddings are pre-computed at ingest time).

### Strategy 3: Ingest-Time Embedding for All Entities (Medium ROI)

Currently, embeddings are stored per triple subject using the object value or fragment text. The embedding input is not always semantically optimal — an entity's `rdfs:label` is a better embedding anchor than an arbitrary object value.

**Proposed change in `_generate_and_store_embeddings()`:**

```python
# Prefer rdfs:label as embedding text; fall back to object_value then fragment_text
label_query = f"""
  SELECT ?label WHERE {{
    GRAPH <{named_graph}> {{
      <{subject}> <http://www.w3.org/2000/01/rdf-schema#label> ?label .
    }}
  }} LIMIT 1
"""
rows = sparql_query(conn, label_query)
text_for_embedding = (rows[0].get("label") if rows else None) or object_value or fragment_text
```

This ensures entity embeddings are anchored to their canonical labels, making `suggest_sameas()` and `rag_retrieve()` significantly more accurate.

**Expected impact:** Improved dedup recall (fewer missed duplicates at the 0.92 threshold); better `rag_retrieve()` relevance.

### Strategy 4: HNSW Index Tuning for Riverbank's Scale (Low Effort)

At corpus scale (riverbank typical: 1,000–50,000 entities; eval: up to 1M triples), the default HNSW parameters are likely adequate but worth tuning:

| Parameter | Default | Recommendation for riverbank |
|---|---|---|
| `m` (connections/layer) | 16 | 16 (keep; good recall at moderate scale) |
| `ef_construction` | 64 | 128 for better recall at build time |
| `hnsw.ef_search` | 40 | 80 for dedup (precision matters); 20 for RAG (speed matters) |
| `hnsw.iterative_scan` | off | `strict_order` for filtered queries (entity category filters) |

These can be set as pg_ripple configuration options or per-session GUCs in riverbank's connection setup.

Monitoring:
```sql
-- Detect when sequential scan is cheaper than HNSW (small tables)
EXPLAIN (ANALYZE, BUFFERS) 
SELECT entity_iri FROM pg_ripple.entity_embeddings 
ORDER BY embedding <=> '[...]'::vector LIMIT 10;
```

### Strategy 5: Half-Precision Embeddings for Scale (Low Effort, High Impact at Scale)

`all-MiniLM-L6-v2` produces 384-dimensional `float32` vectors: **384 × 4 + 8 = 1,544 bytes per entity**.

Switching to `halfvec(384)` halves storage and index memory: **384 × 2 + 8 = 776 bytes per entity**. At 1M entities: saves ~740 MB of index memory with negligible recall impact (float16 precision is sufficient for cosine similarity at this dimensionality).

For `nomic-embed-text` (768-dim), which is configured in the semantic profile:
- `vector(768)` → 3,080 bytes per entity
- `halfvec(768)` → 1,544 bytes per entity (same as float32 384-dim)
- Binary quantized index for initial ANN + float re-rank for recall

pg_ripple would need to expose this configuration, or it can be set directly via migration:

```sql
-- In a new migration file
ALTER TABLE pg_ripple.entity_embeddings 
  ALTER COLUMN embedding TYPE halfvec(384);
-- Rebuild HNSW index at half precision
DROP INDEX IF EXISTS pg_ripple.entity_embeddings_hnsw_idx;
CREATE INDEX CONCURRENTLY ON pg_ripple.entity_embeddings 
  USING hnsw (embedding halfvec_cosine_ops);
```

### Strategy 6: Hybrid Search Fusion (Already Planned, Needs Wiring)

`plans/riverbank.md` section 9.3 describes a three-stream hybrid search already planned:

| Stream | Mechanism | Status |
|---|---|---|
| BM25 | PostgreSQL `tsvector` + `ts_rank_cd` | Partial (thesaurus expansion wired) |
| Vector | pgvector cosine similarity via pg_ripple | Embeddings stored; RAG retrieve available but not CLI-wired |
| Graph traversal | SPARQL property-path walk | Available via `riverbank query` |

The fusion function (Reciprocal Rank Fusion, `Σ 1/(60 + rank_i)`) is planned as a SQL helper. The pgvector stream is already the most mature technically — embeddings are stored at ingest time and HNSW indexes are maintained by pg_ripple. The gap is the SQL RRF function and the CLI integration that calls all three streams and merges results.

```sql
-- RRF fusion (to be implemented as pg_ripple function or riverbank helper)
WITH bm25_results AS (
  SELECT entity_iri, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(label_tsv, q) DESC) AS rank
  FROM pg_ripple.entity_labels, plainto_tsquery($1) q
  WHERE label_tsv @@ q
),
vector_results AS (
  SELECT entity_iri, ROW_NUMBER() OVER (ORDER BY embedding <=> $2) AS rank
  FROM pg_ripple.entity_embeddings
  ORDER BY embedding <=> $2 LIMIT 100
),
graph_results AS (
  -- SPARQL property path results ranked by hop distance
  SELECT entity_iri, hop_distance AS rank
  FROM pg_ripple.graph_walk($3, $4)
)
SELECT entity_iri,
  SUM(1.0 / (60 + rank)) AS rrf_score
FROM (
  SELECT entity_iri, rank FROM bm25_results
  UNION ALL
  SELECT entity_iri, rank FROM vector_results
  UNION ALL
  SELECT entity_iri, rank FROM graph_results
) all_results
GROUP BY entity_iri
ORDER BY rrf_score DESC
LIMIT 10;
```

### Strategy 7: Use `embedding_stream_table()` for Explicit Embedding Corpus Management (Medium Effort, High Operational Value)

Currently, pg_ripple manages the entity embedding table and its HNSW index internally. This is convenient but opaque — riverbank has no visibility into index freshness or drift. pg_trickle's `embedding_stream_table()` (v0.48.0, VA-1) creates an explicitly managed, monitored stream table over any source table:

```sql
-- Add to a riverbank migration (e.g., 0012_embedding_stream_table.py)
SELECT pgtrickle.embedding_stream_table(
    name             => 'riverbank_entity_embeddings',
    source_table     => 'pg_ripple.entity_embeddings',
    vector_column    => 'embedding',
    extra_columns    => ARRAY['entity_iri', 'cluster_id', 'graph_iri'],
    refresh_interval => '5s',
    index_type       => 'hnsw'
);

-- Configure drift-aware reindex at 15% change threshold
SELECT pgtrickle.alter_stream_table(
    'riverbank_entity_embeddings',
    post_refresh_action     => 'reindex_if_drift',
    reindex_drift_threshold => 0.15
);
```

Benefits for riverbank:
- **Operational visibility:** `SELECT * FROM pgtrickle.vector_status()` shows embedding lag, drift %, and last reindex timestamp — exposable as a health metric in `riverbank status`
- **Automatic HNSW maintenance:** REINDEX fires automatically when >15% of embeddings change (e.g., after a bulk re-ingest), keeping ANN recall high
- **Post-refresh ANALYZE:** Keeps planner statistics current without manual intervention
- **Dry-run preview:** `dry_run => true` lets CI validate the embedding pipeline DDL without executing it
- **No silent degradation:** pg_ripple's internal index management doesn't surface drift; pg_trickle's `vector_status()` makes it observable

**Integration point:** Expose `pgtrickle.vector_status()` in `riverbank status --verbose` so operators can see embedding corpus health alongside graph statistics.

**Expected impact:** Automatic HNSW index maintenance prevents recall degradation after heavy ingest runs; operational dashboards can alert on `drift_pct > 0.3` or `embedding_lag > 30s` without custom monitoring code.

### Strategy 8: Reactive Dedup via Distance Subscriptions (Medium Effort, High Architectural Value)

Replace the batch `riverbank deduplicate-entities` CLI pass with a continuous, low-latency pipeline using pg_trickle's reactive distance subscriptions (v0.48.0, VH-2). After each embedding refresh, the scheduler fires NOTIFY on a channel when entity pairs satisfy the cosine distance threshold:

```sql
-- Register subscription (once, in migration or setup)
SELECT pgtrickle.subscribe_distance(
    stream_table  => 'riverbank_entity_embeddings',
    channel       => 'riverbank.potential_duplicates',
    vector_column => 'embedding',
    query_vector  => NULL,   -- NULL = monitor all-pairs
    op            => '<=>',
    threshold     => 0.08    -- cosine distance < 0.08 → similarity > 0.92
);
```

In a riverbank background worker or asyncio task:

```python
# src/riverbank/workers/dedup_listener.py
import select
import json
from sqlalchemy import text

def run_reactive_dedup(engine, graph_iri: str) -> None:
    """Listen for near-duplicate notifications and write owl:sameAs links."""
    with engine.connect() as conn:
        conn.execute(text("LISTEN \"riverbank.potential_duplicates\""))
        raw = conn.connection.connection  # underlying psycopg2 connection
        while True:
            if select.select([raw], [], [], timeout=60.0) != ([], [], []):
                raw.poll()
                for notify in raw.notifies:
                    payload = json.loads(notify.payload)
                    # payload contains candidate IRI pairs from the distance check
                    _write_sameas_candidates(conn, graph_iri, payload)
                raw.notifies.clear()
```

This turns dedup from a post-processing batch job into an incremental pipeline:
- Near-duplicates are detected within seconds of their embeddings being stored
- No full entity scan required — the pg_trickle scheduler does the proximity check at refresh time
- Compatible with the existing `EntityDeduplicator` fallback path for cold-start scenarios

**Expected impact:** Eliminates the latency gap between ingest and dedup in production; reduces dedup compute from O(n²) Python clustering to O(1) per pg_trickle refresh cycle.

### Strategy 9: Embedding Outbox for Cross-System Consistency (Low Effort, Future-Proofing)

When riverbank embeddings need to propagate to external systems (ML retraining pipelines, A/B vector store testing, external semantic search APIs), use pg_trickle's embedding outbox (v0.48.0, VA-4) instead of writing custom event-forwarding code:

```sql
-- Attach embedding outbox (requires pg_tide extension)
SELECT pgtrickle.attach_embedding_outbox(
    stream_table          => 'riverbank_entity_embeddings',
    vector_column         => 'embedding',
    retention_hours       => 24,
    inline_threshold_rows => 1000
);
```

Every non-empty refresh emits an `embedding_change` event to the pg_tide outbox, containing:
- `event_type: "embedding_change"`
- `vector_column: "embedding"` in headers
- Delta rows (entity IRIs with updated embeddings)

Downstream consumers use pg_tide's consumer group API:

```sql
-- In an external ML pipeline or sidecar
SELECT * FROM tide.poll_outbox('riverbank_entity_embeddings_outbox', 'ml-retrainer', 100);
SELECT tide.commit_offset('riverbank_entity_embeddings_outbox', 'ml-retrainer', :offset);
```

The pg_tide relay can forward these events to Kafka, NATS, AWS SQS, or HTTP webhooks without any riverbank Python code.

**Expected impact:** Zero-code event forwarding for embedding change propagation; enables continuous model retraining pipelines and external vector store synchronization without riverbank orchestration logic.

---

### Strategy 10: Live Dedup During Ingest (Advanced)

Instead of post-ingest dedup as a separate `riverbank deduplicate-entities` pass, check for near-duplicate entities at extraction time before writing a new entity IRI:

```python
# In pipeline/__init__.py, after extracting triples but before writing:
def _resolve_entity_aliases(self, conn, subject_iri: str, embedding: list[float], threshold: float = 0.92) -> str:
    """Return canonical IRI if a near-duplicate already exists in the graph."""
    candidates = suggest_sameas(conn, subject_iri, named_graph=self._named_graph)
    # candidates comes from pg_ripple.suggest_sameas() which uses the pgvector index
    if candidates:
        return candidates[0]  # most similar existing entity
    return subject_iri  # no duplicate found; use as-is
```

This would make the graph converge to canonical entity IRIs during ingest rather than requiring a post-processing pass. The trade-off is additional latency per triple during ingest (one pgvector lookup per unique subject).

---

## 6. Architecture: How the Pieces Fit

```
┌─────────────────────────────────────────────────────────────────┐
│                         riverbank ingest                         │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  fragmenter   │    │  extractor   │    │  EmbeddingGen    │  │
│  │  (semantic/  │───▶│  (LLM via    │───▶│  (sentence-      │  │
│  │   header)    │    │   instructor) │    │   transformers)  │  │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘  │
│                                                   │             │
│                           ┌───────────────────────▼──────────┐ │
│                           │         pg_ripple                  │ │
│                           │                                    │ │
│  load_triples_with_confidence()  store_embedding(iri, vector) │ │
│                           │                                    │ │
│                           │  ┌──────────────────────────────┐ │ │
│                           │  │    entity_embeddings table    │ │ │
│                           │  │    vector(384) + HNSW index   │ │ │
│                           │  └──────────────┬───────────────┘ │ │
│                           │                 │                  │ │
│                           │  pg_trickle IVM: avg(embedding)   │ │
│                           │  ──────────────────────────────▶  │ │
│                           │  cluster_centroids materialized   │ │
│                           │  view (updated incrementally)     │ │
│                           └────────────────┬──────────────────┘ │
└────────────────────────────────────────────┼────────────────────┘
                                             │
┌────────────────────────────────────────────▼────────────────────┐
│                       riverbank query                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  BM25 (tsvector)  │  pgvector (HNSW)  │  SPARQL walk   │   │
│  │  ts_rank_cd()     │  rag_retrieve()   │  property-path │   │
│  └──────────────────────────────────────────────────────────┘  │
│                             │ RRF fusion                        │
│                             ▼                                   │
│                       ranked results                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. What pg_ripple Handles vs. What riverbank Handles

| Concern | pg_ripple | riverbank |
|---|---|---|
| Vector storage | `entity_embeddings` table with `vector(n)` column | Calls `store_embedding()` at ingest |
| HNSW indexing | Creates and maintains index on init | No index management needed |
| Centroid IVM | pg_trickle stream table `avg(embedding)::vector` | No maintenance needed |
| Similarity search | `suggest_sameas()`, `rag_retrieve()`, `find_similar_entities()` | Calls wrappers in `catalog/graph.py` |
| Embedding computation | `rag_retrieve()` embeds query in-DB | Python-side via `EmbeddingGenerator` for ingest |
| Duplicate detection | `suggest_sameas()` + `pagerank_find_duplicates()` | `EntityDeduplicator` (Python-side; candidate for migration) |
| Hybrid fusion | (planned pgvector + BM25 + SPARQL) | Planned `riverbank query --semantic` CLI flag |

---

## 8. Constraints and Trade-offs

### 8.1 Embedding at Ingest Time Adds Latency
Each unique entity subject requires one sentence-transformers encode call (~1–5ms per entity on CPU, <1ms on GPU). For a corpus producing 1,000 unique entities, that's 1–5 seconds of embedding overhead per ingest run. This is acceptable but should be async where possible.

**Mitigation:** Batch encode all unique subjects per fragment (already done via `seen_subjects` set); consider batching across the full fragment list with `model.encode(all_labels_at_once)`.

### 8.2 Vector Dimensions Must Match Index
`pg_ripple.store_embedding()` casts to `vector`. If the embedding model changes (e.g., from `all-MiniLM-L6-v2` at 384 dims to `nomic-embed-text` at 768 dims), the column type and HNSW index must be rebuilt. The `profiles.embedding_model` column in the riverbank catalog tracks which model was used, but mixed-model embeddings in the same column will break similarity queries.

**Mitigation:** When changing `embed_model` in a profile, run `riverbank reset-database` or add a migration that drops and recreates the embedding column with the correct dimension. Alternatively, use pg_ripple's `vector` type without dimension annotation and create model-partitioned indexes.

### 8.3 Cold Start: No Embeddings Before First Ingest
`rag_retrieve()` and `suggest_sameas()` are only useful after at least some embeddings are stored. A fresh database has no vector index entries, so all similarity queries return empty. This is expected behavior but should be documented.

### 8.4 HNSW Recall vs. Speed Tradeoff
Default `hnsw.ef_search = 40` may miss some true neighbors (approximate search). For dedup, missing a true duplicate at similarity 0.93 means it persists as a separate entity — a quality problem. Setting `hnsw.ef_search = 100` or using `hnsw.iterative_scan = strict_order` improves recall at the cost of query time.

**Recommendation:** For dedup operations (where recall matters more than latency), set `SET LOCAL hnsw.ef_search = 100` in the dedup transaction. For RAG retrieval (where latency matters more), use defaults.

### 8.5 Vacuum and Index Health
HNSW indexes accumulate dead tuples when entities are updated or deleted. For riverbank, entities are rarely deleted (GDPR erasure uses `pg_ripple.erase_subject()` which handles index cleanup). Routine PostgreSQL autovacuum handles this. The `REINDEX INDEX CONCURRENTLY` + `VACUUM` pattern is available for maintenance if needed.

---

## 9. Prioritized Action Plan

| Priority | Action | Effort | Expected ROI |
|---|---|---|---|
| **P1** | Wire `riverbank query --semantic` to `pg_ripple.rag_retrieve()` | Low (1–2 days) | ⭐⭐⭐⭐⭐ |
| **P1** | Use `rdfs:label` as embedding text anchor instead of object_value | Low (<1 day) | ⭐⭐⭐⭐ |
| **P2** | Migrate `EntityDeduplicator` Python clustering to `pg_ripple.suggest_sameas()` LATERAL query | Medium (2–3 days) | ⭐⭐⭐⭐ |
| **P2** | Tune `hnsw.ef_search` per operation type (dedup=100, RAG=40) | Low (hours) | ⭐⭐⭐ |
| **P2** | Add `embedding_stream_table()` migration + expose `pgtrickle.vector_status()` in `riverbank status` (Strategy 7) | Low (1 day) | ⭐⭐⭐⭐ |
| **P3** | Switch entity embedding column to `halfvec` at scale (>100K entities) | Medium (migration + test) | ⭐⭐⭐ |
| **P3** | Implement RRF fusion SQL helper for hybrid search | Medium (2–3 days) | ⭐⭐⭐⭐ |
| **P3** | Add reactive dedup worker using pg_trickle distance subscriptions (Strategy 8) | Medium (2–3 days) | ⭐⭐⭐⭐ |
| **P4** | Live entity resolution during ingest — call `suggest_sameas()` per new entity (Strategy 10) | High (pipeline changes + tests) | ⭐⭐⭐ |
| **P4** | Attach embedding outbox for cross-system event propagation (Strategy 9) | Low (1 migration) | ⭐⭐ |

---

## 10. Summary

pgvector is already present in riverbank's stack via pg_ripple — it is not an addition to evaluate but an existing capability to exploit more fully. pg_trickle, already a required dependency, has shipped an extensive incremental pgvector feature set across v0.37–v0.48 that riverbank has not yet adopted. The key integration points are:

1. **`pg_ripple.store_embedding()`** — already called at ingest; stores entity vectors in pgvector columns with automatic HNSW indexing.

2. **`pg_trickle` IVM (v0.37+)** — automatically maintains `avg(embedding)::vector` cluster centroids without riverbank involvement; these centroids are the starting point for fast entity cluster lookup. Enabled via `SET pg_trickle.enable_vector_agg = on`.

3. **`pgtrickle.embedding_stream_table()` (v0.48, VA-1)** — one-call setup for an embedding stream table with HNSW indexing and drift monitoring. Should replace the implicit reliance on pg_ripple's opaque internal index management.

4. **`pgtrickle.vector_status()` (v0.47, VP-3)** — monitoring view for embedding lag, ANN index freshness, and drift percentage. Should be surfaced in `riverbank status --verbose`.

5. **Drift-aware HNSW reindexing (v0.47, VP-1/VP-2)** — `post_refresh_action => 'reindex_if_drift'` automatically triggers REINDEX when enough embeddings have changed. Prevents recall degradation after bulk re-ingest runs without manual maintenance.

6. **Reactive distance subscriptions (v0.48, VH-2)** — `subscribe_distance()` fires NOTIFY after each refresh when entity pairs satisfy the cosine similarity threshold. Enables a continuous dedup pipeline that replaces the batch `riverbank deduplicate-entities` CLI command.

7. **`pg_ripple.rag_retrieve()`** — end-to-end pgvector-based RAG already implemented in pg_ripple; riverbank just needs to call it from the query CLI (`riverbank query --semantic`).

8. **`pg_ripple.suggest_sameas()`** — vector-based entity dedup candidates already exposed; riverbank's Python-side `EntityDeduplicator` can delegate its similarity search step to this function, moving the hot path from Python memory to the HNSW index.

9. **Embedding outbox (v0.48, VA-4)** — `attach_embedding_outbox()` emits `embedding_change` events via pg_tide whenever embeddings change. Enables zero-code propagation to external ML pipelines or vector stores.

The architectural goal is: **embed at ingest time (Python), store and index in pg_ripple (PostgreSQL + pgvector), maintain and monitor via pg_trickle (IVM + drift detection + reactive subscriptions), query at retrieval time (SQL via pg_ripple functions).** riverbank Python code should only be responsible for generating the raw float vectors; everything else — indexing, similarity search, centroid maintenance, dedup candidate generation, index health monitoring, and downstream event propagation — is handled by the pg_ripple + pg_trickle + pg_tide layer.

> **Note on v0.49.0:** The latest release focuses entirely on test infrastructure (concurrency synchronization, new fuzz targets, scheduler module decomposition) with no new vector features. The complete embedding programme shipped in v0.48.0.
