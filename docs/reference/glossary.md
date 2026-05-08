# Glossary

A plain-language reference for every term you'll encounter in riverbank's documentation, code, and output. Entries are alphabetical. Where a term has a formal technical meaning, the plain-language explanation comes first — technical precision follows.

---

## A

### Absence rule

An instruction in a compiler profile telling riverbank to record when something is *not* there. Normally, an empty search result is ambiguous — it might mean the fact doesn't exist, or it might mean nobody looked. An absence rule eliminates that ambiguity: if the pipeline searches a fragment for a particular relationship and finds nothing, it writes a `pgc:NegativeKnowledge` record to say "we looked, and it's genuinely absent." This is what lets you query your knowledge graph for confirmed gaps, not just confirmed facts.

### Advisory lock

A cooperative lock held in the PostgreSQL database that prevents two riverbank workers from extracting the same fragment at the same time. Unlike a traditional database row lock, advisory locks don't block database writes — they only work if every participant agrees to check before proceeding. riverbank uses fragment-level advisory locks to run safely across multiple replicas: one worker picks up a fragment, claims the lock, extracts it, then releases the lock. Other workers see the lock and skip ahead to unclaimed work. The result is safe parallelism with no duplicated LLM calls.

### Alembic

The database migration tool riverbank uses to create and evolve the `_riverbank` catalog schema. Alembic is to database schemas what `git` is to source code: it records every change in a numbered sequence of migration scripts and can replay those scripts forward or backward on any database. Running `riverbank init` applies all pending migrations to bring a fresh database up to the current schema version.

### Allowed classes

A whitelist of RDF class IRIs declared in a compiler profile. During extraction, the LLM is told to only classify subjects and objects as one of these declared types. Any triple whose subject or object type falls outside the list is rejected before writing — this prevents the LLM from inventing types that don't belong in your ontology.

### Allowed predicates

A whitelist of RDF predicate IRIs declared in a compiler profile. The LLM is instructed to express relationships *only* using these predicates; anything else is rejected at write time. This is the primary mechanism for keeping your knowledge graph clean and schema-conformant without requiring perfect LLM output — the predicate filter catches vocabulary drift that the LLM introduces.

### Argument graph

A structured record that captures not just a fact but the *reasoning* around it — the claim, the supporting evidence, any objections raised against it, and any rebuttals to those objections. Stored as `pgc:ArgumentRecord` triples, argument graphs are especially useful in domains where facts are contested: legal analysis, policy evaluation, or scientific literature where contradictory studies exist. Unlike a simple confidence score, an argument graph preserves the full line of reasoning so a human reviewer can evaluate it later.

### Artifact

A compiled fact — a single RDF triple written to the knowledge graph as a result of LLM extraction. Every artifact carries metadata: a confidence score, a pointer to the source fragment it came from, the compiler profile that produced it, the timestamp it was compiled, and its epistemic status. Artifacts are the atomic units of the compiled knowledge graph, analogous to the object code a software compiler produces from source files.

### Artifact dependency graph

The network of relationships between artifacts and the fragments they were compiled from. When a source document changes and a fragment is recompiled, riverbank walks the dependency graph to identify every downstream artifact that must be invalidated and recomputed. This is the mechanism that makes incremental compilation correct: no stale facts are left in the graph, and no unnecessary recompilation is triggered.

### Audit trail

A tamper-evident log of every significant action taken in the system, stored in `_riverbank.audit_log`. Every compilation run, schema change, tenant lifecycle event, and GDPR erasure is recorded with a timestamp, the actor, and a hash of the affected data. The audit trail is primarily for compliance — regulated industries need to demonstrate what data was processed, when, and by whom.

---

## B

### Benchmark

The process of re-extracting a golden corpus and comparing the results against known-correct ground truth, expressed as precision, recall, and F1 scores. Running `riverbank benchmark` in CI means any change that degrades extraction quality fails the build — the same guarantee that unit tests provide for code quality, applied to knowledge quality.

### Batch extraction

A mode where multiple document fragments are grouped into a single LLM API call rather than being sent one at a time. This trades a small risk of cross-fragment hallucination for a large reduction in API call overhead — particularly valuable when using hosted LLM APIs where each call carries a fixed latency and minimum billing unit. Configured via `extraction_strategy.batch_size` in the compiler profile.

---

## C

### Calibration

The degree to which a model's confidence scores mean what they claim to mean. A well-calibrated extractor that assigns a confidence of 0.8 to a triple should be right about 80% of the time on triples at that confidence level. riverbank measures calibration by comparing extraction confidence against Wikidata ground truth: if all the 0.8-confidence triples are correct 50% of the time, the model is systematically overconfident. The calibration curve output from `evaluate-wikidata` is used to tune confidence routing thresholds.

### Catalog

The set of PostgreSQL tables in the `_riverbank` schema that record everything the system knows about itself: registered sources, fragment hashes, compiler profiles, compilation runs, artifact dependencies, and the audit log. The catalog is riverbank's memory — it's what makes incremental compilation, run inspection, and provenance querying possible.

### Character range

The exact start and end positions (measured in characters from the beginning of a source document) of the text that supports a compiled fact. Every triple in the knowledge graph must carry a character range as part of its evidence span. This is what makes provenance concrete: not just "this fact came from document X", but "this fact came from characters 4,217 to 4,395 of document X", which corresponds to a specific sentence or phrase you can read.

### Citation grounding

The requirement that every extracted fact must be traceable to a specific passage in its source document. riverbank enforces this at the type-system level: the `EvidenceSpan` type requires both a character range and a verbatim excerpt, and the excerpt is checked against the text at the declared offset. If they don't match, the triple is rejected. This makes fabrication structurally impossible — the LLM cannot cite a passage that doesn't exist.

