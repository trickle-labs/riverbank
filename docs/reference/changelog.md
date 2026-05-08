# Changelog

All notable changes to riverbank, organized by release.

## Unreleased

- LLM-based statement fragmentation (`llm_statement` fragmenter) with configurable distillation levels (`default`, `essential`, `minimal`)
- Batch extraction: groups multiple fragments into a single LLM call via `extraction_strategy.batch_size` in the profile
- `direct` fragmenter for pre-split corpora
- SAVEPOINT-based handling of PostgreSQL extension creation in migrations to prevent transaction abort

## v0.15.1 — Extraction improvement loop

- Per-property recall gap analysis: `riverbank recall-gap-analysis --threshold`
- Extraction prompt tuning from false-positive/false-negative patterns: `riverbank tune-extraction-prompts`
- 200+ manual novel-discovery annotations in `eval/novel-discovery-annotations.yaml`
- Published evaluation methodology and benchmark results in `docs/reference/evaluation-methodology.md`
- Evaluation profile YAML (`wikidata-eval-v1`) committed to `examples/profiles/`

## v0.15.0 — Wikidata evaluation framework

- `riverbank evaluate-wikidata --article <title|url>` — single-article evaluation with hybrid caching
- `riverbank evaluate-wikidata --dataset <path> --profile <name>` — batch mode over 1,000-article benchmark
- 1,000-article benchmark dataset across 7 domains in `eval/wikidata-benchmark-1k.yaml`
- Wikipedia → Markdown download pipeline with local hybrid cache (`.riverbank/article_cache/`)
- Wikidata SPARQL ground-truth fetcher with statement filtering
- Property alignment table mapping 50+ Wikidata P-ids to riverbank predicate patterns
- Entity resolution: sitelink → label matching → context disambiguation
- Scoring pipeline: precision, recall, F1, confidence calibration (Pearson ρ), novel discovery rate
- Per-domain and per-property breakdowns in JSON report; calibration curve output

## v0.14.0 — Structural improvements and reasoning

- Constrained decoding for Ollama backends (grammar-constrained JSON via `format` parameter)
- Semantic chunking: embedding-based boundary detection, fragments align with topic transitions
- SHACL shape validation against `pgc-shapes.ttl`; CLI: `riverbank validate-shapes`
- SPARQL CONSTRUCT rules: profile-defined inference, results written to `graph/inferred`
- OWL 2 RL forward-chaining via owlrl; CLI: `riverbank run-owl-rl`
- `riverbank run-construct-rules` command

## v0.13.1 — Extraction feedback loops

- Auto few-shot expansion: `riverbank expand-few-shot` samples high-confidence triples post-ingest
- Semantic few-shot selection: `FewShotInjector` embeds fragment and examples, selects by cosine similarity
- Batched verification: `VerificationPass` groups low-confidence triples into batches (configurable `batch_size`)
- Knowledge-prefix adapter: `riverbank build-knowledge-context` injects local graph neighbourhood as KNOWN GRAPH CONTEXT

## v0.13.0 — Entity convergence

- Predicate normalization: `riverbank normalize-predicates` clusters near-duplicate predicates, writes `owl:equivalentProperty`
- Incremental entity linking with synonym rings; `riverbank entities list` and `riverbank entities merge`
- `skos:altLabel` triples for entity surface variants; `pg:fuzzy_match()` validates synonymy
- Contradiction detection and demotion: `riverbank detect-contradictions` for functional predicates
- `pgc:ConflictRecord` provenance for detected contradictions
- `riverbank induce-schema` — cold-start OWL ontology proposal from graph statistics
- Automatic tentative cleanup: `riverbank gc-tentative --older-than <days>`; `tentative_ttl_days` in profile
- Quality regression tracking: `riverbank benchmark --golden --fail-below-f1`

## v0.12.1 — Permissive extraction phase B

- Confidence consolidation (noisy-OR): $c_{final} = 1 - \prod_i (1 - c_i)$ across fragments
- Source diversity scoring: corroboration from the same document counts as one vote
- `riverbank promote-tentative` — explicit CLI promotion with `--dry-run`; writes `pgc:PromotionEvent`
- Functional predicate hints in profile YAML (`predicate_constraints.max_cardinality: 1`)
- `riverbank explain-rejections` — show discarded triples grouped by reason
- `triples_promoted` stat tracked in run records

## v0.12.0 — Permissive extraction

- Ontology-grounded extraction: `allowed_predicates` and `allowed_classes` in profile; pre-write structural filtering
- CQ-guided extraction: competency questions injected as EXTRACTION OBJECTIVES
- `extraction_strategy.mode: permissive` — tiered confidence guidance (EXPLICIT / STRONG / IMPLIED / WEAK)
- Per-triple confidence routing: ≥ 0.75 trusted, 0.35–0.75 tentative, < 0.35 discarded
- `tentative_graph` field in `CompilerProfile`; `graph/tentative` named graph
- Extraction safety cap: `max_triples_per_fragment` in profile; `triples_capped` stat
- Two-tier query model: `riverbank query` (trusted only) and `--include-tentative`
- Coreference resolution before fragmentation (`preprocessing.coreference: llm | spacy | disabled`)
- Overlapping fragment windows (`overlap_sentences` in fragmenter block)
- Literal normalization (strings, dates ISO 8601, IRIs) with deduplication
- Compact output schema for local models (short JSON keys, ~300 fewer output tokens per fragment)
- Token budget manager (`max_input_tokens_per_fragment` in profile)

