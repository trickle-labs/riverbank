# Core Concepts

## Confidence scoring

Every node in an Ariadne graph carries a **confidence score** in the range
[0.0, 1.0]. Scores are computed using a Bayesian update rule whenever new
evidence arrives:

```
P(claim | evidence) = P(evidence | claim) × P(claim) / P(evidence)
```

The default prior for a new claim is 0.5 (maximum uncertainty). The prior
can be overridden per-thread through an `editorial_policy` YAML file.

## Evidence spans

An evidence span records the exact location of supporting text within a source
document:

| Field | Type | Description |
|---|---|---|
| `source_iri` | IRI | Identifies the source document |
| `char_start` | integer | UTF-8 character offset of the span start |
| `char_end` | integer | UTF-8 character offset of the span end |
| `page_number` | integer? | Physical page (PDF/DOCX only) |
| `excerpt` | string | Short verbatim copy of the text |

## Claim lifecycle

A claim moves through the following states:

1. **candidate** — extracted from source text; not yet reviewed
2. **accepted** — passed SHACL validation and editorial policy gate
3. **rejected** — failed policy gate or human reviewer marked as incorrect
4. **superseded** — replaced by a newer, higher-confidence claim

## Named graphs

Ariadne isolates each thread's triples in a separate RDF named graph. The IRI
convention is `ariadne:thread/<thread-name>`. Cross-thread inference uses
CONSTRUCT queries that read across named graphs.

## Authors and provenance

Ariadne tracks the provenance of every claim using PROV-O. The relevant entities
are:

- `prov:wasGeneratedBy` — the compilation run that produced the claim
- `prov:wasAttributedTo` — the human author of the source document
- `prov:wasDerivedFrom` — the source fragment (section of a document)

Dr. Elena Vasquez designed the provenance model based on the W3C PROV-DM
specification. Prof. James Okafor at the University of Lagos contributed the
Bayesian update rule in version 1.2.