### Circuit breaker

A fault-tolerance pattern borrowed from electrical engineering. When an LLM provider starts returning errors, a circuit breaker counts the failures and, once they exceed a threshold, "trips" — temporarily stopping new requests to that provider rather than flooding it with calls that will all fail. After a cooling-off period, the breaker enters a half-open state to test whether the provider has recovered. This pattern prevents cascading failures and reduces wasted tokens during provider outages.

### Compiler profile

The primary configuration surface for a compilation run. A YAML file that specifies everything about how a corpus should be compiled: which extractor to use, which LLM model to call, the editorial policy (what fragments to skip), the ontology constraints (which predicates and classes are allowed), the competency questions (what the compiled graph must be able to answer), confidence thresholds, few-shot examples, and post-processing settings. Think of it as the build configuration file for your knowledge graph.

### Competency question

A SPARQL query that the compiled knowledge graph must be able to answer correctly. Competency questions serve the same purpose as unit tests in software: they define what the system is supposed to know, and they run automatically in CI after every compilation. A query that returns no results when it should return results fails the check — signalling that extraction quality has regressed.

### Confidence consolidation

The process of combining multiple independent extractions of the same fact into a single, more reliable confidence score. riverbank uses the **noisy-OR** formula: if three fragments each independently extract the same triple with confidences 0.6, 0.7, and 0.5, the consolidated confidence is $1 - (1-0.6)(1-0.7)(1-0.5) = 0.94$. The intuition is that independent corroboration dramatically increases reliability — the same logic that makes scientific replication meaningful.

### Confidence routing

The mechanism that decides where an extracted triple goes based on its confidence score. High-confidence triples (above the `trusted_threshold`) go to the trusted named graph. Medium-confidence triples (above the `tentative_threshold` but below trusted) go to the tentative graph for accumulation and later promotion. Low-confidence triples are discarded. This replaces the old binary accept/reject approach with a tiered system that preserves uncertain-but-plausible facts for future corroboration.

### Confidence score

A number between 0.0 and 1.0 expressing how strongly the extraction evidence supports a compiled fact. A score of 1.0 means the text states the fact explicitly and unambiguously. A score of 0.35 means the text implies it, but weakly. Confidence scores are not probabilities in the strict statistical sense — they reflect calibrated routing signals. Facts above 0.75 go to the trusted graph; facts between 0.35 and 0.75 accumulate in the tentative graph; facts below 0.35 are discarded.

### Conflict record

A `pgc:ConflictRecord` triple written when two extracted facts directly contradict each other on a functional predicate — for example, two different birth years for the same person. The conflict record captures both competing values, both source fragments, and the detection timestamp. The `riverbank explain-conflict` command surfaces these records in a human-readable form.

### Connector

A plugin that discovers and retrieves source documents. The built-in `filesystem` connector walks a directory tree. Custom connectors can pull from REST APIs, S3 buckets, message queues, Confluence, or any other source. Connectors produce a stream of source documents; everything downstream is source-agnostic.

### Constrained decoding

A technique for forcing a language model to produce output that conforms to a precise JSON schema at the token generation level — not by post-processing, but by restricting which tokens the model is allowed to emit at each step. When enabled for Ollama backends, this eliminates JSON parse errors entirely, because structurally invalid responses are literally impossible. The trade-off is slightly slower generation.

### Coreference resolution

The process of replacing pronouns and ambiguous references in a document with the full entity names they refer to, before that document is fragmented and extracted. "The company was founded in 1995. *It* expanded to Europe in 2001." — after coreference resolution, the second sentence reads "The company expanded to Europe in 2001." This prevents phantom entities (triples about an entity named "it") and dramatically improves extraction accuracy on procedural and narrative text.

### Coverage map

A structured record that tracks which competency questions are answered by the current compiled graph and which are not. A coverage map turns "what does the system know?" from a vague question into a measurable one: N of M competency questions are satisfied, broken down by domain and predicate.

### CycloneDX

An open standard for software bills of materials (SBOMs). The `riverbank sbom` command generates a CycloneDX-format document listing every dependency in the riverbank package — useful for software supply-chain compliance in regulated environments or security audits.

---

## D

### Datalog

A declarative query and inference language that is a restricted subset of Prolog. pg-ripple uses Datalog to express recursive inference rules — rules like "if A is a part of B, and B is a part of C, then A is a part of C". Unlike SPARQL CONSTRUCT rules (which run once and write results), Datalog rules are evaluated lazily and on demand.

### Dependency graph

See *Artifact dependency graph*.

### Differential dataflow

A computational model where results are maintained incrementally as inputs change, rather than being recomputed from scratch each time. pg-trickle uses a DBSP-inspired differential dataflow engine to keep derived views — quality scores, entity pages, topic indices — up to date in milliseconds whenever the underlying graph changes. The alternative would be running a full recomputation on every ingest, which becomes prohibitively slow for large corpora.

### Extraction focus

A profile setting (`extraction_focus`) that controls the precision-vs-recall trade-off at the extractor layer. `comprehensive` (default) extracts all factual claims including strong inferences. `high_precision` extracts only claims explicitly and unambiguously stated in the text, with confidence ≥ 0.90. `facts_only` extracts stated factual assertions and excludes opinions, estimates, and hedged language. The extraction focus is injected into the extraction prompt — it does not affect fragmentation, which always produces all atomic statements.

### Draft graph

The `graph/draft` named graph where extracted facts are routed when their confidence falls below the trusted threshold but they've been explicitly flagged for human review rather than simply discarded. Draft facts are visible in Label Studio's review queue, where a human can accept them (promoting them to trusted) or reject them.

---

## E