## v0.11.1 — Token efficiency

- Per-fragment entity catalog filtering by mention presence (`token_optimization.filter_entities_by_mention`)
- Adaptive preprocessing skip for small documents (`skip_preprocessing_below_chars`)
- Phase 2 pre-scan deduplication: Phase 1 summaries reused by Phase 2 corpus analyser
- Ollama keep-alive prompt caching (`keep_alive: "5m"`)
- Noise section filtering: LLM-identified boilerplate headings skipped before extraction

## v0.11.0 — Preprocessing and post-processing

- LLM document preprocessing (Phase 1): `DocumentPreprocessor` generates structured summary and entity catalog; injected into extraction prompts
- Corpus-level clustering (Phase 2): `CorpusPreprocessor` embeds summaries, K-Means clusters, per-cluster context in prompts
- Few-shot injection: `FewShotInjector` loads golden examples from `examples/golden/`, configurable per profile
- `riverbank validate-graph` — competency-question coverage via SPARQL ASK; exits non-zero below threshold
- Entity deduplication (Post-1): `riverbank deduplicate-entities --threshold --dry-run`
- Self-critique verification (Post-2): `riverbank verify-triples --profile --graph --dry-run`
- Separate token tracking for preprocessing calls (`preprocessing_prompt_tokens`, `preprocessing_completion_tokens`)

## v0.10.0 — Release infrastructure

- PyPI package: `pip install riverbank`; optional extras `[ollama]`, `[docling]`, `[labelstudio]`
- `riverbank sbom` — CycloneDX SBOM generation; exits non-zero if any dependency has a known CVE
- Documentation site auto-publish on every version tag via GitHub Actions

## v0.9.0 — Multi-tenant and prose generation

- Multi-tenant lifecycle: `riverbank tenant create/suspend/delete/list/activate-rls`
- Row-Level Security (RLS) on all `_riverbank` catalog tables
- GDPR erasure via `--gdpr` flag (cascading provenance-graph deletion)
- Federated compilation: `riverbank federation register/compile`
- Rendering engine: `riverbank render` (Markdown, JSON-LD, HTML)
- `pgc:RenderedPage` artifacts with dependency tracking
- Tenant-scoped named graph prefixes

## v0.8.0 — Epistemic layer

- Negative knowledge (`pgc:NegativeKnowledge`) with absence rules in profiles
- Argument graphs (`pgc:ArgumentRecord` with claim, evidence, objection, rebuttal)
- Assumption registry (`pgc:AssumptionRecord`)
- Full epistemic status layer (all 9 values)
- Model ensemble compilation (`weighted_merge`, `majority_vote`)
- `riverbank explain-conflict` command
- Coverage maps (`pgc:CoverageMap`)
- `procedural-v1` compiler profile

## v0.7.0 — Production hardening

- Helm chart (`helm/riverbank/`)
- Multi-replica advisory locking (fragment-level, no duplicate work)
- Circuit breakers per LLM provider (via `aiobreaker`)
- Prometheus metrics endpoint (`/metrics`)
- HashiCorp Vault secret management (via `hvac`)
- Kubernetes health probes
- Pod annotations for Prometheus scraping
- ServiceMonitor for operator-based scraping

## v0.6.0 — Quality gates and review

- Label Studio integration (`riverbank review queue/collect`)
- Active-learning review queue (centrality × uncertainty ranking)
- Example bank: review decisions become few-shot examples
- Langfuse evaluation integration
- Full lint pass: SHACL + SKOS integrity + `pgc:LintFinding` triples
- Nightly lint Prefect flow
- SHACL score history tracking
- OpenTelemetry tracing setup

## v0.5.0 — Multi-format and vocabulary

- Docling parser (PDF, DOCX, HTML)
- SKOS vocabulary pass (`--mode vocabulary`)
- `pg:skos-integrity` shape bundle
- Thesaurus-aware query expansion (`--expand`)
- `owl:sameAs` fuzzy match suggestions in `riverbank explain`
- `run_mode_sequence` field in profiles
- Named entity recognition (NER) for entity linking

## v0.4.0 — Incremental compilation

- Artifact dependency graph (`_riverbank.artifact_deps`)
- `riverbank explain` command
- `riverbank recompile` command (bulk reprocessing)
- Semantic diff events via pg-trickle
- Audit trail (`_riverbank.audit_log`)
- Tenant ID column scaffolding (pre-RLS)
- Filesystem connector plugin

## v0.3.0 — MVP completion

- `riverbank query` — SPARQL SELECT/ASK execution
- `riverbank runs` — run inspection with Langfuse deep-links
- `riverbank lint --shacl-only` — SHACL quality gate
- Cost accounting (prompt tokens, completion tokens, USD estimate)
- Competency questions in profiles (CI gate)
- Golden corpus test suite

## v0.2.0 — Core ingestion

- Markdown parser
- Heading fragmenter
- NoOp extractor (CI/testing)
- Instructor extractor (real LLM extraction)
- Editorial policy gate
- Hash-based fragment deduplication (`xxh3_128`)
- SHACL validation (trusted vs. draft routing)
- PROV-O provenance edges
- `riverbank ingest` command
- `riverbank profile register` and `riverbank source set-profile`

## v0.1.0 — Skeleton

- Docker Compose stack (PostgreSQL, pg-tide, Ollama, Langfuse)
- `riverbank version`, `riverbank config`, `riverbank health`
- `riverbank init` (Alembic migrations)
- Plugin discovery via entry points
- Pydantic Settings configuration
