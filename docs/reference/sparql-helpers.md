# SPARQL helpers

pg-ripple provides SQL functions that wrap common SPARQL patterns. These are used by riverbank internally and are available for direct use.

## `pg_ripple.sparql_query(query, named_graph)`

Execute a SPARQL SELECT or ASK query against the compiled graph.

```sql
SELECT * FROM pg_ripple.sparql_query(
  'SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10',
  'http://riverbank.example/graph/trusted'
);
```

## `pg_ripple.rag_context(entity_iri, named_graph, max_tokens)`

Format graph facts about an entity into a structured prompt context for LLMs.

```sql
SELECT pg_ripple.rag_context(
  'http://example.org/entity/Acme',
  'http://riverbank.example/graph/trusted',
  2000
);
```

Returns a Markdown-formatted text block with:

- Entity properties and relationships
- Confidence scores
- Epistemic status annotations
- Source citations

## `pg_ripple.rag_retrieve(query_text, named_graph, limit)`

Vector-similarity retrieval over the compiled graph. Uses pgvector embeddings.

```sql
SELECT * FROM pg_ripple.rag_retrieve(
  'What does Acme produce?',
  'http://riverbank.example/graph/trusted',
  5
);
```

Returns the top-K facts most semantically similar to the query text.

## `pg_ripple.shacl_score(named_graph)`

Compute the numeric SHACL quality score for a named graph.

```sql
SELECT pg_ripple.shacl_score('http://riverbank.example/graph/trusted');
-- Returns: 0.9234
```

The score is the proportion of triples conforming to all registered SHACL shapes.

## `pg_ripple.load_triples_with_confidence(triples, named_graph)`

Write triples with confidence scores and provenance edges.

```sql
SELECT pg_ripple.load_triples_with_confidence(
  '[{"s": "...", "p": "...", "o": "...", "confidence": 0.92}]'::jsonb,
  'http://riverbank.example/graph/trusted'
);
```

## `pg_ripple.suggest_sameas(entity_iri)`

Find potential `owl:sameAs` candidates for an entity (fuzzy matching by label).

```sql
SELECT * FROM pg_ripple.suggest_sameas('http://example.org/entity/Acme');
```

Returns IRIs of entities with similar labels (edit distance + token overlap).

## `pg_ripple.explain_contradiction(entity_iri, named_graph)`

Compute the minimal hitting set of sources responsible for a contradiction.

```sql
SELECT * FROM pg_ripple.explain_contradiction(
  'http://example.org/entity/Acme',
  'http://riverbank.example/graph/trusted'
);
```

## `pg_ripple.pg_tide_available()`

Check if the pg-tide CDC sidecar is connected.

```sql
SELECT pg_ripple.pg_tide_available();
-- Returns: true/false
```

## `pg_ripple.load_shape_bundle(bundle_name)`

Activate a SHACL shape bundle (e.g., `skos-integrity`).

```sql
SELECT pg_ripple.load_shape_bundle('skos-integrity');
```

## `pgtrickle.preflight()`

Run pg-trickle system checks (7 checks).

```sql
SELECT * FROM pgtrickle.preflight();
-- Returns: (check_name, ok, detail) rows
```
