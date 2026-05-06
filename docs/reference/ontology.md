# Ontology reference

The `pgc:` vocabulary (prefix: `https://pg-ripple.org/compile#`) is defined in `ontology/pgc.ttl`. This page documents every class, property, and named individual.

## Classes

### `pgc:Source`

A registered source document (file, API response, issue, etc.).

```sparql
SELECT ?source WHERE { ?source a pgc:Source . }
```

### `pgc:Fragment`

A stable section of a source (heading block, page, time segment, etc.).

```sparql
SELECT ?fragment ?key WHERE {
  ?fragment a pgc:Fragment ;
            pgc:fragmentKey ?key .
}
```

### `pgc:Profile`

A versioned compiler profile: JSON Schema + system prompt + editorial policy.

```sparql
SELECT ?profile ?name ?version WHERE {
  ?profile a pgc:Profile ;
           pgc:profileName ?name ;
           pgc:profileVersion ?version .
}
```

### `pgc:Run`

One compile attempt for a fragment under a profile.

```sparql
SELECT ?run ?outcome ?cost WHERE {
  ?run a pgc:Run ;
       pgc:outcome ?outcome ;
       pgc:costUsd ?cost .
}
```

### `pgc:Synthesis`

An atomic compiled artifact (a triple or named claim) written to the graph. Subclass of `pgc:Artifact`.

```sparql
SELECT ?artifact ?confidence WHERE {
  ?artifact a pgc:Synthesis ;
            pgc:confidence ?confidence .
}
```

### `pgc:LintFinding`

A quality finding raised by the lint pass.

```sparql
SELECT ?finding ?type ?message WHERE {
  ?finding a pgc:LintFinding ;
           pgc:findingType ?type ;
           pgc:findingMessage ?message .
}
```

### `pgc:ArgumentRecord`

A structured argument for or against a claim.

```sparql
SELECT ?arg ?claim ?strength WHERE {
  ?arg a pgc:ArgumentRecord ;
       pgc:claim ?claim ;
       pgc:strength ?strength .
}
```

### `pgc:AssumptionRecord`

An explicit assumption made during compilation.

```sparql
SELECT ?assumption ?text ?status WHERE {
  ?assumption a pgc:AssumptionRecord ;
              pgc:assumptionText ?text ;
              pgc:status ?status .
}
```

### `pgc:NegativeKnowledge`

A recorded absence of evidence for a claim.

```sparql
SELECT ?nk ?subject ?predicate ?reason WHERE {
  ?nk a pgc:NegativeKnowledge ;
      pgc:aboutSubject ?subject ;
      pgc:negatedPredicate ?predicate ;
      pgc:reason ?reason .
}
```

### `pgc:CoverageMap`

Coverage tracking for compiled concepts.

```sparql
SELECT ?concept ?level WHERE {
  ?cm a pgc:CoverageMap ;
      pgc:concept ?concept ;
      pgc:coverageLevel ?level .
}
```

### `pgc:RenderedPage`

A page rendered from compiled knowledge.

```sparql
SELECT ?page ?format ?renderedAt WHERE {
  ?page a pgc:RenderedPage ;
        pgc:format ?format ;
        pgc:renderedAt ?renderedAt .
}
```

## Properties

### `pgc:fromFragment`

Links a compiled artifact to its source fragment. Subproperty of `prov:wasDerivedFrom`.

- **Domain:** `pgc:Synthesis`
- **Range:** `pgc:Fragment`

### `pgc:byProfile`

The compiler profile used to produce an artifact.

- **Domain:** `pgc:Synthesis`
- **Range:** `pgc:Profile`

### `pgc:confidence`

Confidence score assigned by the extractor.

- **Range:** `xsd:float` (0.0–1.0)

### `pgc:epistemicStatus`

Epistemic status tag. One of: `observed`, `extracted`, `inferred`, `verified`, `deprecated`, `normative`, `predicted`, `disputed`, `speculative`.

- **Range:** `xsd:string`

### `pgc:evidenceSpan`

JSON object: `{char_start, char_end, excerpt}`.

- **Range:** `xsd:string` (JSON)

### `pgc:compiledAt`

Timestamp of the compiler run. Subproperty of `prov:generatedAtTime`.

- **Range:** `xsd:dateTime`

### `pgc:tenantId`

Tenant identifier for RLS scoping.

- **Range:** `xsd:string`

### `pgc:aboutSubject`

Subject of a negative knowledge or argument record.

### `pgc:negatedPredicate`

The predicate whose absence is recorded.

### `pgc:reason`

Human-readable explanation (for negative knowledge or assumptions).

### `pgc:claim`

The fact being argued about (in `ArgumentRecord`).

### `pgc:evidence`

Fragment supporting a claim (in `ArgumentRecord`).

### `pgc:objection`

Counter-argument text (in `ArgumentRecord`).

### `pgc:rebuttal`

Response to an objection (in `ArgumentRecord`).

### `pgc:strength`

Argument strength (0.0–1.0).

### `pgc:assumptionText`

Text of an explicit assumption.

### `pgc:concept`

Concept reference (in `CoverageMap`).

### `pgc:coverageLevel`

Coverage level: `covered`, `partial`, `uncovered`.

### `pgc:format`

Render format: `markdown`, `jsonld`, `html`.

### `pgc:dependsOn`

Dependency edge from a rendered page to a source fact.

## Source

The canonical source is [`ontology/pgc.ttl`](https://github.com/trickle-labs/riverbank/blob/main/ontology/pgc.ttl).