### Editorial policy gate

The filter that runs before any LLM call, discarding fragments that are too short, too long, in the wrong language, or at a heading depth that indicates they're structural noise (like a top-level title page). This gate exists purely to save money and improve quality — LLM calls on fragments that clearly contain no useful knowledge are wasteful. Every skipped fragment is recorded in run statistics so you can see exactly what was filtered and why.

### Embedding

A list of numbers (a vector) that represents the meaning of a piece of text in a high-dimensional mathematical space. Two texts with similar meanings will have embeddings that are close together in that space, measured by cosine similarity. riverbank uses embeddings for several purposes: entity deduplication (finding entities that refer to the same concept under different names), semantic chunking (finding natural topic boundaries in a document), semantic few-shot selection (finding golden examples that are topically similar to the fragment being extracted), and vector search via pgvector.

### Entity catalog

A per-document list of named entities (people, organizations, places, concepts) and their known aliases, built by the preprocessing pass and injected into every extraction prompt for that document. The entity catalog anchors the LLM to canonical entity IRIs, preventing the same organization from appearing as "ACME Corp", "ACME Corporation", "Acme", and "the company" across different fragments.

### Entity deduplication

The process of identifying when two different entity IRIs in the knowledge graph actually refer to the same real-world thing — for example, `ex:Marie_Curie` and `ex:MarieCurie` — and writing `owl:sameAs` links to declare their equivalence. riverbank uses embedding-based similarity clustering: entity labels are embedded, compared by cosine similarity, and merged when similarity exceeds the configured threshold. The `riverbank deduplicate-entities` command runs this pass explicitly.

### Entity registry

A persistent table (`entity_registry`) that grows as documents are processed, tracking every entity IRI the system has ever seen, its label, type, embedding, when it was first observed, and how many documents it has appeared in. Before each extraction, the top-K most relevant entities from the registry are injected into the prompt as "KNOWN ENTITIES — prefer these IRIs." This is what makes the system converge on stable IRIs over time rather than minting new ones on every run.

### Epistemic model

The framework riverbank uses to represent not just *what* is known, but *how well* it's known and *why*. The epistemic model includes: nine status values (from `observed` through `verified` to `deprecated`), negative knowledge records for confirmed absences, argument graphs for contested claims, assumption records for working hypotheses, and confidence scores for every extracted fact. The goal is a knowledge graph you can trust — one that is honest about uncertainty rather than presenting everything with equal authority.

### Epistemic status

A label attached to every compiled fact indicating its current state of knowledge. The nine values — `observed`, `extracted`, `inferred`, `verified`, `deprecated`, `normative`, `predicted`, `disputed`, `speculative` — form a lifecycle from raw observation to validated knowledge. A `disputed` fact is one where two sources contradict each other; a `deprecated` fact is one that was once valid but has been superseded; a `speculative` fact came from hedged language ("might", "could") in the source.

### Evidence span

The proof that a compiled fact is grounded in its source document. An evidence span consists of two parts: the character range (start and end positions in the source file) and a verbatim excerpt (the exact text at those positions). Every triple in the knowledge graph must carry a valid evidence span — one where the excerpt actually appears at the declared character range. This check is performed at write time and cannot be bypassed.

### Extractor

The plugin responsible for calling the LLM and converting its response into structured RDF triples. The built-in `instructor` extractor uses the Instructor library to enforce a Pydantic schema on LLM output, with automatic retries when the model produces malformed responses. The `noop` extractor is used for testing — it records a run and emits telemetry spans without making any LLM calls or writing any triples. Custom extractors can be installed via Python entry points.

---

## F

### F1 score

The harmonic mean of precision and recall: $F1 = 2 \cdot \frac{\text{precision} \cdot \text{recall}}{\text{precision} + \text{recall}}$. Used in the Wikidata evaluation benchmark as the single headline quality metric. F1 is preferred over accuracy because it penalises both over-extraction (precision loss) and under-extraction (recall loss) equally. A system that extracts everything scores perfect recall but terrible precision; one that extracts only certainties scores perfect precision but terrible recall. F1 rewards the balance.

### Federation

The ability for one riverbank instance to pull compiled triples from a remote pg-ripple instance and incorporate them into its local knowledge graph. Federation is how organisations share compiled knowledge without sharing raw documents — the remote instance controls what it exposes via SPARQL, and the local instance weights the imported triples by a configurable confidence factor to account for the fact that foreign extraction quality may differ from local quality.

### Few-shot injection

The technique of prepending worked examples to the extraction prompt before sending it to the LLM. Instead of asking the LLM to extract triples from cold text, few-shot injection shows it 1–3 examples of a fragment and its correct extraction, which significantly improves output quality and consistency. The examples are stored in YAML files in `examples/golden/` and can be selected randomly or semantically (choosing examples that are topically similar to the current fragment).

### Fragment

The atomic unit of compilation in riverbank. A fragment is typically one heading and its associated content — a section of a document. Fragments are independently extractable, hashable, and cacheable. When a document changes, only the fragments that changed need recompilation. The `xxh3_128` hash of a fragment's text is stored after compilation; on re-ingest, an identical hash means the fragment is skipped with zero LLM cost.

### Fragmenter

The plugin that splits a parsed document into fragments. The built-in options are:
- **`heading`** — splits at Markdown heading boundaries (the default for structured documents)
- **`semantic`** — uses embedding-based boundary detection to split at topic transitions
- **`llm_statement`** — sends the whole document to the LLM once and asks it to split it into individual statements
- **`direct`** — passes the whole document as a single fragment (for pre-split corpora)

### Functional predicate

