# Ontology Pipeline Ideas — Lessons from Jessica Talisman's Work

> **Date:** 2026-05-05  
> **Source:** Jessica Talisman's Substack "[Intentional Arrangement](https://jessicatalisman.substack.com/)" and her guest post on [Modern Data 101](https://moderndata101.substack.com/p/the-ontology-pipeline-refresh)  
> **Scope:** Deep analysis of how the Ontology Pipeline® framework, and Talisman's broader body of work on semantic knowledge management, apply to the riverbank project  
> **Related:** [riverbank.md](riverbank.md) §2.2, [ROADMAP.md](../ROADMAP.md)

---

## 1. Executive summary

Jessica Talisman's Ontology Pipeline® is a staged methodology for constructing semantic knowledge management systems, moving iteratively from controlled vocabularies → metadata standards → taxonomies → thesauri → ontologies → knowledge graphs. Her broader Substack writing covers process knowledge management, the thesaurus as "knowledge graph lite", the context problem in AI token economics, concept models vs ontologies, metadata as a data model, and governance as a living engineering discipline.

Riverbank already cites the Ontology Pipeline as its "output quality contract" (§2.2). This report goes further: it identifies **specific, actionable ideas** from Talisman's full body of work that riverbank can exploit, many of which are not yet reflected in the current plans.

---

## 2. Key articles surveyed

| Article | Date | Key thesis |
|---|---|---|
| The Ontology Pipeline® | May 2025 | Staged, iterative framework: CV → metadata → taxonomy → thesaurus → ontology → KG |
| From Metadata to Meaning | May 2025 | Knowledge infrastructure as an organizational program; AI depends on structured knowledge |
| The Mighty Thesaurus, Part I | Jul 2025 | SKOS thesauri as lightweight symbolic AI; "Knowledge Graph Lite" |
| Metadata as a Data Model, Part I | Aug 2025 | Metadata must be treated as a holistic system, not an appendage |
| Controlled Vocabularies, Part I | Oct 2025 | CV build process: purpose → concept discovery → reconciliation → governance |
| Concept Models and Ontologies | Nov 2025 | Distinction between sketch (concept model) and blueprint (ontology); competency questions |
| Process Knowledge Management I–IV | Dec 2025 | Elicitation, formalisation, and encoding of tacit procedural knowledge |
| Context Graphs and Process Knowledge | Jan 2026 | PKO ontology for decision traces; process knowledge as the missing layer for "context graphs" |
| Relationships and Knowledge Systems | Jan 2026 | Organisational consequences of how we model connections |
| Where Provenance Ends, Knowledge Decays | Feb 2026 | AI without provenance produces decay; provenance is structural, not cosmetic |
| Ontology, Part I | Feb 2026 | Clearing confusion: what qualifies as an ontology; OWL/RDF are tools not ontologies |
| A Practitioner's Guide to Taxonomies, Part I | Jan 2026 | Taxonomy as low-fidelity semantic structure with high ROI; prep work before building |
| The Internet of Probability | Mar 2026 | LLMs as probability engines; the need for structured knowledge to ground them |
| The Context Problem | Mar 2026 | Token economics conflate capacity with coherence; neurosymbolic structures solve the real problem |
| The Ontology Pipeline™, Refresh | Mar 2026 | Updated pipeline with governance + AI partnership as explicit new disciplines |

---

## 3. The complementarity thesis — strengthened

Riverbank §2.2 already states:

> Karpathy without Talisman produces a compiled artifact of unknown structural quality. Talisman without Karpathy produces a methodology that does not scale to LLM-speed ingestion. Together they define both the engineering pattern and the quality contract.

The deeper reading confirms this and reveals a **third axis** from the Refresh article: **governance as a living engineering discipline**. The triad is:

| Axis | Source | Riverbank role |
|---|---|---|
| Engineering pattern | Karpathy (compiler analogy) | The pipeline architecture: ingest → compile → validate → publish |
| Quality contract | Talisman (Ontology Pipeline) | SHACL shapes, SKOS integrity, layered named graphs, competency questions |
| Living governance | Talisman (Refresh + Context Graphs) | Drift detection, audit trail, provenance enforcement, correction loops |