A predicate where each subject can have at most one value — for example, `schema:birthDate` (a person has exactly one birth date). Functional predicates are declared in the `predicate_constraints` block of a compiler profile. When two conflicting values for a functional predicate are found (different birth dates for the same person, from different sources), riverbank creates a conflict record and reduces the confidence of both competing triples.

---

## G

### GDPR erasure

The ability to delete all data about a specific subject from the knowledge graph and catalog, leaving no trace. Implemented by cascading deletion of all triples whose subject IRI matches the erasure request, along with all provenance records, fragment references, and audit entries. Triggered via `riverbank tenant delete --gdpr` or the `riverbank source` GDPR commands. pg-ripple handles the graph-side erasure; Alembic migrations ensure the catalog tables support cascading deletes.

### Golden corpus

A curated set of documents with known-correct extraction results, used as a regression test for extraction quality. When `riverbank benchmark` runs against the golden corpus, it re-extracts the documents from scratch and compares the results against the ground truth file. A drop in F1 score below the configured threshold fails the build — the same guarantee that unit tests provide for code, applied to knowledge quality.

### Graph write

The final stage of the compilation pipeline, where validated triples are written to pg-ripple via `load_triples_with_confidence()`. The graph write includes the triple itself, its confidence score, its evidence span, its provenance edges, and its epistemic status. pg-trickle's IMMEDIATE refresh mode keeps SHACL score gates in sync within the same transaction, so quality constraints are enforced at write time rather than in a background job.

### GraphRAG

A retrieval pattern that uses a structured knowledge graph — rather than raw vector similarity search — to find relevant context for LLM generation. pg-ripple's `rag_context()` and `rag_retrieve()` functions format graph facts as structured context blocks for LLM prompts, producing retrievals that are precise, attributable, and reproducible rather than probabilistic nearest-neighbour results.

---

## H

### Hash-based fragment skip

The mechanism that makes re-ingesting unchanged documents free. After each fragment is compiled, its `xxh3_128` hash is stored. On the next ingest, the hash is recomputed and compared to the stored value. An identical hash means the fragment text hasn't changed, so the extraction result is still valid — no LLM call needed. Only fragments with changed hashes (or new fragments) are recompiled. This is what makes riverbank suitable for corpora that are updated frequently.

### Helm chart

A Kubernetes packaging format. The `helm/riverbank/` directory contains a Helm chart that deploys the full riverbank stack — workers, PostgreSQL with extensions, Langfuse, Prometheus scraping — onto any Kubernetes 1.28+ cluster with a single `helm install` command.

---

## I

### Incremental compilation

The property of only recompiling what has changed. When a source document is updated, only the fragments that differ from the previous version need to be re-extracted. All other fragments are served from the existing catalog. This is analogous to how `make` or Gradle only recompile source files that have changed — except here the "compilation" is LLM extraction, and the "build artifact" is a set of RDF triples.

### Ingest gate

See *Editorial policy gate*.

### Instructor

An open-source Python library that patches LLM clients (OpenAI, Anthropic, Ollama, etc.) to enforce structured output via Pydantic schemas. When riverbank's `instructor` extractor sends a request, Instructor intercepts the response, validates it against the `ExtractionResult` Pydantic model, and retries automatically if the model produced malformed JSON. The result is reliable structured extraction without writing bespoke output-parsing code.

### IRI

**Internationalized Resource Identifier** — the RDF standard's equivalent of a URL, used as the stable, globally unique identifier for entities, predicates, and graphs. In riverbank, every entity gets an IRI (e.g., `http://example.org/entity/Marie_Curie`), every predicate gets an IRI (e.g., `schema:birthDate`), and every named graph gets an IRI (e.g., `http://riverbank.example/graph/trusted`). IRIs are what make RDF data interoperable: two systems using the same IRI are talking about the same thing, regardless of what language or format they use.

---

## K

### Knowledge compiler

The core metaphor for riverbank. A software compiler transforms human-readable source code into machine-executable code. A knowledge compiler transforms human-readable documents into machine-queryable structured facts. Just as a compiler catches errors, enforces type constraints, and produces reproducible output, riverbank catches fabrications, enforces schema constraints, and produces a governed, citable knowledge graph.

### Knowledge graph

A structured representation of facts as a network of entities connected by typed relationships. In riverbank, every fact is stored as an RDF triple: a subject (an entity), a predicate (a relationship type), and an object (another entity or a value). The full set of triples forms a graph where entities are nodes and predicates are labelled edges. Storing knowledge as a graph rather than as text or tables makes multi-hop reasoning, provenance tracking, and ontology-driven validation straightforward.

### Knowledge-prefix adapter

A feature that, before each extraction call, retrieves the local neighbourhood of already-known entities from pg-ripple and injects it into the extraction prompt as a "KNOWN GRAPH CONTEXT" block. This means the LLM extracting a new fragment sees what the system already knows about the entities in that fragment — improving consistency, reducing duplicate entities, and decreasing contradictory extractions across documents.

---

## L

### Label Studio

An open-source data labelling platform that riverbank integrates with for human review of low-confidence extractions. When `riverbank review queue` runs, it pushes borderline triples to a Label Studio project where human reviewers can accept or reject each one. Accepted triples get promoted to the trusted graph; rejected triples are quarantined. Reviewer decisions also flow back into the few-shot example bank, enriching future extraction runs.

### Langfuse

An open-source LLM observability platform that riverbank uses to trace every LLM call. Each extraction run records its Langfuse trace ID, which links to a detailed view of the prompt sent, the response received, the token counts, and the latency. This is invaluable for debugging extraction quality — you can see exactly what the model was asked, exactly what it said, and exactly how much it cost.

### Literal