Riverbank's §7.10.1 already contrasts "people-centric" vs "system-centric" governance. What the Refresh article adds is the explicit requirement that governance must be **dynamic** — "the day an ontology is deployed is the day it starts to drift." Riverbank handles this with daily SHACL snapshots, CONSTRUCT writeback drift detection, and the lint flow. This is already well-aligned.

---

## 4. Ideas to exploit fully

### 4.1 The vocabulary pass as first-class pipeline stage

**Source:** Controlled Vocabularies Part I; the original Ontology Pipeline.

**Talisman's key insight:** A controlled vocabulary is not merely a list of terms. It requires:
- One preferred label per concept
- Captured variants mapped to the canonical form
- A scope note (definition) pinning down meaning
- A stable identifier (URI)
- Light usage guidance (capitalisation, singular/plural)

**Current riverbank state:** The `run_mode_sequence` in compiler profiles supports `['vocabulary', 'full']`. The vocabulary pass "establishes a clean, disambiguated controlled vocabulary" before full extraction.

**Opportunities to go further:**

1. **Synonym ring extraction.** Talisman references ANSI Z39.19 synonym rings. Riverbank should have the vocabulary pass explicitly produce `skos:altLabel` triples for every discovered variant, not just prefer one label. The `pg:fuzzy_match()` function already exists — use it to *validate* that extracted alt-labels are truly synonymous by checking token-set-ratio against a threshold.

2. **Scope note enforcement as a quality gate.** Talisman insists that every term in a controlled vocabulary must have a definition. Riverbank's SHACL shapes already treat missing `skos:scopeNote` as a Warning. Consider promoting this to a **hard gate for high-centrality concepts** — if a concept has PageRank above a threshold and no scope note, it routes to `<review>` automatically. High-importance undefined concepts are the most dangerous kind.

3. **Vocabulary-first corpus analysis.** Before any LLM extraction, run a pre-pass that identifies candidate terms purely from corpus statistics (TF-IDF, co-occurrence). Feed these to the LLM as "terms to define" rather than asking the LLM to discover terms from scratch. This reduces hallucinated vocabulary items and grounds the LLM's work in actual corpus language — exactly what Talisman prescribes when she says "collect candidate terms from the language you already have: site content, search logs, customer tickets."

4. **Vocabulary deprecation policy.** Talisman asks: "Will the controlled vocabulary be deprecated or remain in use when the taxonomy is deployed?" Riverbank should support `owl:deprecated true` on vocabulary terms with a CONSTRUCT rule that propagates deprecation to any entity still using the deprecated term — flagging them for re-extraction.

---

### 4.2 The thesaurus layer as "Knowledge Graph Lite"

**Source:** The Mighty Thesaurus Part I.

**Key insight:** A SKOS thesaurus is technically a form of symbolic AI. It provides:
- Explicit concept hierarchies (`skos:broader`, `skos:narrower`)
- Associative relationships (`skos:related`)
- Equivalence links (`skos:exactMatch`, `skos:closeMatch`)
- Lightweight inference (transitive closures, symmetric relations)

**Why this matters for riverbank:** The thesaurus layer (`<thesaurus>` named graph in §7.5.1) is currently described but lacks operational emphasis. Talisman argues the thesaurus is the critical "knowledge graph lite" — it handles ambiguity resolution, near-term discovery, and query expansion without the overhead of full OWL ontologies.

**Opportunities:**

1. **Query expansion via thesaurus traversal.** When `sparql_from_nl()` translates a natural language question, pre-expand query terms using `skos:related` and `skos:altLabel` edges from the thesaurus layer. This gives the query planner synonym coverage that pure vector similarity might miss ("SSO" ↔ "Single Sign-On" ↔ "SAML authentication").

2. **Thesaurus-guided RAG context selection.** When `rag_context()` assembles context for an LLM response, include related concepts from the thesaurus as structured "nearby terms" — this provides the model with disambiguation context without consuming tokens on raw text. Per Talisman's point about context being relational structure, a thesaurus subgraph delivers more inferential signal per token than equivalent raw text.