In RDF terminology, a value that is not an entity IRI but a concrete datum: a string, a number, a date, a boolean. For example, in the triple `ex:Marie_Curie schema:birthDate "1867-11-07"^^xsd:date`, the object is a date literal. riverbank normalises literals before writing: strings are lowercased and trimmed, dates are converted to ISO 8601 canonical form, and duplicate literals (same value, different casing) are deduplicated in favour of the highest-confidence instance.

### Lint

The process of running automated quality checks against the compiled knowledge graph. `riverbank lint --shacl-only` runs SHACL shapes against the trusted graph and produces a numeric quality score. If the score falls below the profile's threshold, the command exits non-zero — making the lint step suitable as a CI gate that fails the build when knowledge quality degrades.

### LLM (Large Language Model)

A neural network trained on large amounts of text that can generate, summarise, translate, and structure text. In riverbank, the LLM is the extraction engine: it reads a text fragment and produces structured RDF triples. riverbank works with any OpenAI-compatible LLM endpoint, including local models via Ollama, and hosted models from OpenAI, Anthropic, and others.

---

## M

### MediaWiki API

The REST API that Wikipedia exposes for programmatic access to article content. riverbank's `WikipediaClient` uses this API to download article text as Markdown, which is then cached locally. The `evaluate-wikidata` command relies on the MediaWiki API for its article fetch pipeline.

### Migration

A versioned, incremental change to the database schema, recorded as a Python script and managed by Alembic. When `riverbank init` runs, it applies any pending migrations in order, bringing the `_riverbank` catalog schema to the current version. Migrations run automatically on upgrade — you never need to write SQL by hand to update the catalog after a riverbank version bump.

### Model ensemble