3. **Automatic thesaurus maturation.** Implement a CONSTRUCT writeback rule that promotes repeated `skos:related` co-occurrences (concepts that appear together across many source fragments) into stronger `skos:broader`/`skos:narrower` candidates for human review. The thesaurus grows organically from corpus evidence.

4. **Cross-corpus alignment via `skos:exactMatch`.** When riverbank ingests multiple corpora (e.g., a company's internal docs + an industry standard), the thesaurus layer is the natural alignment surface. `skos:exactMatch` and `skos:closeMatch` links between the two vocabularies enable federated queries without full ontology alignment.

---

### 4.3 Metadata as a data model

**Source:** Metadata as a Data Model Part I.

**Key insight:** Metadata is not an appendage; it is a holistic system with elements categorised as STRUCTURAL (machine readability), DESCRIPTIVE (context), and ADMINISTRATIVE (maintenance/lineage). Metadata should be treated as a first-class data model woven into the fabric of digital ecosystems.

**Relevance to riverbank:** The `pgc:` ontology (pgc.ttl) already defines structural metadata for the compiler (Source, Fragment, Profile, Run, Synthesis). But Talisman's framework suggests this should be more explicitly layered:

1. **Structural metadata:** `pgc:fromFragment`, `pgc:byProfile`, `pgc:compiledAt` — already present.
2. **Descriptive metadata:** scope notes, topic labels, subject classifications of compiled artifacts. Currently these are extracted but not formally typed as descriptive metadata elements.
3. **Administrative metadata:** ownership, review status, version history, retention policy. Partially present in the audit log but not as a formal metadata schema.

**Opportunity:** Define an explicit metadata standard (in the Talisman sense) for riverbank artifacts. This becomes the contract that all extractors must populate. Express it as a SHACL node shape: every `pgc:Synthesis` must have structural metadata (fragment link, profile link, timestamp), should have descriptive metadata (at least one `skos:Concept` annotation), and may have administrative metadata (reviewer, expiry). This gives the SHACL score a principled basis in metadata theory rather than ad-hoc field requirements.

---

### 4.4 Process knowledge and decision traces

**Source:** Context Graphs and Process Knowledge; Process Knowledge Management series.

**Key insight:** Context graphs are fundamentally a knowledge management problem. They require:
- Formal distinction between procedures (specifications) and executions (instances)
- Semantic relationships enabling graph traversal and inference
- Temporal dimension (what was true when decisions were made)
- User feedback and error tracking that feeds back into the knowledge graph

**Relevance to riverbank:** Riverbank currently focuses on compiling *declarative* knowledge from documents. But many valuable enterprise corpora contain *procedural* knowledge: runbooks, SOPs, onboarding guides, incident responses, troubleshooting trees.

**Opportunities:**

1. **Procedural knowledge extraction profile.** Create a specialised compiler profile for procedural documents that extracts:
   - Steps and their sequence (`pko:nextStep`, `pko:previousStep`)
   - Decision points and branching logic (`pko:nextAlternativeStep`)
   - Required expertise/tools per step
   - Preconditions and postconditions
   
   This maps directly to the Procedural Knowledge Ontology (PKO) from Cefriel that Talisman describes.

2. **Execution trace ingestion.** When downstream systems execute procedures compiled by riverbank, feed execution traces back as source material. The compiler can then detect:
   - Steps that are frequently skipped (indicating the procedure is outdated)
   - Steps that generate frequent questions (indicating unclear instructions)
   - Deviation patterns (indicating undocumented alternatives)
   
   This creates the "continuous learning loop" Talisman describes.

3. **Decision trace as provenance.** Extend the `prov:` vocabulary in riverbank to support decision reasoning. When a compiled fact is the *result* of a decision (e.g., "we chose Redis because..."), store the reasoning chain as a first-class provenance record, not just the conclusion. This enables the "why was this allowed to happen?" queries that Foundation Capital identifies as the decisive asset for agentic AI.

---

### 4.5 The context problem — economic justification for riverbank

**Source:** The Context Problem (Mar 2026).

**Key insight:** The AI market charges for tokens (capacity) but delivers degraded coherence as context grows. Research shows:
- 80% decrease in token usage when graph-based retrieval replaces vector RAG
- Contradiction detection complexity reduced by 7× with structured knowledge
- Smaller models on structured subgraphs match larger models on raw text
- "Context rot" — performance degrades as input length grows, even on simple tasks
- Shuffled (random-order) context outperforms logically ordered raw text (!)

**This is riverbank's entire value proposition distilled into economic terms.** Talisman provides the market research and citations that justify the project's existence:

1. **Token cost reduction is measurable.** Riverbank should track and report token savings: compare the token cost of answering a query using `rag_context()` (compiled graph subgraph) vs the token cost of naive RAG (raw chunks). The 80% reduction figure from the GenAIK workshop gives a baseline expectation.

2. **Context rot immunity.** Because riverbank pre-compiles relationships into graph structure, the "context" passed to the LLM at query time is a small, semantically dense subgraph — not a growing raw text window. This makes riverbank queries immune to context rot by design. This should be a first-class marketing claim.

3. **Neurosymbolic positioning.** Talisman + Gartner (Data & Analytics Summit 2026) both identify composite/neurosymbolic AI as a defining future trend. Riverbank is precisely this: symbolic backbone (pg_ripple RDF/SHACL/Datalog) + neural pattern matching (LLM extraction and querying). Position the project explicitly in this frame.

4. **The credence good problem.** Talisman identifies AI output as a "credence good" — quality cannot be verified even after consumption. Riverbank's confidence scores, SHACL quality gates, provenance chains, and epistemic status labels provide exactly the **quality signal** that the market lacks. Every compiled artifact comes with a verifiable quality assessment. This is a differentiator.

---

### 4.6 Governance as engineering, not documentation

**Source:** The Ontology Pipeline Refresh (both versions).

**Key insight:** "Governance is the engineering practice that keeps an ontology coherent across change... Without a formal governance structure — versioning conventions, ownership protocols, change management processes, validation matrices — even a well-built ontology degrades."

Talisman specifically calls out:
- AI partnership: using AI to "surface candidates, flag inconsistencies, run reasoners, test SPARQL queries against competency questions"
- Competency questions as the design heuristic that AI-generated taxonomies always lack
- Coverage models as a governance tool

**Current riverbank state:** Already well-aligned. The audit log, SHACL gates, lint flow, competency questions in profiles, and coverage maps all implement governance-as-engineering.

**Opportunities to strengthen:**

1. **Governance dashboard.** Expose Talisman's five driving questions as operational metrics:
   - "What problems are you solving?" → coverage map heat map
   - "What is this system designed to answer?" → competency question pass rate
   - "Who can change what, when, how?" → audit log activity per operator/profile
   - "How can we collaborate across disciplines?" → review queue throughput
   - "How will you sustain this work?" → drift rate trend (SHACL score over time)

2. **AI-assisted governance.** The Refresh article explicitly endorses AI for "entity extraction, gap analysis, drafting candidate vocabularies for human review, and populating ontologies for validation." Riverbank already does all of these. But add: **AI-assisted competency question generation.** When a new source domain is ingested, have the LLM propose competency questions that the compiled graph should be able to answer. These become CI assertions.

3. **Versioned governance policies.** Just as compiler profiles are versioned, governance rules (SHACL shapes, Datalog bundles, editorial policies) should be versioned with the same audit-trail rigour. A change to a SHACL shape is a change to the quality contract — it should produce a changelog entry visible to operators.

---

### 4.7 Competency questions as the north star

**Source:** Concept Models and Ontologies; Ontology Pipeline Refresh.

**Key insight:** "Competency questions are a human-in-the-loop necessity, conducted in natural language, and are normally part of the ontology design process." Talisman insists: "If the profile cannot state [competency questions], the extraction schema is not ready."

**Current riverbank state:** Compiler profiles include competency questions as SPARQL `ASK`/`SELECT` assertions. The CI golden corpus gate runs them. `riverbank lint --check-coverage` surfaces unanswered questions.

**Opportunities to make this the central design tool:**

1. **Competency-question-driven profile creation.** When bootstrapping a new compiler profile, start with: "What questions must this knowledge base answer?" Generate competency questions first, then derive the extraction schema that would make those questions answerable. This inverts the common pattern of designing schema first and discovering gaps later.

2. **Coverage gap → source acquisition signal.** When a competency question cannot be answered, that gap should propagate as an actionable signal: "We need sources about X." This connects the knowledge system back to source acquisition strategy — precisely the "where are we blind?" capability in §8.7.

3. **Competency question evolution tracking.** As the domain evolves, new questions emerge that the original model cannot answer (exactly what Talisman warns about). Track which competency questions were added over time, which were retired, and which required schema changes — this becomes the operational history of how the knowledge domain evolved.

---

### 4.8 The validation matrix concept

**Source:** Ontology Pipeline (original); A Practitioner's Guide to Taxonomies.

**Key insight:** Taxonomies must be validated against structural integrity rules before deployment:
- No recursive loops in broader/narrower chains
- No conflicting relationship types (e.g., something is both broader AND exact-match of the same concept)
- Depth limits enforced
- Granularity decisions documented
- ISO 25964-1 and ANSI/NISO Z39.19 compliance

**Current riverbank state:** The `pg:skos-integrity` shape bundle catches cycles and conflicting matches. But Talisman's "validation matrix" concept is broader than individual SHACL shapes.

**Opportunity: Formal validation matrix as a queryable artifact.**

Define validation matrices as structured configuration (YAML or JSON) that declare:
- Maximum taxonomy depth per domain
- Required concept density (minimum concepts per branch)
- Orphan detection threshold (concepts with no broader term and no narrower terms)
- Polyhierarchy policy (allowed or prohibited per profile)
- Localisation requirements (which languages must have labels)

These map to SHACL shapes programmatically. The validation matrix becomes a **human-readable governance document** that generates machine-executable constraints — bridging Talisman's people-centric methodology with riverbank's system-centric enforcement.

---

### 4.9 The layered troubleshooting principle

**Source:** Ontology Pipeline (original) — knowledge graphs as layered systems.

**Key insight:** "The Ontology Pipeline naturally presents a layered knowledge graph, making it easier to troubleshoot broken logic while providing the control planes necessary to scale and extend the graph."

**Current riverbank state:** §7.5.1 already defines semantic-depth layers (`<vocab>`, `<taxonomy>`, `<thesaurus>`, `<ontology>`, `<trusted>`), each independently queryable and lintable.

**Opportunity to exploit this more aggressively:**

1. **Layer-specific quality metrics.** Report SHACL scores per layer, not just per graph. A declining vocabulary-layer score indicates term pollution. A declining taxonomy-layer score indicates structural degradation. A declining thesaurus-layer score indicates relationship drift. Each has different remediation actions.

2. **Layer-dependent inference scoping.** Datalog rules should declare which layers they read from. A rule that derives `skos:broader` transitive closures reads only from `<taxonomy>`. A rule that infers entity types reads from `<ontology>`. This prevents cross-layer contamination and makes reasoning chains auditable per-layer.

3. **Layer promotion ceremonies.** When a concept graduates from `<vocab>` to `<taxonomy>` (it gains broader/narrower relations), that promotion is an event. When it moves from `<taxonomy>` to `<thesaurus>` (it gains associative relations), that's another event. Track these promotions as first-class lifecycle events in the audit log. Over time, this shows the "maturation velocity" of the knowledge base.

---

### 4.10 The human-in-the-loop principle for AI partnership

**Source:** Ontology Pipeline Refresh; Context Graphs and Process Knowledge.

**Key insight:** "AI that generates a taxonomy wholesale, without human review, unable to validate against standards, missing design heuristics such as competency questions and coverage models — that AI is producing a liability disguised as an asset. AI that assists a trained semantic engineer in building a better ontology, faster, is just plain smart."

**Current riverbank state:** The Label Studio review queue, the draft/trusted graph separation, and the confidence-based routing all implement human-in-the-loop. But the *nature* of the human contribution could be more precisely scoped.

**Opportunities:**

1. **Human effort allocation based on Ontology Pipeline stages.** Different stages require different human expertise:
   - Vocabulary: domain experts validate definitions and synonym choices
   - Taxonomy: information architects validate hierarchy depth and structure
   - Thesaurus: linguists validate associative relationships and equivalences
   - Ontology: ontologists validate class hierarchies and property constraints
   
   The review queue should route items to appropriate reviewers based on which layer the item belongs to.

2. **Active learning focused on high-impact decisions.** Talisman emphasises that the hardest decisions in knowledge modelling are definitional: "difficulty articulating a definition is not a reason to proceed — it is a signal to stop and think." Riverbank's active learning queue should prioritise concepts where the LLM's scope note has low confidence or where multiple extraction attempts produced different definitions. These are the cases where human judgment adds the most value.

3. **Example bank as institutional memory.** The example bank in compiler profiles should explicitly store the *reasoning* behind modelling decisions, not just the decisions themselves. "We chose to model X as a narrower term of Y because..." This creates the process knowledge Talisman describes — the institutional memory of why the knowledge system is structured the way it is.

---

### 4.11 Knowledge infrastructure as a program

**Source:** From Metadata to Meaning.

**Key insight:** Knowledge infrastructure must be treated as a program, not a project. Its composite includes: Creators, Products, Distributors, Disseminators, and Users. It requires "continuous, cumulative learning loops."

**Relevance to riverbank:** Riverbank is a tool, not a program. But it can be designed to support the program model:

1. **Role-aware access and contribution.** Map Talisman's five roles to riverbank operations:
   - Creators → connector/source operators
   - Products → compiled artifacts (entity pages, summaries, Q&A pairs)
   - Distributors → pg-tide outbox → downstream systems
   - Disseminators → rendered pages, API responses, agent navigation
   - Users → query consumers, LLM agents
   
   Each role has different observability needs. The dashboard should provide role-specific views.

2. **Cumulative learning loops.** Riverbank already has the synthesis feedback loop (§9.5 — queries compound the knowledge base). Extend this with:
   - Query patterns that reveal vocabulary gaps feed back to the vocabulary pass
   - Unanswered questions feed back to source acquisition
   - Correction patterns feed back to extractor prompt tuning
   - Usage patterns feed back to tiered scheduling (Hot/Warm/Cold)

---

### 4.12 Provenance as structural, not cosmetic

**Source:** Where Provenance Ends, Knowledge Decays (Feb 2026).

**Key insight:** AI without provenance produces decay. Provenance is not optional metadata — it is the structural guarantee that knowledge can be verified, updated, and trusted over time.

**Current riverbank state:** Write-time citation grounding (§7.0) already enforces that every triple must have a `prov:wasDerivedFrom` edge. This is one of riverbank's strongest design decisions.

**Opportunity:** Make provenance the core differentiator in market positioning. Talisman's argument is that most RAG systems and AI-generated knowledge bases have no verifiable provenance — they are "probability engines" producing plausible but unverifiable outputs. Riverbank's provenance chain (source → fragment → evidence span → compiled artifact → confidence → epistemic status) is exactly what she argues the industry needs. Every compiled fact answers: "Where did this come from? How confident are we? What would invalidate it?"

---

## 5. New feature ideas derived from this research

### 5.1 Vocabulary health score

Implement a composite metric for the `<vocab>` layer:
- % of concepts with scope notes
- % of concepts with at least one alt-label
- Synonym ring completeness (detected variants mapped vs unmapped)
- Orphan term rate (terms not used in any compiled fact)
- Definition consistency (LLM check for contradictory scope notes)

Surface this as `riverbank lint --layer vocab --score` and trend it over time.

### 5.2 Taxonomy maturity progression

Track each concept's position in the Ontology Pipeline lifecycle:
- `pgc:maturityLevel "vocabulary"` → has preferred label and scope note
- `pgc:maturityLevel "taxonomy"` → has at least one broader/narrower relation
- `pgc:maturityLevel "thesaurus"` → has associative or equivalence relations
- `pgc:maturityLevel "ontology"` → is typed with a domain class and has property constraints

Report maturity distribution as a histogram. Set targets: "80% of high-centrality concepts should be at thesaurus level or above."

### 5.3 Context efficiency metric

Per query, compute and report:
- Tokens consumed via `rag_context()` (graph-based)
- Estimated tokens that naive RAG would consume for equivalent coverage
- Ratio = context efficiency gain

This directly validates Talisman's claim (backed by GenAIK workshop research) that graph-based retrieval delivers 80% token reduction.

### 5.4 Competency question coverage CI badge

In CI, after the golden corpus gate runs all competency questions:
- Report: X/Y questions answered correctly
- Badge: "Coverage: 94%" (like test coverage)
- Fail build if coverage drops below threshold

This makes the knowledge base's fitness-for-purpose as visible as code test coverage.

### 5.5 Process knowledge compiler profile template

Ship a built-in profile template for procedural documents that:
- Extracts step sequences with ordering relations
- Identifies decision points and branching
- Captures preconditions, tools, and expertise levels
- Links to the PKO ontology from Cefriel
- Generates "what happens if step X fails?" competency questions

---

## 6. Positioning and narrative

Talisman's work provides riverbank with a powerful narrative frame:

1. **The industry problem:** Organizations rush to knowledge graphs without foundational vocabulary hygiene. AI-generated taxonomies are "lists, not knowledge infrastructure." RAG systems hallucinate because they lack semantic grounding.

2. **Riverbank's answer:** A compiler that enforces the Ontology Pipeline's quality contract automatically, at LLM speed, with machine-executable governance. It doesn't skip the work — it accelerates it with AI partnership while enforcing the same standards a trained semantic engineer would demand.

3. **The economic argument:** Structured knowledge delivers 80% token cost reduction, 7× contradiction detection improvement, and immunity to context rot. Every dollar spent on compilation saves multiples at query time.

4. **The trust argument:** In a market of "credence goods" where AI output quality cannot be verified, riverbank's provenance chains, confidence scores, SHACL quality gates, and epistemic status labels provide the quality signal that buyers cannot get from raw LLM outputs.

5. **The governance argument:** "The day an ontology is deployed is the day it starts to drift." Riverbank treats governance as a living engineering discipline — automated, continuous, auditable — not a documentation exercise.

---

## 7. Gaps and future research

| Gap | Source of insight | Potential action |
|---|---|---|
| Localisation / multilingual vocabularies | Talisman's taxonomy guidelines question: "Will localisation be enabled?" | Support `skos:prefLabel` with language tags; SHACL shape requiring labels in configured languages |
| Polyhierarchy handling | Taxonomy practitioner's guide | Explicitly support or reject polyhierarchy per profile; document trade-offs |
| Vocabulary lifecycle ceremonies | Controlled Vocabularies Part I | Formal "term graduation" workflow: candidate → approved → in-use → deprecated |
| Cross-organisation alignment | Thesaurus as alignment surface | Support `skos:mappingRelation` for inter-organisational knowledge federation |
| Process knowledge elicitation tooling | Process Knowledge Management series | Integration with web forms (cf. Cefriel's `rapid-triples`) for expert knowledge capture |
| Token-cost-aware compilation scheduling | The Context Problem economics | Factor downstream token savings into compilation priority — expensive-to-query topics should compile first |

---

## 8. Summary of recommendations

1. **Strengthen the vocabulary pass** with corpus-statistics pre-analysis, synonym ring extraction, scope-note enforcement for high-centrality concepts, and deprecation propagation.

2. **Operationalise the thesaurus layer** for query expansion, RAG context assembly, automatic maturation, and cross-corpus alignment.

3. **Define a formal metadata standard** for compiled artifacts (structural/descriptive/administrative) expressed as SHACL node shapes.

4. **Add a procedural knowledge profile** for runbooks, SOPs, and process documents using PKO-aligned extraction.

5. **Track and report context efficiency** (token savings vs naive RAG) as a first-class operational metric.

6. **Implement validation matrices** as human-readable governance documents that generate SHACL constraints.

7. **Layer-specific quality metrics** and promotion tracking for the semantic-depth named graph architecture.

8. **Competency question coverage** as a CI badge alongside test coverage.

9. **Position riverbank** using Talisman's economic and trust arguments: neurosymbolic AI, context rot immunity, credence good quality signals.

10. **AI-assisted governance** — use LLMs to propose competency questions, flag definition inconsistencies, and surface coverage gaps, while keeping human judgment on modelling decisions.