A configuration where multiple LLM models extract the same fragment independently, and their results are merged. riverbank supports `weighted_merge` (each model's triples are weighted by its configured weight, and consolidated via noisy-OR) and `majority_vote` (a triple is accepted only if a majority of models agree on it). Ensembles increase extraction accuracy at the cost of higher LLM spend.

### Multi-tenancy

The ability to run multiple isolated tenants — separate organisations, teams, or projects — on a single riverbank deployment, with strict data isolation. Each tenant's sources, fragments, runs, and knowledge graph facts are scoped to that tenant via PostgreSQL Row-Level Security. One tenant cannot read or write another's data, even if they share the same database. Tenant lifecycle is managed via `riverbank tenant create/suspend/delete`.

---

## N

### Named graph

An RDF feature that organises triples into labelled collections identified by IRIs. riverbank uses named graphs to separate concerns:

| Graph IRI | Contents |
|-----------|---------|
| `graph/trusted` | High-confidence, quality-validated facts |
| `graph/tentative` | Plausible but not yet confirmed facts, accumulating evidence |
| `graph/draft` | Low-confidence facts pending human review |
| `graph/inferred` | Facts derived by OWL 2 RL or SPARQL CONSTRUCT rules |
| `graph/vocab` | SKOS concept vocabulary (canonical entity IRIs) |
| `graph/human-review` | Decisions from human reviewers in Label Studio |

### Negative knowledge

An explicit record that a fact is confirmed *absent*, not merely unobserved. Stored as `pgc:NegativeKnowledge` triples, negative knowledge is produced when an absence rule finds that a predicate it expects is missing from a fragment. The distinction matters: "no error-handling path found" as negative knowledge is a positive assertion about absence; an empty query result is just silence.

### Noise section filtering

A preprocessing feature that asks the LLM to identify headings that are pure boilerplate — navigation bars, disclaimers, legal notices, change logs — and marks those sections for skipping. Fragments under a boilerplate heading are never sent to the extraction LLM, saving one full extraction call per boilerplate fragment without any loss of knowledge quality.

### Noisy-OR

The formula used to consolidate confidence scores when the same fact is extracted multiple times from different fragments: $c_{final} = 1 - \prod_i (1 - c_i)$. The name comes from the analogy with a noisy logic gate: if two independent sensors each have a 60% chance of detecting a signal, the probability that *at least one* detects it is $1 - (1-0.6)^2 = 0.84$. Applied to triple extraction, independent corroboration from multiple fragments dramatically increases consolidated confidence — as it should, because genuinely true facts tend to appear in multiple places.

---

## O

### Ollama

An open-source tool for running large language models locally, without an API key or cloud account. riverbank uses Ollama as its default LLM backend in development and CI. Ollama serves any supported model (Llama, Gemma, Mistral, Phi, etc.) via an OpenAI-compatible REST API on `localhost:11434`, so switching between a local Ollama model and a hosted OpenAI model requires only a config change.

### Ontology

A formal description of the concepts and relationships in a domain — the vocabulary that the knowledge graph uses. In riverbank, the `pgc:` ontology defines the classes and properties that the system uses internally (provenance records, epistemic status, etc.). User-defined ontologies (expressed as OWL Turtle files) define the domain concepts and predicates for a specific corpus. Ontology files live in the `ontology/` directory; the `allowed_predicates` and `allowed_classes` fields in a compiler profile enforce ontology conformance at extraction time.

### OWL (Web Ontology Language)

A W3C standard for expressing formal ontologies in RDF. riverbank's `run-owl-rl` command applies OWL 2 RL (a tractable, forward-chaining subset of OWL) to infer new facts from existing ones: if `owl:inverseOf` links two predicates, a triple using one implies a triple using the other; `rdfs:subClassOf` transitivity chains automatically. Inferred triples are written to `graph/inferred` and never contaminate the asserted evidence base.

### OWL `sameAs`

An RDF/OWL property declaring that two IRIs refer to the same real-world entity. When riverbank's entity deduplication pass identifies two entity IRIs that are likely the same (based on embedding similarity or explicit merger), it writes `<ex:Marie_Curie> owl:sameAs <ex:MarieCurie>`. SPARQL queries that use reasoning will treat both IRIs as equivalent. The `riverbank entities merge` command performs an explicit, supervised `sameAs` assertion.

---

## P

### Parser

The plugin that converts a raw source file into a normalised text representation with structural metadata (heading positions, paragraph boundaries). The `markdown` parser handles Markdown files; the `docling` parser handles PDF, DOCX, and HTML. Parsers are the first stage of the pipeline — their output is what the fragmenter operates on.

### Permissive extraction

An extraction mode (`extraction_strategy.mode: permissive`) that asks the LLM to extract facts at four confidence tiers — EXPLICIT (0.9–1.0), STRONG (0.7–0.9), IMPLIED (0.5–0.7), and WEAK (0.35–0.5) — rather than only extracting facts it is highly certain about. Permissive extraction dramatically increases triple yield, especially for implied relationships that a conservative prompt would silently skip. The lower-confidence triples route to the tentative graph rather than trusted, preserving them for later corroboration.

### pg-ripple

The PostgreSQL extension that provides riverbank's knowledge store. pg-ripple adds a full RDF triple store inside PostgreSQL with SPARQL 1.1 query support, SHACL validation, Datalog inference, OWL 2 RL reasoning, vector search via pgvector, and GraphRAG export. Storing the knowledge graph inside PostgreSQL (rather than a separate graph database) is a deliberate architectural choice: it means the graph is transactionally consistent with the catalog, accessible via standard SQL tooling, and manageable with familiar backup and operations practices.

### pg-trickle

The PostgreSQL extension that provides incremental view maintenance for riverbank. pg-trickle keeps derived artifacts — quality scores, entity pages, topic indices, embedding centroids — up to date using a DBSP-inspired differential dataflow engine. When triples change, pg-trickle computes only the *difference* and applies it to affected views, rather than recomputing views from scratch. Its `IMMEDIATE` refresh mode keeps SHACL score gates current within the same transaction as the graph write.

### pg-tide

A standalone Rust binary that bridges pg-trickle's stream tables with external messaging systems. When compiled knowledge changes, pg-trickle computes the semantic diff; pg-tide delivers those diff events to whatever downstream systems are listening — Kafka, NATS JetStream, Redis Streams, SQS, RabbitMQ, HTTP webhooks, and more. Configuration is via SQL, not config files.

### pgvector

A PostgreSQL extension that adds vector storage and similarity search to standard PostgreSQL tables. riverbank uses pgvector to store entity label embeddings (for deduplication), fragment embeddings (for semantic chunking), and document summary embeddings (for corpus clustering). Keeping vectors in PostgreSQL alongside the knowledge graph means all similarity queries are transactionally consistent with the graph data.

### Plugin

An extension to the riverbank pipeline registered via Python entry points. Plugins can add new parsers (document formats), fragmenters (splitting strategies), extractors (LLM backends), connectors (source systems), or reviewers (human-review interfaces). Installing a plugin package makes it immediately available to the pipeline — no changes to riverbank core code required. This is the same mechanism used by pytest plugins and Singer taps.

### Precision

In the context of extraction quality: the fraction of extracted triples that are actually correct. If riverbank extracts 100 triples and 85 are verified as true, precision is 0.85. High precision means the system rarely makes things up; it does not say anything about what was missed. See also: *Recall*, *F1 score*.

### Predicate

In RDF, the middle term of a triple — the relationship between subject and object. Predicates are IRIs from a controlled vocabulary (an ontology). For example, `schema:birthDate`, `schema:memberOf`, or `pgc:confidence` are predicates. riverbank's `allowed_predicates` field in a compiler profile enforces that the LLM only uses predicates from a declared list, preventing vocabulary drift.

### Predicate normalization

The process of identifying near-duplicate predicates that express the same relationship under different names — for example, `ex:founded_in`, `ex:wasFoundedIn`, and `ex:foundingYear` — and writing `owl:equivalentProperty` links between them. The `riverbank normalize-predicates` command clusters predicates by embedding similarity and maps non-canonical variants to their canonical equivalents, reducing predicate vocabulary bloat by 30–50%.

### Preprocessing

An optional pipeline stage that runs *before* fragmentation, making one or two LLM calls per document (not per fragment) to produce a structured document summary and an entity catalog. These are then injected into every fragment's extraction prompt for that document, giving the extraction LLM entity-aware context it would otherwise lack. The cost is amortised across all fragments: for a 20-fragment document, two preprocessing calls replace the equivalent of many fragments' worth of drift and hallucination.

### Profile

See *Compiler profile*.

### Promote-tentative

The explicit CLI command (`riverbank promote-tentative`) that moves facts from the tentative graph to the trusted graph when their consolidated confidence has crossed the trusted threshold. Promotion is never automatic — it requires a deliberate `--dry-run` review before committing. Each promotion event is recorded as a `pgc:PromotionEvent` provenance record, preserving the full history of how a fact moved from tentative to trusted.

### Property alignment

In the Wikidata evaluation context, a mapping table that translates between Wikidata's numeric property identifiers (like `P569` for date of birth) and riverbank's human-readable predicate IRIs (like `schema:birthDate`). The alignment table covers 50+ Wikidata properties and is what makes automated precision/recall calculation against Wikidata ground truth possible.

### PROV-O

The W3C provenance ontology. riverbank uses PROV-O to express the origin of every compiled fact: `prov:wasDerivedFrom` links a triple to its source fragment; `prov:wasAttributedTo` links it to the compiler profile that produced it; `prov:generatedAtTime` records when it was compiled. PROV-O provenance is what makes "trace this fact back to its source" a concrete operation rather than a vague aspiration.

---

## Q

### Quality gate

A checkpoint in the compilation pipeline (or in CI) that rejects output below a threshold. riverbank has two main quality gates: the **confidence gate** (per-triple, routing low-confidence triples to draft or tentative rather than trusted) and the **SHACL gate** (per-graph, failing the lint step if the aggregate quality score is below the profile threshold). Quality gates prevent degraded knowledge from accumulating silently in the graph.

---

## R

### RAG (Retrieval-Augmented Generation)

A common pattern for feeding document content to LLMs: at query time, find the most similar chunks of text and include them in the LLM prompt. RAG is fast to set up but has limits: chunks lose context, similarity is not the same as relevance, and the model re-interprets the same raw prose on every request. riverbank is a structured alternative: facts are compiled once into a knowledge graph and queried directly, rather than re-retrieved from raw text.

### Recall

In the context of extraction quality: the fraction of true facts that were actually extracted. If a document contains 100 true facts and riverbank extracted 60 of them, recall is 0.60. High recall means the system misses few facts; it does not say anything about whether the extracted facts are correct. See also: *Precision*, *F1 score*.

### RDF (Resource Description Framework)

The W3C standard data model that riverbank uses for its knowledge graph. RDF represents knowledge as a set of triples: subject–predicate–object. Every term in a triple is either an IRI (a globally unique identifier) or a literal (a concrete value). The simplicity of the triple model is what makes RDF graphs composable across systems and queryable with SPARQL.

### Rendered page

An entity page generated from the compiled knowledge graph by the `riverbank render` command. Rendering converts the structured triples about an entity into human-readable output: Markdown (for documentation sites), JSON-LD (for web publication with structured data markup), or HTML. Each rendered page is itself stored as a `pgc:RenderedPage` artifact in the graph, with dependency tracking so it can be regenerated automatically when its source facts change.

### Reviewer

A plugin that manages the human review loop. The built-in `file` reviewer writes low-confidence triples to a local YAML file for offline review. The `label_studio` reviewer integrates with the Label Studio annotation platform for team-based review workflows.

### Row-Level Security (RLS)

A PostgreSQL feature that enforces data isolation at the row level. When tenant RLS is activated via `riverbank tenant activate-rls`, every query against `_riverbank` catalog tables automatically filters to the current tenant's rows — even if the application forgets to add a `WHERE tenant_id = ...` clause. RLS is the security foundation for multi-tenant deployments: misconfigurations in application code cannot leak one tenant's data to another.

---

## S

### Safety cap

A configurable maximum number of triples that can be extracted from a single fragment (`extraction_strategy.safety_cap`). If the LLM produces more triples than the cap, the pipeline keeps the top-N by confidence and logs a warning. This prevents runaway token usage on unusually dense documents with permissive extraction, and catches cases where the LLM is hallucinating quantity.

### SBOM (Software Bill of Materials)

A machine-readable inventory of every software component and dependency in a system, analogous to the ingredients list on a food product. The `riverbank sbom` command generates a CycloneDX-format SBOM for the installed riverbank package, with optional CVE auditing (`--audit`). SBOMs are required by an increasing number of enterprise procurement processes and government regulations for software supply-chain security.

### Schema induction

The process of automatically proposing a domain ontology from the patterns observed in an initial, unconstrained extraction pass. `riverbank induce-schema` collects all unique predicates and entity types from the graph, computes frequency statistics, and asks the LLM to propose a minimal OWL ontology with class hierarchy, domain/range constraints, and cardinality rules. The proposal is written to `ontology/` for human review before a second extraction pass uses it as constraints. This removes the requirement for ontology expertise to get started — you can bootstrap a schema from your data.

### Semantic chunking

A fragmentation strategy that uses embedding similarity to find natural topic boundaries in a document, rather than splitting on heading markers. Each sentence is embedded; when cosine similarity between adjacent sentences drops sharply, a boundary is detected. The result is fragments that align with semantic units (topic shifts) rather than with arbitrary structural markers. Semantic chunking tends to produce fewer orphan triples — facts split across boundaries that belong together.

### Semantic diff

The structured representation of what changed in the knowledge graph between two compilation runs: which triples were added, which were removed, and which had their confidence scores updated. pg-trickle computes semantic diffs using differential dataflow; pg-tide delivers them to downstream systems. A semantic diff is far more useful than a raw database change log, because it expresses change at the knowledge level rather than the storage level.

### Source diversity scoring

A refinement to noisy-OR confidence consolidation that prevents a fact corroborated by many fragments of the *same* document from receiving the same boost as a fact corroborated by fragments from *different* documents. If five fragments all say the same thing because they're from the same document (possibly copied or templated), they count as one vote. Independent corroboration from five different documents counts as five votes. This prevents systematically repeated claims in a single source from crossing the trusted threshold through sheer repetition.

### SPARQL

The W3C query language for RDF knowledge graphs — the SQL of the graph world. SPARQL SELECT retrieves rows of matching data; SPARQL ASK returns a boolean; SPARQL CONSTRUCT generates new triples. riverbank exposes the compiled knowledge graph via `riverbank query <sparql>`, which sends the query to pg-ripple and returns results as a table, JSON, or CSV. Competency questions are SPARQL ASK queries.

### SPARQL CONSTRUCT rules

Profile-defined inference rules expressed as SPARQL CONSTRUCT queries that generate new triples from existing ones. `riverbank run-construct-rules` executes these rules and writes the results to `graph/inferred`. CONSTRUCT rules are transparent, auditable, and domain-specific — unlike black-box reasoners, every inferred triple can be traced back to the CONSTRUCT rule and the asserted triples that triggered it.

### SHACL (Shapes Constraint Language)

A W3C standard for expressing validation rules over RDF data. A SHACL shape says things like "every `pgc:Source` must have exactly one `schema:name`" or "every triple in the trusted graph must have a `pgc:confidence` ≥ 0.7". pg-ripple's `shacl_score()` function evaluates the proportion of triples that pass all applicable shapes and returns a number between 0.0 and 1.0. The SHACL score is riverbank's primary data quality metric.

### SKOS (Simple Knowledge Organisation System)

A W3C vocabulary for representing taxonomies, thesauri, and controlled vocabularies in RDF. riverbank uses SKOS for the vocabulary pass: before full extraction, a first pass extracts `skos:Concept` triples for named entities, establishing canonical preferred labels (`skos:prefLabel`) and alternate labels (`skos:altLabel`) for each entity. This is what enables the entity catalog and synonym ring mechanisms — the SKOS vocabulary is the authoritative mapping from surface form to canonical IRI.

### Source

A registered input document or data feed in the riverbank catalog. Every source has a stable IRI, a content hash, a last-modified timestamp, and an associated compiler profile. Sources are registered via `riverbank source` commands and can be associated with different profiles as extraction needs evolve.

### Synonym ring

The set of surface forms (labels and aliases) that all refer to the same canonical entity. If "Marie Curie", "Maria Skłodowska-Curie", and "Mme Curie" all appear in a corpus and are resolved to the same entity IRI, they form a synonym ring stored as `skos:altLabel` triples. The entity linker uses synonym rings to snap new mentions to canonical IRIs rather than minting fresh entities.

---

## T

### Tenant

An isolated organisational unit within a multi-tenant riverbank deployment. Each tenant has its own namespace of sources, fragments, runs, and knowledge graph facts, enforced at the PostgreSQL level via Row-Level Security. Tenants are created, suspended, and deleted via `riverbank tenant` commands.

### Tentative graph

The `graph/tentative` named graph where plausible but not-yet-confirmed facts accumulate. A triple enters the tentative graph when its confidence is between the `tentative_threshold` and the `trusted_threshold`. Over time, as the same fact is extracted from additional fragments, its consolidated confidence (via noisy-OR) may rise above the trusted threshold, at which point `riverbank promote-tentative` can move it to the trusted graph. Facts that never accumulate enough evidence are eventually archived by `riverbank gc-tentative`.

### Token budget manager

A profile setting (`max_input_tokens_per_fragment`) that caps the total token count of an assembled extraction prompt. When the prompt — system message, entity catalog, few-shot examples, corpus context, and fragment text — exceeds the budget, components are trimmed in priority order: few-shot examples first, then corpus context, then entity catalog entries, then the document summary. The fragment text is never truncated.

### Token efficiency

A set of profile-level optimisations that reduce LLM token consumption without sacrificing extraction quality: per-fragment entity catalog filtering (inject only entities that appear in the fragment), adaptive preprocessing skip (skip preprocessing for very short documents), Phase 2 pre-scan deduplication (reuse Phase 1 summaries), Ollama keep-alive prompt caching, noise section filtering, and compact output schema (short JSON keys). Together these deliver ~30% token reduction from the baseline.

### Triple

The fundamental unit of RDF data: a (subject, predicate, object) statement. In a knowledge graph, every fact is expressed as one or more triples. "Marie Curie was born on 7 November 1867" becomes: `ex:Marie_Curie schema:birthDate "1867-11-07"^^xsd:date`. Every compiled artifact in riverbank is a triple, annotated with confidence, evidence span, and provenance metadata.

### Trusted graph

The `graph/trusted` named graph containing high-confidence, quality-validated facts. Only facts whose confidence meets or exceeds the `trusted_threshold` (default 0.75) and that pass SHACL validation are written here. This is the authoritative query surface — the compiled knowledge graph that downstream applications read.

---

## V

### Verification pass

An optional post-extraction stage (`riverbank verify-triples`) where low-confidence triples are re-evaluated by a second LLM call. The second call is phrased as a self-critique: "Given this source text, is this triple correct?" Confirmed triples receive a confidence boost; rejected triples are quarantined to `graph/draft`. Batching multiple triples into a single verification call (via `verification.batch_size`) keeps the additional LLM cost manageable.

### Vocabulary pass

An optional first-pass extraction mode (`run_mode_sequence: [vocabulary, full]`) that extracts only `skos:Concept` triples into the `graph/vocab` named graph before the full extraction pass. The vocabulary pass establishes canonical entity IRIs before relationship extraction begins, so that the full pass can reference consistent entities rather than creating duplicates. It is the RDF equivalent of a linking step before code execution.

---

## W

### Wikidata

A free, collaborative knowledge base maintained by the Wikimedia Foundation containing over 1.65 billion human-curated statements about people, places, organisations, works, and concepts. Each statement is backed by at least one reference and expressed in a structured form (item → property → value). riverbank uses Wikidata as an external validation ground truth: the `evaluate-wikidata` command compares riverbank's extracted triples against Wikidata's statements for the same Wikipedia articles, producing an objective measure of precision, recall, and calibration.

### Worker

The riverbank process that runs the compilation pipeline. A single worker processes one fragment at a time within a run; multiple workers can run in parallel across different sources, coordinated by fragment-level advisory locks that prevent duplicate extraction. Workers are stateless between runs — all persistent state lives in PostgreSQL.

---

## X

### xxh3_128

The hash function riverbank uses to detect fragment changes. xxh3_128 is an extremely fast non-cryptographic hash that produces a 128-bit (16-byte) digest. "Non-cryptographic" means it is not suitable for security purposes, but it is highly collision-resistant for content change detection — two fragments with the same xxh3_128 hash can be treated as identical with very high confidence. The hash is computed in microseconds, making it practical to hash every fragment on every ingest run.
