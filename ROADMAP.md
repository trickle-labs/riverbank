# riverbank Roadmap

> **Audience:** Product managers, stakeholders, and technically curious readers
> who want to understand what each release delivers and why it matters — without
> needing to read Python code or SQL specifications.
>
> **Dependencies:** riverbank is built on top of
> [pg-ripple](https://github.com/grove/pg-ripple) ≥ 0.98.0,
> [pg-trickle](https://github.com/grove/pg-trickle) ≥ 0.48.0, and
> [pg-tide](https://github.com/trickle-labs/pg-tide) ≥ 0.14.0.
> The implementation blueprint lives in
> [plans/riverbank-implementation.md](plans/riverbank-implementation.md);
> the strategy document lives in [plans/riverbank.md](plans/riverbank.md).

---

## Versions

### Skeleton and MVP (v0.1.x – v0.3.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.1.0 | Skeleton — `docker compose up` proves the deployment story: CLI scaffolding, catalog migrations, no-op extractor, Langfuse wired | **Done** | Small |
| v0.2.0 | MVP ingestion — Markdown corpus → triples with citation grounding, confidence scores, and fragment-level skip on re-ingest | **Done** | Large |
| v0.3.0 | MVP completion — `riverbank query`, `riverbank runs`, cost accounting, Langfuse traces, golden corpus CI gate | **Done** | Medium |

### Incremental Compilation (v0.4.x – v0.5.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.4.0 | Incremental compilation core — artifact dependency graph, `riverbank explain`, recompile flow, vocabulary pass, SKOS integrity shape bundle, `tenant_id` schema scaffold | **Done** | Large |
| v0.5.0 | Multi-format parsing and enrichment — Docling, spaCy NER + vocabulary lookup, fuzzy entity matching, embedding generation, Singer tap configuration (pg-tide ≥ 0.14.0) | **Done** | Large |

### Quality Gates and Review (v0.6.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.6.0 | Quality gates and human review loop — Label Studio integration, active-learning queue, example bank, Langfuse evals, lint flow, Prefect introduced | **Done** | Large |

### Production Hardening (v0.7.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.7.0 | Production hardening — Helm chart, multi-replica workers, Prometheus/Perses dashboards, secret management, circuit breakers, audit trail, bulk reprocessing | **Done** | Very Large |

### Advanced Epistemic Features (v0.8.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.8.0 | Epistemic layer — negative knowledge records, argument graphs, assumption registry, all 9 epistemic status labels, model ensemble, contradiction explanation, coverage maps | **Done** | Very Large |

### Multi-tenant and Prose Generation (v0.9.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.9.0 | Multi-tenant and rendering — tenant_id RLS activation, federated compilation (SPARQL SERVICE), Markdown/JSON-LD page rendering, streaming render via SSE | **Done** | Very Large |

### Release Infrastructure (v0.10.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.10.0 | Release infrastructure — PyPI package, `riverbank sbom` command, documentation site auto-publish on every release | **Done** | Medium |

### Extraction Quality (v0.11.x – v0.13.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.11.0 | Preprocessing & post-processing — LLM document preprocessing, corpus-level clustering, few-shot injection, validate-graph, entity deduplication, self-critique verification | **Done** | Large |
| v0.11.1 | Token efficiency — per-fragment entity catalog filtering, adaptive preprocessing for small documents, Phase 2 pre-scan deduplication, Ollama keep-alive prompt caching, noise section filtering | **Done** | Small |
| v0.12.0 | Permissive extraction (Phase A) — ontology-grounded & CQ-guided prompts, permissive extraction prompt, per-triple confidence routing, `graph/tentative`, two-tier query model, safety cap, pre-write structural filtering, overlapping fragments, literal normalization | **Done** | Large |
| v0.12.1 | Permissive extraction (Phase B) — confidence consolidation (noisy-OR) with source diversity scoring, `riverbank promote-tentative`, functional predicate hints, `riverbank explain-rejections` | **Done** | Medium |
| v0.13.0 | Entity convergence — predicate normalization, incremental entity linking with synonym ring extraction, `riverbank induce-schema`, contradiction detection, tentative cleanup, quality regression tracking | **Done** | Large |
| v0.13.1 | Extraction feedback loops — auto few-shot expansion, semantic few-shot selection, batched verification, knowledge-prefix adapter | **Done** | Medium |

### Structural Improvements & Stable Release (v0.14.x – v1.0.0)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.14.0 | Structural improvements — constrained decoding, semantic chunking, SHACL shape validation, SPARQL CONSTRUCT rules, OWL 2 RL inference | **Done** | Large |
| v1.0.0 | Stable — full API stability guarantee, signed artifacts, Helm chart stability, SLOs in CI | Planned | Medium |

### Wikidata Evaluation (v0.15.x)

| Version | Description | Status | Size |
|---|---|---|---|
| v0.15.0 | Wikidata evaluation framework — `riverbank evaluate-wikidata` command (single article or full dataset), 1,000-article benchmark dataset (7 domains), property alignment table, entity resolution pipeline, calibration curves, per-domain and per-property breakdowns | **Done** | Large |
| v0.15.1 | Extraction improvement loop — per-property recall gap analysis, extraction prompt tuning from failure modes, 200+ novel-discovery annotations, published evaluation methodology | **Done** | Medium |

### Adaptive Auto-Tuning (v0.16.x – v0.18.x)

> **Resequenced 2026-05-09:** The original plan placed measurement (Tier 1 curated
> ground truth) in v0.18.0, after the full diagnostics, A/B, and orchestration
> stack. This creates a fundamental problem — the `DiagnosticsEngine` rules for F1,
> precision, and recall are uncomputable without ground truth, so the entire stack
> would run blind on Tier 2/3 proxies for three releases. The resequencing pulls
> Tier 1 ground truth creation into v0.16.0 as a prerequisite (see
> `eval/ground-truth/`), delivers a simpler A/B mechanism in v0.16.2 before the
> full SPRT harness, scopes v0.16.1 to threshold sweeps only (deferring OPRO prompt
> mutation until parallel trial infrastructure exists in v0.17.0), and defers
> orchestration until at least one successful automated improvement cycle is
> validated end-to-end.

| Version | Description | Status | Size |
|---|---|---|---|
| v0.16.0 | Tuning diagnostics — **prerequisite: curated JSONL Tier 1 ground truth** for at least one corpus (`eval/ground-truth/`); `DiagnosticsEngine` with 10 priority-ordered rules operating on Tier 2/3 signals (rejection rate, SHACL, CQ coverage, entity IRI fragmentation) by default; F1/precision/recall rules activate automatically when `evaluation.ground_truth` is configured; corpus drift detection (embedding centroid + JSD); `_riverbank.tuning_diagnostics` catalog table; `riverbank tuning diagnose` | Planned | Large |
| v0.16.1 | Hypothesis generation (scoped) — threshold sweep automation (citation similarity, confidence routing thresholds); few-shot injection from recall-gap patterns; `TriedPatchesRegistry`; `MutationEffectivenessRegistry`; `riverbank tuning propose`; OPRO-style prompt mutation deferred to v0.18.0 pending parallel trial infrastructure | Planned | Medium |
| v0.16.2 | Lightweight A/B + fragmentation — simplified profile comparison (rolling average F1 over N fragments, no SPRT); entity IRI fragmentation rate metric (same-entity IRI variant ratio per document); `riverbank tuning compare` for manual side-by-side; promotion on rolling-average significance | Planned | Medium |
| v0.17.0 | Full A/B testing harness — `CandidateRouter` (consistent-hash cohort assignment), `SignificanceTester` (SPRT sequential testing), `_riverbank.tuning_experiments` and `tuning_cohorts` catalog tables, `ExperimentPostmortem` auto-generation, promotion and demotion logic, pg-tide event emission on state transitions | Planned | Large |
| v0.17.1 | Measurement Tier 1 full pipeline — `MeasurementStrategy` with complete three-tier ground truth pipeline (curated JSONL, Wikidata, noisy-OR bootstrap); human spot-sampling via Label Studio; measurement miscalibration detection; per-tier confidence labels on all promotion audit records; `riverbank tuning status`; note: JSONL schema and first corpus file (`eval/ground-truth/marie-curie.jsonl`, 45 triples) already decided and committed in v0.15.1 — v0.17.1 delivers the *runner* (SPARQL-match F1 evaluator) not the schema | Planned | Large |
| v0.17.2 | Orchestration and scheduling — `TuningOrchestrator` closed loop (**only after v0.17.0 has demonstrated at least one successful automated improvement cycle end-to-end**); `PlateauDetector` with restart strategy; `TuningScheduler` (APScheduler); full `auto_tuning:` profile YAML schema; `riverbank tuning run-once`; safety guardrails (precision floor, cost ceiling, freeze-on-regression, generation-depth limit, mutation-conflict prevention) | Planned | Large |
| v0.18.0 | Tuning observability and OPRO — Perses dashboard panel; `riverbank tuning history` lineage tree; `riverbank tuning pareto` quality×cost frontier; `riverbank tuning rollback` / `freeze` / `unfreeze`; new profile onboarding path (`riverbank tuning init`); OPRO-style prompt mutation (now backed by proper parallel trial infrastructure from v0.17.0); auto-tuning how-to docs | Planned | Large |
| v0.18.1 | Learning from history — `MutationEffectivenessRegistry` with time-decayed half-life; cross-profile transfer suggestions; `ProposalCalibrator` for hypothesis accuracy self-improvement; multi-property triage with clustering and batch mutation; `riverbank tuning insights` populated from full learning history | Planned | Medium |

---

### v0.15.0 — Wikidata Evaluation Framework

Goal: establish an externally-validated, reproducible benchmark for riverbank's
extraction quality by comparing compiled triples against Wikidata's 1.65 billion
human-curated statements sourced from the same Wikipedia articles.

- [x] `riverbank evaluate-wikidata --article <title|url>` — evaluate a single
  Wikipedia article on demand with hybrid caching: checks local cache first
  (`.riverbank/article_cache/`), falls back to Wikipedia API if not cached,
  fetches corresponding Wikidata item, runs full pipeline, prints
  precision/recall summary. Supports article title, Wikipedia URL, or Wikidata
  Q-id. Use `--no-cache` to bypass local cache; `--cache-only` for offline mode
- [x] `riverbank evaluate-wikidata --dataset <path> --profile <name>` — batch
  mode over the full benchmark dataset
- [x] 1,000-article benchmark dataset stratified across 7 domains: biographies
  (living + historical), organizations (commercial + non-profit), geographic
  entities, creative works, scientific concepts, and events
- [x] Wikipedia → Markdown download pipeline via MediaWiki API
- [x] Wikidata SPARQL ground-truth fetcher with statement filtering (excludes
  external identifiers, media, interwiki links)
- [x] Property alignment table mapping 50+ Wikidata P-ids to riverbank predicate
  patterns (P31 instance-of, P106 occupation, P569 birth date, P159 HQ, etc.)
- [x] Entity resolution: sitelink lookup → label matching → context disambiguation
- [x] Scoring pipeline: precision, recall, F1, confidence calibration (Pearson ρ),
  novel discovery rate, false positive rate
- [x] Per-domain and per-property breakdowns in JSON report
- [x] Calibration curve output (confidence bucket vs. observed accuracy)
- [x] Local run only; results stored in `eval/results/`

**Exit criterion:** first full evaluation report produced over 1,000 articles;
precision ≥ 0.85, recall ≥ 0.60, F1 ≥ 0.70; calibration ρ ≥ 0.80.

---

### v0.15.1 — Extraction Improvement Loop

Goal: close the feedback loop from the Wikidata evaluation back into the
extraction pipeline — identify systematic failure modes and fix them.

- [x] Per-property recall gap analysis: identify Wikidata properties where
  recall falls below 0.50, generate targeted extraction examples
- [x] Extraction prompt tuning driven by false-positive and false-negative patterns
  identified in v0.15.0 evaluation runs
- [x] 200+ manual annotations of unmatched riverbank triples to validate the novel
  discovery rate (triples correct but absent from Wikidata)
- [x] Published evaluation methodology and benchmark results in docs
- [x] Evaluation profile YAML (`wikidata-eval-v1`) committed to `examples/profiles/`

**Exit criterion:** second evaluation run shows measurable improvement over
v0.15.0 baseline on at least two of: precision, recall, novel discovery rate.

---

### v0.16.0 — Tuning Diagnostics

Goal: make all auto-tuning-relevant metrics queryable and trendable, establishing
the observation layer that all subsequent adaptive work depends on. See
[plans/auto-tuning.md](plans/auto-tuning.md) for the full design.

- [ ] `_riverbank.tuning_diagnostics` table (Alembic migration): one row per
  diagnosis cycle, storing `metrics` JSONB, `gaps` JSONB, `recommendations`
  JSONB with priority ordering, `measurement_tier` label, and `drift_status`
- [ ] SQL sliding-window view: aggregate per-run F1, precision, recall,
  cost-per-triple, SHACL score, rejection rate, and novel-discovery rate from
  `_riverbank.runs` over a configurable time window
- [ ] 7-day rolling baseline per profile: used to detect drift in each diagnosis
  cycle; stored in `tuning_diagnostics` for trend charting
- [ ] `MeasurementStrategy` — selects the active measurement tier (Tier 1 curated
  JSONL, Tier 2 structural SHACL+CQ, Tier 3 self-consistency) based on profile
  configuration and ground truth availability; computes per-tier composite score
  with configurable weights
- [ ] `DiagnosticsEngine.diagnose()` with 10 priority-ordered rules:
  (1) F1 regression >5% vs. 7-day baseline — critical, triggers freeze;
  (2) precision below configured floor — high, tighten routing thresholds;
  (3) zero recall on tracked predicates — high, inject targeted examples;
  (4) cost-per-written-triple increased >20% vs. baseline — medium, reduce safety cap;
      note: cost must be normalised by `triples_written` (not total LLM cost), because
      `extraction_target` intentionally raises `num_predict` and thus raw cost; a
      higher cost accompanied by proportionally more triples is not a regression;
  (5) confidence miscalibration (ρ < 0.3) — medium, adjust routing thresholds;
      note: the citation-similarity penalty (`conf_final = conf_llm × sim/100`)
      shifts the confidence distribution downward for all triples with imperfect
      excerpts; calibration must compare predicted vs. observed accuracy using
      `conf_final` (post-penalty), and treat the penalty as a calibration feature
      rather than noise — do not attempt to undo it before computing ρ;
  (6) SHACL score declining — low, review shape constraints;
  (7) novel-discovery rate >40% — low, review predicate alignment table;
  (8) entity IRI fragmentation rate elevated — medium, tune knowledge-prefix adapter;
  (9) triple yield per fragment declining — medium, review preprocessing strategy;
  (10) competency question coverage dropping — high, review CQ-guided extraction
- [ ] Corpus drift detection: embedding centroid distance (cosine distance between
  current sliding-window centroid and profile baseline centroid exceeds threshold)
  and predicate distribution Jensen–Shannon divergence (JSD > 0.15 flags drift);
  drift routes to domain adaptation path rather than quality tuning
- [ ] Cold-start bootstrap mode: when `min_history_runs` (default 5) not yet met,
  skip baseline-requiring rules, mark all recommendations as `confidence='bootstrap'`,
  queue initial spot-sampling task for corpora without a reference dataset
- [ ] FP/FN pattern clustering: group false positives and false negatives by
  predicate pattern; surface top-5 of each type with frequency counts
- [ ] Confidence calibration check: Pearson ρ between confidence bucket midpoints
  and observed accuracy; flag miscalibration below threshold
- [ ] Pre-diagnosis precondition checks: drift check (skip quality rules if corpus
  drifted), calibration check (predicate alignment coverage < 50%), tried-patches
  check (suppress mutation types attempted ≥3 times in 30d without promotion)
- [ ] Full `DiagnosticsReport` JSON stored per cycle (not just aggregates) so
  future post-mortem analysis can reconstruct the system's state at decision time
- [ ] `riverbank tuning diagnose --profile <name> [--window <hours>]` CLI command:
  prints ranked recommendations as JSON and human-readable summary table with
  active measurement tier and drift status
- [ ] `riverbank_tuning_f1_current` Prometheus gauge (labels: profile)
- [ ] `riverbank_tuning_cost_per_triple` Prometheus gauge (labels: profile)
- [ ] Unit tests for all 10 diagnosis rules with synthetic run data, drift
  detection with synthetic embedding series, and cold-start bootstrap mode

**Exit criterion:** `riverbank tuning diagnose --profile X` produces a JSON
report with gaps, ranked recommendations, active measurement tier, and drift
status. Cold-start mode correctly defers baseline-requiring rules when fewer
than `min_history_runs` runs have completed.

---

### v0.16.1 — Hypothesis Generation

Goal: automatically generate well-reasoned profile mutations from diagnostic
reports, using a combination of LLM-assisted optimization and deterministic
rule-based strategies. Add registries that prevent the system from trying the
same failed approach repeatedly.

- [ ] `ProfileMutation` dataclass: `mutation_type`, `mutation_yaml`, `rationale`,
  `estimated_lift`, `calibrated_lift` (bias-corrected), `parent_profile_id`,
  `generation` counter
- [ ] `MutationRegistry`: stores and queries mutation lineage; supports
  parent → child → outcome tree traversal; backed by `_riverbank.mutation_registry`
  table (Alembic migration)
- [ ] `TriedPatchesRegistry` backed by `_riverbank.tried_patches` table: tracks
  `(profile_id, mutation_type, parameter)` triples and their attempt counts and
  outcomes; suppresses mutation types tried ≥3 times in 30d without promotion;
  injects past successful mutations as positive examples into the OPRO prompt
- [ ] `MutationEffectivenessRegistry` backed by `_riverbank.mutation_effectiveness`
  table: tracks empirical success rates per `(mutation_type, failure_mode,
  corpus_domain)` with time-decayed relevance (exponential decay, half-life 90d);
  consulted by `HypothesisGenerator` to rank candidate mutation types before
  generating any prompt
- [ ] `PromptMutatorBackend` (OPRO-style): feeds current prompt + last 5 F1
  results + top FP/FN patterns + tried-patches to a configurable hypothesis model
  (defaults to `gpt-4o-mini`); requests one minimal targeted edit with rationale
  and estimated lift; validates returned YAML against `CompilerProfile` schema
  before accepting; coordinated mutation detection prevents simultaneously
  proposing changes to parameters with known interaction effects
- [ ] `ThresholdSweepBackend`: deterministic adjacent-step grid search over 9
  numeric parameters (`trusted_threshold`, `tentative_threshold`, `safety_cap`,
  `max_graph_context_tokens`, `top_entities`, `few_shot.max_examples`,
  `preprocessing.max_entities`, `extraction_strategy.citation_floor`,
  `extraction_strategy.extraction_target.min_triples`); the last two are new
  since v0.15.1 — `citation_floor` controls the hard-reject floor for absent
  excerpts (default 40), and `min_triples` directly controls triple yield
  (the primary signal for DiagnosticsEngine Rule 9); note: `citation_similarity_threshold`
  has been removed — replaced by the soft confidence-penalty model; selects
  direction based on the diagnosis recommendation; consults `TriedPatchesRegistry`
  to skip directions already tried
- [ ] `EvalDrivenFewShotMutator`: targets the top-3 lowest-recall predicates
  (any corpus, not Wikidata-specific); injects built-in extraction examples from
  `RecallGapAnalyzer._BUILTIN_EXAMPLES` as targeted few-shot additions
- [ ] `KnowledgePrefixTuner`: adjusts `max_graph_context_tokens` and
  `top_entities` based on entity IRI fragmentation rate and observed prompt
  truncation signals
- [ ] `PreprocessingStrategyMutator`: toggles preprocessing backend (nlp ↔ llm)
  and adjusts `max_entities` based on entity catalog quality signals from runs
- [ ] `HypothesisGenerator`: wraps all five backends, consults
  `MutationEffectivenessRegistry` to rank backends by empirical success rate for
  this failure mode, applies multi-property triage (cluster related gaps; batch
  up to `max_properties_per_mutation` default 3), enforces `max_active_candidates`
  limit, validates generated YAML before returning any mutation; aborts early if
  all calibrated lifts fall below noise floor (0.005)
- [ ] `_tuning_metadata:` block auto-written into candidate profile YAML:
  generation counter, parent profile IRI, mutation type, rationale, experiment ID
- [ ] `riverbank tuning propose --profile <name> [--type <mutation_type>]` CLI
  command: outputs candidate YAML with rationale and calibrated lift estimate
- [ ] Unit tests for each mutation backend including regression tests against
  known-bad mutation patterns; integration test verifying `TriedPatchesRegistry`
  prevents repeated failed approaches

**Exit criterion:** `riverbank tuning propose --profile X` generates a
syntactically valid candidate profile YAML with documented rationale. Re-running
after marking a mutation type as tried does not reproduce the same approach.
`MutationEffectivenessRegistry` correctly ranks backends by historical success rate.

---

### v0.17.0 — A/B Testing Harness

Goal: safely validate candidate profile mutations against live traffic using
statistically correct sequential testing before any configuration change takes
effect. No mutation goes live without statistical evidence.

- [ ] `_riverbank.tuning_experiments` table: experiment lifecycle
  (`active`, `promoted`, `demoted`, `expired`, `pending_review`), metrics at
  resolution, SPRT log-likelihood ratio, Cohen's d effect size, decision
  rationale, `cohort_source` field (`fresh` or `replay`) for per-cohort
  confidence weighting
- [ ] `_riverbank.tuning_cohorts` table: per-source cohort assignment
  (baseline / candidate) linked to experiment; idempotent via consistent
  hashing — same source always lands in the same cohort within an experiment
- [ ] `CandidateRouter`: consistent-hash assignment using
  `xxhash.xxh64(experiment_id + source_iri)`; configurable split ratio
  (default 10% candidate, 90% baseline); replay evaluation path for low-volume
  corpora (re-processes already-ingested documents deterministically when
  `validation.replay_on_low_volume: true` and fewer than `low_volume_threshold`
  new documents per week; replay results carry 0.6× weight in SPRT)
- [ ] Modify `pipeline.run_source()` to query active experiments and route each
  source to the appropriate profile before extraction; no change to extraction
  pipeline itself
- [ ] Replace Welch's t-test with SPRT (`SignificanceTester` with
  `_compute_llr()`): accumulates sequential log-likelihood ratio comparing H₁
  (candidate better by `effect_size`) against H₀ (no difference); crosses upper
  bound A → promote, lower bound B → demote; statistically correct for
  sequential monitoring without inflating Type I error rate; minimum sample size
  enforcement (default 30 documents)
- [ ] Held-out validation: documents used to generate the triggering diagnosis
  are excluded from A/B cohorts (prevents test-set contamination); 20% of any
  reference dataset reserved for final validation and never used in A/B scoring
- [ ] Promotion logic: Pareto dominance check for acceptance (candidate must not
  regress on precision or cost); scalar ranking via
  objective = score − λ × (cost / cost_baseline) for choosing between competing
  candidates; λ = 0.5 for budget-sensitive operators, λ = 0.0 for quality-only
- [ ] Demotion logic: demote when SPRT LLR ≤ B and regression ≥
  `demotion_f1_delta` or cost exceeds ceiling; automatic rollback if regression
  is on an already-promoted variant
- [ ] `ExperimentPostmortem` auto-generated on every `demoted` or `expired`
  experiment: `mutation_type`, `failure_mode`, `diagnostic_snapshot` at creation
  time, `actual_f1_delta`, `predicted_f1_delta`, `calibration_error`, derived
  `root_cause` and `lesson`; stored in `_riverbank.experiment_postmortems`
- [ ] Audit trail: every promotion and demotion writes a `_riverbank.log` entry
  (`operation='tuning_promotion'` / `'tuning_demotion'`) with metrics, SPRT
  LLR, effect size, and measurement tier
- [ ] pg-tide event emission on promotion (`riverbank.tuning.promoted`) and
  demotion (`riverbank.tuning.demoted`) for downstream alerting
- [ ] `riverbank tuning experiments [--profile <name>]` — list active experiments
  with current sample counts, cohort sizes, SPRT progress, and metric deltas
- [ ] `riverbank tuning approve --experiment-id <id>` — manually approve a
  `pending_review` experiment
- [ ] `riverbank tuning reject --experiment-id <id> [--reason <text>]` — reject
  with optional reason recorded in audit log
- [ ] `riverbank_tuning_experiments_active` Prometheus gauge
- [ ] `riverbank_tuning_promotions_total` and `riverbank_tuning_demotions_total`
  Prometheus counters (labels: profile, mutation_type)
- [ ] Integration tests: clearly-better candidate promoted after `min_sample_size`
  evaluations via SPRT; clearly-worse candidate demoted via SPRT early stopping;
  replay evaluation produces valid cohort results on a synthetic low-volume corpus

**Exit criterion:** a synthetic experiment routes traffic correctly, collects
per-cohort scores, and promotes the winning candidate automatically when the
SPRT log-likelihood ratio crosses the upper bound. The losing candidate is
demoted via SPRT early stopping without waiting for the full minimum sample.
`ExperimentPostmortem` is auto-generated for every demoted experiment.

---

### v0.17.1 — Orchestration and Scheduling

Goal: wire the full observe → diagnose → hypothesize → validate → promote loop
to run autonomously, with configurable scheduling, plateau detection, and
comprehensive safety guardrails that prevent runaway quality or cost regressions.

- [ ] `TuningOrchestrator.run_cycle()`: orchestrates one full loop iteration —
  calls `DiagnosticsEngine`, selects top recommendation, calls
  `HypothesisGenerator`, creates experiment record in DB, registers candidate
  profile, activates `CandidateRouter` routing; also fires on event-driven
  trigger (after `trigger_after_n_documents` new documents are ingested)
- [ ] `PlateauDetector`: after 3 consecutive promotions with mean ΔF1 <
  `plateau_threshold` (default 0.01), fires a response in order — (1) switch
  to different mutation type family, (2) expand parameter search space (allow
  2-step sweeps), (3) reset generation counter as new baseline, (4) escalate
  to human review with "possible local optimum" notification
- [ ] `TuningScheduler`: APScheduler-based periodic trigger; configurable
  interval per profile via `auto_tuning.diagnosis_interval_hours`; reuses the
  existing APScheduler instance used by nightly lint
- [ ] Full `auto_tuning:` section in `CompilerProfile` dataclass and profile
  YAML schema: `enabled`, `diagnosis_interval_hours`,
  `trigger_after_n_documents`, `validation.*` (split_ratio, min_sample_size,
  max_experiment_days, replay_on_low_volume, low_volume_threshold),
  `thresholds.*` (promotion_f1_delta, demotion_f1_delta, max_cost_increase,
  min_precision, plateau_threshold), `mutations.*` (max_active_candidates,
  allowed_types, hypothesis_model, max_batch_examples,
  max_properties_per_mutation), `convergence.*` (window_days,
  maintenance_interval_multiplier, reactivation_score_delta), and
  `cost_sensitivity` λ parameter
- [ ] `riverbank tuning run-once --profile <name>` CLI command: executes one
  full cycle synchronously, printing each step with timing for debugging
- [ ] Safety guardrails (enforced in `TuningOrchestrator`):
  - Precision floor: immediate demotion if candidate precision < floor
  - Cost ceiling: immediate demotion if candidate cost > `max_cost_increase`
    × baseline
  - Freeze-on-regression: if any promoted variant shows >5% F1 drop in 24h,
    freeze ALL experiments for that profile and emit a critical alert
  - Generation depth limit: pause auto-tuning at lineage depth 10; require
    human review before continuing
  - Mutation conflict prevention: at most one active experiment per parameter
    type at a time
  - Minimum evaluation coverage: no promotion without ≥10 scored documents
- [ ] Post-promotion recompilation policy: when `recompile_on_promotion: true`,
  schedule background recompile of all sources compiled by the previous profile
  version; `riverbank tuning stale-sources --profile <name>` lists sources
  flagged as stale after a promotion (compiled by the prior version)
- [ ] `riverbank tuning freeze --profile <name>` and
  `riverbank tuning unfreeze --profile <name>` commands; FROZEN state
  persisted in `_riverbank.profiles.metadata`; can be entered from any state
  and requires explicit unfreeze to exit
- [ ] Mutation auto-approval rules: threshold sweeps (±1 step) and small prompt
  patches (≤50 words changed) auto-approve; large prompt patches (>50 words
  changed) and structural changes (backend toggle, model change) require
  `pending_review`
- [ ] Loop state machine: BOOTSTRAP → ACTIVE → MAINTENANCE (triggered after
  `convergence.window_days` with no promotion and last 3 experiments ΔF1 <
  0.005) → reactivation on score shift or drift; FROZEN state from any state
- [ ] End-to-end integration test: run 3 full cycles; verify profile evolves,
  each promotion improves quality, plateau detection fires after 3 small-delta
  promotions, no guardrail fires falsely

**Exit criterion:** `riverbank tuning run-once --profile X` completes a full
cycle and either promotes a candidate, demotes a bad one, or logs "no significant
improvement found" — with a complete audit trail and a matching pg-tide event.
After 3 consecutive small-delta promotions, `PlateauDetector` fires and strategy
shifts without human intervention.

---

### v0.17.2 — Tuning Observability and Polish

Goal: make the auto-tuning system fully transparent to operators; complete the
CLI surface; integrate with Langfuse and Perses; add convergence/maintenance
mode and onboarding path; publish the design as documentation.

- [ ] Perses dashboard panel: active experiment count, F1 trend over time,
  cost-per-triple trend, promotion and demotion event timeline, experiment
  sample-size progress bars, tuning state machine status (ACTIVE / MAINTENANCE
  / FROZEN / BOOTSTRAP) per profile
- [ ] `riverbank tuning history --profile <name>` CLI: renders the mutation
  lineage tree (parent → child → outcome) with F1 delta, cost delta, and SPRT
  LLR at each node; supports `--format json` for programmatic consumption;
  marks plateau detection events in the tree
- [ ] `riverbank tuning pareto --profile <name>` CLI: tables the quality × cost
  Pareto frontier across all historical profile variants; marks the currently
  active profile and highlights dominated variants
- [ ] `riverbank tuning rollback --profile <name> --to-generation <n>` CLI:
  reactivates a previous generation as the current active profile; records a
  `tuning_rollback` event in the audit log
- [ ] `riverbank tuning insights --profile <name>` CLI: surfaces
  `ExperimentPostmortem` lessons, `MutationEffectivenessRegistry` top performers,
  and cross-profile transfer suggestions; supports `--format json`
- [ ] `riverbank tuning init --profile <name>` CLI: new profile onboarding path
  — verifies ≥20 documents ingested with tuning disabled, runs initial
  evaluation, snapshots the baseline in `_riverbank.tuning_diagnostics`, and
  enables `auto_tuning.enabled: true`; for corpora without a reference dataset,
  automatically queues an initial spot-sampling task
- [ ] `riverbank tuning status --profile <name>` CLI: shows current tuning state
  (BOOTSTRAP / ACTIVE / MAINTENANCE / FROZEN), active experiment count,
  last diagnosis timestamp, and convergence progress
- [ ] Convergence and maintenance mode: automatically transitions to MAINTENANCE
  when no promotion in `convergence.window_days` (default 30) and the last 3
  experiments all had ΔF1 < 0.005; diagnosis interval multiplied by
  `maintenance_interval_multiplier` (default 4×); reactivated automatically
  when score drops by `reactivation_score_delta` or drift is detected
- [ ] Langfuse dataset integration: each A/B experiment creates a Langfuse
  dataset with baseline and candidate cohort results; diff annotations flag
  which triples appeared, disappeared, or changed confidence between variants
- [ ] `riverbank_tuning_f1_current` gauge updated on every diagnosis cycle, not
  only on promotion events; new `riverbank_tuning_state` gauge (0=bootstrap,
  1=active, 2=maintenance, 3=frozen) per profile
- [ ] Experiment expiry background task: mark experiments `expired` after
  `max_experiment_days` with no significant result; archive or delete candidate
  profiles per `auto_tuning.mutations.on_expiry` policy
- [ ] `auto_tuning:` section added to example profiles (`wikidata-eval-v1`,
  `docs-policy-v1-preprocessed`) with sensible defaults, convergence config,
  and inline YAML comments explaining each option
- [ ] `riverbank evaluate <document> --profile <name>` CLI: pre-tuning diagnostic
  for a single document — reports Tier 2 (SHACL score, CQ coverage, entity
  fragmentation) and Tier 3 (confidence calibration ρ, rejection breakdown) signals
  without needing auto-tuning loop; optional `--reference <jsonl>` for Tier 1
  metrics (precision, recall, F1); `--compare <profile>` for side-by-side
  comparison on the same document
- [ ] How-to guide: [docs/how-to/enable-auto-tuning.md](docs/how-to/enable-auto-tuning.md)
- [ ] Concepts page: [docs/concepts/adaptive-compilation.md](docs/concepts/adaptive-compilation.md)
- [ ] [plans/auto-tuning.md](plans/auto-tuning.md) cross-referenced from ROADMAP
  and concepts page

**Exit criterion:** an operator can read the Perses dashboard, understand why
the last promotion happened, inspect the full lineage tree, perform a rollback
from the CLI, and onboard a new profile using `riverbank tuning init` — without
consulting source code. A stable profile correctly enters MAINTENANCE mode and
reactivates when corpus drift is detected.

---

### v0.18.0 — Measurement Architecture

Goal: implement the full ground truth pipeline so the auto-tuner works correctly
with any corpus — curated JSONL reference datasets, Wikidata, noisy-OR bootstrap,
or human spot-sampling. This makes auto-tuning genuinely corpus-agnostic.

- [ ] `MeasurementPlan` dataclass: tier label (`'gold'`, `'silver'`, `'bronze'`),
  primary score function, confidence level, recommended minimum sample size,
  staleness timestamp, composite weights per signal
- [ ] Full three-tier signal hierarchy in `MeasurementStrategy.select_tier()`:
  Tier 1 — curated JSONL ground truth or Wikidata property alignment (requires
  `evaluation.ground_truth` pointing to a JSONL file or `'wikidata'`); Tier 2
  — SHACL validation score + CQ coverage fraction + noisy-OR promotion rate
  (structural signals, no external labels); Tier 3 — self-consistency signals
  (confidence calibration ρ, triple yield, rejection rates, latency)
- [ ] `evaluation.ground_truth` field added to profile YAML schema: accepts a
  path to a JSONL ground truth file (predicate-per-line format with subject,
  predicate, object, label fields) or the string `'wikidata'` for Wikidata-backed
  evaluation; when absent the system falls back to Tier 2/3
- [ ] Composite score computation: weighted blend across tiers based on
  availability and configured `measurement_weights`; per-tier weights configurable
  in profile YAML; at least one tier must be available or diagnosis is deferred
- [ ] Human spot-sampling integration with Label Studio (Phase F):
  `SpotSampler` selects a stratified random sample from recently-ingested
  sources and creates Label Studio tasks; results scored against the extraction
  output; triggered automatically after every `spot_sample_every_n_promotions`
  promotions (default 5)
- [ ] Cold-start bootstrap path: for any new profile with no reference dataset,
  `riverbank tuning init` immediately queues a spot-sampling task; diagnosis
  defers until at least `min_spot_sample_size` (default 20) human labels are
  available; bootstrap mode uses Tier 2/3 only until then
- [ ] Measurement miscalibration detection before every diagnosis cycle:
  (a) predicate alignment coverage check — flag if < 50% of top-K predicates
  are aligned in the ground truth vocabulary (stale reference dataset);
  (b) CQ coverage check — flag if CQ relevance < 0.2 before using CQ signals;
  (c) calibration freshness check — flag Tier 3 confidence as stale if
  calibration run is > 30d old; (d) reference dataset staleness — warn if
  ground truth file not updated in > `evaluation.max_reference_age_days` days
- [ ] `SignificanceTester` updated to use composite score when Tier 1
  unavailable: accumulates SPRT over per-document composite scores rather
  than per-document F1; decision thresholds adjusted for higher score variance
- [ ] Per-tier confidence labels on all promotion audit records:
  `_riverbank.log` entries include `measurement_tier`, `composite_score`,
  and individual tier scores at the time of the promotion decision
- [ ] `riverbank tuning status --profile <name>` extended to show active
  measurement tier, predicate alignment coverage, reference dataset staleness,
  and next scheduled spot-sampling event
- [ ] Integration tests: full cycle with curated JSONL ground truth achieving
  Tier 1; full cycle with no reference dataset falling back to Tier 2/3;
  spot-sampling trigger fires correctly after N promotions; miscalibration
  detection flags correctly when alignment coverage drops below threshold

**Exit criterion:** `riverbank tuning diagnose --profile X` correctly identifies
Tier 1/2/3 availability and adjusts recommendations accordingly. Human
spot-sampling is triggered automatically on a corpus with no reference dataset.
A new corpus with a curated JSONL ground truth file achieves Tier 1 confidence
without any manual configuration beyond `evaluation.ground_truth`.

---

### v0.18.1 — Learning from History

Goal: make the auto-tuner self-improving across experiments — it should get
better at predicting which mutations will work, transfer successful patterns
to related profiles, and handle corpora with many simultaneous quality gaps.

- [ ] `ExperimentPostmortem` full analysis pipeline: after every `demoted` or
  `expired` experiment, automatically derive `root_cause` and `lesson` using
  LLM analysis of the `diagnostic_snapshot` vs. actual outcome; store in
  `_riverbank.experiment_postmortems`; surface in `riverbank tuning insights`
- [ ] `MutationEffectivenessRegistry` time-decay: empirical success rates decay
  with exponential half-life of 90 days (`decay_weight = exp(-λ·days)`);
  very old evidence has less influence than recent outcomes; decay applied
  on-read, not as a scheduled job, for efficiency
- [ ] Cross-profile transfer suggestions (§7.3): after every promotion in
  profile A, query other profiles with similar corpus domain and overlapping
  failure modes; emit a transfer suggestion (not an automatic mutation — requires
  human approval) surfaced in `riverbank tuning insights` and `riverbank.tuning.
  transfer_suggestion` pg-tide event; validated by `riverbank tuning suggest
  --profile B` before any action
- [ ] `ProposalCalibrator` (§7.5): tracks bias between `predicted_f1_delta` and
  `actual_f1_delta` over the last 20 experiments using an exponentially-weighted
  moving average; corrects systematic over- or under-prediction before lift
  estimates are used for ranking or early-abort decisions; stores calibration
  state in `_riverbank.proposal_calibration`; early abort if all calibrated
  lifts fall below 0.005
- [ ] Multi-property triage (§7.6): when `DiagnosticsReport` has more than 3
  simultaneous recall gaps, `HypothesisGenerator` clusters them by shared
  root cause (overlapping FN/FP patterns); batches few-shot injection for
  up to `max_batch_examples` (default 5) patterns into a single mutation;
  prioritises by recall × predicate frequency; caps at
  `max_properties_per_mutation` (default 3) per mutation to keep experiments
  interpretable
- [ ] Mutation half-life in `TriedPatchesRegistry`: attempted mutations also
  decay over time — a failed approach tried 90 days ago should be retryable;
  configurable `tried_patches_decay_days` (default 90)
- [ ] Cross-experiment learning validation: after every 20 experiments, run an
  internal A/B test comparing the `MutationEffectivenessRegistry`-guided
  proposal order against random; emit a `learning_improving` / `learning_flat`
  diagnostic event
- [ ] `riverbank tuning insights --profile <name>` fully populated: post-mortem
  lessons, top-5 effective mutation types with success rates, cross-profile
  transfer suggestions, `ProposalCalibrator` bias and confidence, and a
  plain-language summary of what the tuner has learned about this corpus
- [ ] Integration tests: after 20 synthetic experiments, `MutationEffectiveness
  Registry` correctly ranks mutation types by historical success; cross-profile
  transfer suggestion fires when a promoted mutation matches another profile's
  failure mode; `ProposalCalibrator` corrects a 20% systematic over-prediction
  after 10 experiments

**Exit criterion:** after 20+ experiments, recommended mutation types succeed
at a higher rate than random selection (measured by the internal learning
validation A/B). `riverbank tuning insights` surfaces at least one cross-profile
transfer suggestion and a calibrated lift estimate for each queued proposal.
`ProposalCalibrator` demonstrably reduces calibration error over baseline.

---

## External dependency risk

Several planned versions delegate implementation to pg-ripple or pg-tide rather than owning the capability in Python. The table below identifies the features at risk and the mitigation if a dependency is unavailable at the start of a release cycle.

| Capability | Owned by | First needed | Mitigation if delayed |
|---|---|---|---|
| `pg:fuzzy_match()`, `pg:token_set_ratio()`, `suggest_sameas()`, `pagerank_find_duplicates()` | pg-ripple | v0.5.0 | Fuzzy entity matching deferred; spaCy pre-resolution still ships |
| `pg_ripple.explain_contradiction()` | pg-ripple | v0.8.0 | `riverbank explain-conflict` deferred; contradiction detection via SHACL still works |
| `pg_ripple.refresh_coverage_map()` | pg-ripple | v0.8.0 | Coverage map generation deferred; competency-question coverage computed locally |
| SPARQL `SERVICE` federation | pg-ripple | v0.9.0 | Federated compilation deferred; local compilation unaffected |
| Relay circuit breakers, DLQ, backpressure | pg-tide | v0.7.0 | Relay health visible in `riverbank health`; manual configuration fallback |
| `owlrl` (OWL 2 RL reasoner) | PyPI | v0.14.0 | OWL inference deferred; SPARQL CONSTRUCT rules still ship and cover most derivations |
| `pyshacl` (SHACL validation) | PyPI | v0.14.0 | SHACL shape validation deferred; ontology-grounded predicate allowlist still enforces structural constraints |

**Policy:** if a dependency is unavailable at the start of a release cycle, the affected feature moves to the following minor version. All core ingestion, extraction, catalog, and provenance features are riverbank-owned and carry no upstream dependency.

---

## What each release delivers

### v0.1.0 — Skeleton

Goal: prove the deployment story end-to-end with no LLM calls.

- [x] `riverbank/` repo with `pyproject.toml`, `Dockerfile`, `docker-compose.yml`
- [x] `riverbank` CLI with `init`, `version`, `health` subcommands
- [x] `health` calls `pgtrickle.preflight()` (7 system checks) and
  `pg_ripple.pg_tide_available()` to verify the full extension stack before
  any ingest attempt
- [x] Catalog schema migrations (Alembic) for `sources`, `fragments`, `profiles`,
  `runs`, `artifact_deps`, `log` tables in `_riverbank`
- [x] CI workflow: `pytest` against an ephemeral PostgreSQL with pg_ripple,
  pg_trickle, and pg_tide installed via `testcontainers-python`
- [x] No-op extractor: records a run, emits an OTel span, writes nothing to the
  graph — verifying orchestration plumbing end-to-end
- [x] `docker compose up` brings up: PostgreSQL with pg_ripple ≥ 0.98 + pg_trickle
  ≥ 0.48, pg-tide v0.14, riverbank worker, Langfuse, Ollama

**Exit criterion:** `docker compose up -d && riverbank health` prints
"all systems nominal" on a clean checkout.

---

### v0.2.0 — MVP Ingestion

Goal: ingest a Markdown corpus, extract atomic facts, write them to pg_ripple
with confidence and provenance, and demonstrate fragment-level skip on
re-ingest.

- [x] `markdown` parser + `heading` fragmenter plugin
- [x] `instructor` extractor: OpenAI-compatible endpoint (Ollama for local/CI),
  `EvidenceSpan` validator, Pydantic retry loop
- [x] `docs-policy-v1` example compiler profile (YAML → `_riverbank.profiles`)
- [x] Editorial policy ingest gate: minimum heading depth, fragment length, language
  check
- [x] Citation grounding: every triple must carry a `prov:wasDerivedFrom` edge with
  character-range evidence; fabricated quotes rejected by the type system
- [x] `load_triples_with_confidence()` writes facts to a named graph in pg_ripple
- [x] `shacl_score()` gate routes low-quality output to `<draft>` graph, not
  `<trusted>`
- [x] Fragment hash check (`xxh3_128`): re-ingesting an unchanged file produces
  0 LLM calls
- [x] Filesystem connector with `watchdog` directory-watcher mode
- [x] `riverbank ingest <path>` command
- [x] Token counts and cost estimate recorded in `_riverbank.runs`
- [x] OTel spans wrap every pipeline stage; Langfuse receives LLM call traces

**Exit criterion:** `riverbank ingest examples/markdown-corpus/` produces
triples in pg_ripple, all with `pgc:fromFragment` edges and confidence scores.
Re-running produces 0 LLM calls.

---

### v0.3.0 — MVP Completion

Goal: close out the MVP with query access, run inspection, cost visibility, and
a reproducible CI gate.

- [x] `riverbank query <sparql>` — execute SPARQL against the compiled graph
- [x] `riverbank runs --since 1h` — inspect recent compiler runs with outcome,
  token counts, and Langfuse deep-links
- [x] Cost accounting: per-source and per-profile cost dashboards via
  `_riverbank.runs.cost_usd`; cost tables in `riverbank/cost_tables/`
- [x] Schema rejection and citation enforcement acceptance tests
- [x] Golden corpus: `tests/golden/` with SPARQL `ASK`/`SELECT` assertions over a
  fixed Markdown corpus; profile or model changes that break a golden assertion
  fail CI
- [x] Full test suite runs in under 10 minutes in CI against `ollama/llama3.2:3b`
- [x] `riverbank profile register` and `riverbank source set-profile` commands
- [x] **`riverbank lint --shacl-only`** — thin SHACL quality report against the trusted named graph; exits non-zero if score falls below the profile threshold. No Prefect required. Establishes governance as a first-class operation from day one, before the full lint pass lands in v0.6.0.
- [x] **Competency question CI gate** — golden corpus assertions are generated from the `competency_questions` array in each compiler profile. CI validates not just that triples were written, but that the compiled graph answers what the profile was built to answer.

**Exit criterion:** end-to-end demo on pg_ripple's own `docs/src/**/*.md`:
≥ 80% fragment skip rate on re-ingest, ≥ 95% of facts with valid evidence
spans, full compile cost < $5 with `gpt-4o-mini` or $0 with Ollama.

---

### v0.4.0 — Incremental Compilation

Goal: prove the system rebuilds *only* what changed when a source updates, establish vocabulary hygiene as an upstream constraint before relationship extraction, and scaffold the multi-tenant catalog schema.

- [x] **Artifact dependency graph.** Every compiled artifact records
  `(fragment, profile_version, rule_set)` dependencies in
  `_riverbank.artifact_deps`; queryable in SQL and SPARQL.
- [x] **`riverbank explain <artifact-iri>`** — dumps the dependency tree of any
  compiled artifact: fragments, profile version, rules that contributed.
- [x] **Recompile flow.** Changed fragments → invalidate dependent artifacts →
  re-extract → re-derive → emit semantic diff event via pg-trickle +
  `pgtrickle.attach_outbox()`.
- [x] **Vocabulary pass.** `riverbank ingest --mode vocabulary` (or
  `run_mode_sequence: ['vocabulary', 'full']` in the profile) processes the
  corpus with the `ExtractedEntity` schema first, writing `skos:Concept`
  triples (preferred label, alternate labels, scope note) into `<vocab>` before
  any relationship extraction. Subsequent full passes are given the compiled
  vocabulary as a structured context constraint, snapping entity references to
  canonical preferred-label IRIs before writing facts — upstream vocabulary
  hygiene rather than downstream deduplication.
- [x] **SKOS structural integrity shape bundle.** `riverbank init` activates the
  built-in `pg:skos-integrity` shape bundle via
  `pg_ripple.load_shape_bundle('skos-integrity')` (pg-ripple ≥ 0.98.0). The
  six shapes (prefLabel required, scopeNote recommended, broader-cycle
  detection, conflicting match-type check, orphan concept warning, altLabel
  collision check) are defined and maintained in pg-ripple — riverbank ships
  no Turtle files for these rules. `riverbank lint --layer vocab` runs the
  bundle against the `<vocab>` named graph. This is the machine-executable
  form of the Ontology Pipeline output quality contract.
- [x] **`tenant_id` schema scaffold.** A nullable `tenant_id` column is added to
  all `_riverbank` tables via Alembic migration (0002). Row-level security is
  not activated yet — that lands in v0.9.0 — but the column is present so that
  all downstream migrations are additive-only.

**Exit criterion:** modify one paragraph in one Markdown file, re-run
`riverbank ingest`, exactly one fragment re-extracted, semantic diff event
arrives on the pg_trickle outbox. `riverbank explain entity:Acme` prints a
complete dependency tree.

---

### v0.5.0 — Multi-format Parsing and Enrichment

Goal: extend ingestion beyond Markdown to office documents and web content, and add the enrichment layer (NER, fuzzy matching, embeddings) that quality gates and epistemic features depend on.

- [x] **Docling integration.** PDF, DOCX, PPTX, HTML, and image OCR via Docling ≥
  2.92. `Docling` becomes the default parser for non-Markdown sources.
- [x] **spaCy NER pre-resolution + vocabulary lookup.** Named entities extracted
  before the LLM call; when a vocabulary pass has run, the pre-resolution step
  also queries the `skos:prefLabel` / `skos:altLabel` index and injects matched
  preferred-label IRIs into the structured context block.
- [x] **Fuzzy entity matching.** pg_ripple `pg:fuzzy_match()` and
  `pg:token_set_ratio()` (GIN trigram index) for query-time matching;
  `suggest_sameas()` and `pagerank_find_duplicates()` for dedup; RapidFuzz for
  pre-LLM Python-side candidate preparation.
- [x] **Embedding generation.** sentence-transformers produces embeddings for each
  compiled summary. Entity-cluster centroid views are maintained as
  `avg(embedding)::vector` pg_trickle stream tables (pgVector IVM, v0.37+):
  centroid updates incrementally with no full scan on each new fact.
- [x] **Singer tap configuration.** pg-tide ≥ 0.14.0 ships native Singer tap
  mode: tap invocation, STATE checkpoint persistence (resumable taps across
  restarts), and SCHEMA drift detection are all handled by the pg-tide sidecar.
  riverbank's contribution is profile-side: a `singer_taps` block in the
  compiler profile YAML maps each tap (`tap-github`, `tap-slack-search`, etc.)
  to a `tide.relay_inlet_config` row, which pg-tide picks up via `NOTIFY` hot
  reload. No Python tap-invocation code lives in riverbank.

**Exit criterion:** a PDF and a DOCX file ingest successfully alongside the
existing Markdown corpus; entity-cluster centroid views are queryable via SQL;
`riverbank query` returns vector-similar results for a test entity; fuzzy match
suggestions appear in `riverbank explain` output for a known near-duplicate pair.

---

### v0.6.0 — Quality Gates and Review Loop

Goal: a running human-in-the-loop pipeline that converts low-confidence
extractions into reviewed, high-confidence facts.

- [x] **Label Studio integration.** `LabelStudioReviewer` plugin creates one task
  per review-queue item; pre-labels with LLM extraction; webhook posts
  decisions back; corrections enter `<human-review>` named graph.
  Custom labeling templates: atomic-fact correction, span-based evidence
  annotation, ensemble disagreement arbitration.
- [x] **Active-learning review queue.** `riverbank review queue` runs the
  centrality × uncertainty SPARQL query and refreshes Label Studio task
  priorities — maximum leverage per review hour.
- [x] **Editorial policy example bank.** Each Label Studio decision exports to the
  profile's example bank; next compile run uses these as few-shot examples.
- [x] **SHACL score history.** Daily Prefect flow snapshots `shacl_score()` per
  named graph into Prometheus. **Prefect is introduced here**; the APScheduler
  job from v0.2.0 is replaced.
- [x] **Langfuse evaluations.** Generated Q&A pairs run as Langfuse dataset
  evaluations on every recompile; regressions surface as alerts.
- [x] **Lint flow.** `riverbank lint` runs a full lint pass and writes findings to
  `pgc:LintFinding` triples; Prefect schedules it nightly.
- [x] **Thesaurus layer activation.** `riverbank query` expands query terms via the
  `<thesaurus>` named graph before dispatching BM25, vector, and graph traversal
  streams. `skos:altLabel` provides synonym coverage; `skos:related` provides
  associative coverage; `skos:exactMatch` / `skos:closeMatch` provide cross-corpus
  alignment. The expansion is a SPARQL lookup — sub-millisecond, no LLM call.
  This is the release where the thesaurus layer transitions from a compilation
  artifact to an active query-time asset.

**Exit criterion:** reviewer receives a Label Studio task within 60 seconds of
a low-confidence extraction; correction is reflected in the next SPARQL query;
example bank has ≥ 20 entries after a one-week pilot.

---

### v0.7.0 — Production Hardening

Goal: deployable in a regulated production environment with multi-replica
workers, secret management, backups, and SLOs.

- [x] **Helm chart.** `riverbank/helm/` deploys the worker, Prefect server,
  Langfuse, and Label Studio onto Kubernetes; depends on the existing
  pg_ripple chart.
- [x] **Multi-replica workers.** Fragment-level advisory locks
  (`pg_try_advisory_lock(hashtext(fragment_iri)::bigint)`) + run idempotency
  key (fragment_id + profile_id + content_hash) prevent duplicate work without
  an external coordinator.
- [x] **Prometheus metrics + Perses dashboard.** `/metrics` exposes
  `riverbank_runs_total`, `riverbank_run_duration_seconds`,
  `riverbank_llm_cost_usd_total`, `riverbank_shacl_score`,
  `riverbank_review_queue_depth`, `riverbank_context_efficiency_ratio` (graph
  tokens vs estimated naive-RAG tokens per `rag_context()` call). Perses panels
  ship in `riverbank/perses/` and import the pg-tide relay health sub-dashboard
  (relay throughput, error rate, DLQ depth, circuit breaker state, forward
  latency) from pg-tide's own Perses definition — relay metrics are not
  re-implemented in riverbank. The context efficiency panel shows the running
  ratio trend per profile, making the token-cost justification for graph-based
  retrieval quantitatively visible to operators and stakeholders.
- [x] **Secret management.** LLM API keys from environment variables, Kubernetes
  Secrets, or HashiCorp Vault (`hvac`). Keys route through pg-tide's
  `${env:VAR}` / `${file:/path}` secret interpolation for relay credentials;
  no secret is ever logged.
- [x] **Rate limiting + circuit breakers.** Per-provider concurrency limits and a
  circuit breaker (`aiobreaker`) protect against runaway LLM costs during API
  misbehaviour — this covers OpenAI, Anthropic, and Ollama provider calls only.
  Relay pipeline circuit breakers (pg-tide transport layer) are configured via
  `tide.relay_outbox_config` and do not require Python code in riverbank.
  `riverbank health` surfaces open relay circuits from
  `tide.relay_circuit_breaker_status` alongside the existing extension stack
  checks.
- [x] **Audit trail.** Every graph-mutating operation writes to `_riverbank.log`;
  append-only at the database level (`REVOKE UPDATE, DELETE`).
- [x] **Bulk reprocessing.** `riverbank recompile --profile docs-policy-v1
  --version 2` queues all v1 sources for recompilation and produces a semantic
  diff report.
- [x] **OpenTelemetry export.** `OTEL_EXPORTER_OTLP_ENDPOINT` routes traces to any
  collector (Jaeger, Tempo, Honeycomb-OSS).
- [x] **Cost dashboard.** Perses panels: cost per source, cost per profile, cost
  trend, projected monthly spend.

**Load test exit criteria:** three worker replicas process 10,000
fragments/hour; a simulated 1-hour LLM outage triggers the circuit breaker and
recovers without manual intervention; Helm upgrade rolls workers without
dropping in-flight runs.

---

### v0.8.0 — Advanced Epistemic Features

Goal: implement the features that distinguish riverbank from a generic compiler:
explicit absence, structured reasoning, and ensemble verification.

- [x] **Negative knowledge.** `pgc:NegativeKnowledge` records for explicit denials,
  exhaustive search failures, and superseded facts. Compiler profiles can
  declare "search-and-record-absence" rules per predicate.
- [x] **Argument graphs.** `pgc:ArgumentRecord` extractor with a Label Studio
  annotation template for `{claim, evidence, objection, rebuttal}` spans. SPARQL
  navigation: "which policy conclusions have a recorded objection but no
  rebuttal?"
- [x] **Assumption registry.** Extracted assumptions attached as RDF-star
  annotations to facts and entity pages; surfaced by `rag_context()` alongside
  answers.
- [x] **Epistemic status layer.** Every fact gets a `pgc:epistemicStatus`
  annotation from the full set: `observed`, `extracted`, `inferred`,
  `verified`, `deprecated`, `normative`, `predicted`, `disputed`,
  `speculative`. Status flows from compiler outcome, Datalog inference, and
  Label Studio decisions.
- [x] **Model ensemble compilation.** Per-profile opt-in; runs N model variants
  and routes disagreements to Label Studio with a side-by-side template. Hard
  cost cap configurable per profile.
- [x] **Minimal contradiction explanation.** `riverbank explain-conflict <iri>`
  is a CLI wrapper around `pg_ripple.explain_contradiction()` — the
  minimal-cause reasoning engine (SAT-style hitting-set over the inference
  dependency graph) lives in pg-ripple and requires no Python implementation
  in riverbank.
- [x] **Coverage maps.** `pg_ripple.refresh_coverage_map()` computes per-topic
  source density, mean confidence, contradiction count, and recency into the
  `<coverage>` named graph. A Prefect flow joins the result against
  `_riverbank.profiles.competency_questions` to compute the unanswered-question
  count (the one join that requires riverbank's catalog), then writes enriched
  `pgc:CoverageMap` triples surfaced by `rag_context()`.
- [x] **Procedural knowledge compiler profile.** A built-in profile template
  (`procedural-v1`) for runbooks, SOPs, incident-response guides, and onboarding
  flows. The vocabulary pass extracts step names and tool/resource names;
  the full pass extracts step sequences (`pko:nextStep`, `pko:previousStep`),
  decision points (`pko:nextAlternativeStep`), preconditions, required expertise
  levels, and error-handling paths — aligned with the Procedural Knowledge
  Ontology (PKO) from Cefriel. Standard competency questions are generated
  automatically: "What happens if step X fails?", "Which steps require admin
  access?", "What is the rollback path?". This expands riverbank's applicability
  to operational knowledge that currently lives as tribal practice in undocumented
  runbooks.

**Exit criterion:** an argument graph in Label Studio produces a
`pgc:ArgumentRecord` with claim, two evidence nodes, one objection, and one
rebuttal — all queryable in SPARQL. A test-corpus contradiction produces a
hand-verified minimal explanation. Ensemble compilation with 3 models shows
measurable error reduction over a single-model baseline.

---

### v0.9.0 — Multi-tenant and Prose Generation

Goal: deploy as shared infrastructure across multiple knowledge bases; render
compiled knowledge back to prose.

- [x] **Multi-tenant RLS activation.** Row-level security is enabled on all
  `_riverbank` tables using the `tenant_id` column scaffolded in v0.4.0.
  Per-tenant editorial policies, profiles, and named graphs. Tenant lifecycle
  API (create, suspend, delete with GDPR erasure).
- [x] **Tenant-scoped Label Studio.** One Label Studio organisation per tenant;
  reviewer assignments respect tenant boundaries.
- [x] **Federated compilation.** A "remote profile" type pulls SERVICE-federated
  triples from a peer pg_ripple instance into a local compilation context,
  applies confidence weighting, and writes the result locally. The SPARQL
  `SERVICE` keyword is implemented in pg-ripple's query engine; riverbank
  configures a `federation_endpoints` entry via SQL and issues a standard
  SPARQL query — no federation protocol code lives in riverbank.
- [x] **Markdown / JSON-LD page rendering.** `riverbank render` generates entity
  pages, topic surveys, comparison tables, and change digests from compiled
  artifacts. Output formats: Markdown (Obsidian/MkDocs), JSON-LD, HTML.
- [x] **Render scheduling.** Pages stored as `pgc:RenderedPage` artifacts with
  dependency edges to their source facts. When facts change, pages are flagged
  stale and regenerated in the next render flow.
- [x] **Streaming render.** SSE endpoint emits page updates as the underlying graph
  changes, for live documentation sites.

**Exit criteria:** two tenants compile independently on shared PostgreSQL with
no data leakage (verified by RLS tests); `riverbank render --format markdown
--target docs/` produces a navigable MkDocs site with citations linking back to
source fragments; modifying one fact regenerates exactly the pages that depend
on it.

---

### v0.10.0 — Release Infrastructure

Goal: make riverbank self-installable from PyPI, ship a machine-readable SBOM,
and automate the documentation site — so that adopters can onboard without
cloning the repository.

- [x] **PyPI package.** `pip install riverbank` installs the worker and CLI.
  Optional extras: `[ollama]`, `[docling]`, `[labelstudio]`. `pyproject.toml`
  build metadata, `MANIFEST.in`, and a GitHub Actions release workflow that
  publishes to PyPI on every version tag.
- [x] **`riverbank sbom`** — new CLI command that generates a CycloneDX SBOM for
  the installed package using `cyclonedx-python`. Output formats: JSON (default)
  and XML. Exits non-zero if any dependency has a known CVE (via `pip-audit`
  integration). Designed for supply-chain compliance workflows.
- [x] **Documentation site auto-publish.** The existing `riverbank render` capability
  is wired to a release workflow: on each tag, `riverbank render --format markdown
  --target docs/` generates the MkDocs site from the pg_ripple docs corpus and
  publishes it to GitHub Pages. No new rendering logic — purely CI plumbing.

**Exit criterion:** `pip install riverbank` on a clean machine runs
`riverbank health` successfully; `riverbank sbom` produces a valid CycloneDX
JSON file; the documentation site updates automatically on the next version tag.

---

### v0.11.0 — Preprocessing & Post-Processing

Goal: enrich extraction with document-level and corpus-level context, and add
post-extraction quality passes that clean and verify the compiled graph.

- [x] **LLM document preprocessing (Phase 1).** `DocumentPreprocessor` generates
  a structured summary and entity catalog per document before extraction. The
  catalog (label, type, aliases) is injected into the extraction prompt via
  `build_extraction_prompt()`, giving the LLM entity-aware context. Token counts
  tracked separately (`preprocessing_prompt_tokens`, `preprocessing_completion_tokens`).
- [x] **Corpus-level clustering (Phase 2).** `CorpusPreprocessor` embeds document
  summaries via sentence-transformers, clusters with K-Means, and generates
  per-cluster and corpus-wide summaries. `CorpusAnalysis` (cluster map, entity
  vocabulary, predicate vocabulary) is prepended to extraction prompts via
  `build_context()`, providing cross-document awareness.
- [x] **Few-shot injection.** `FewShotInjector` loads golden examples from YAML
  files in `examples/golden/` and prepends them to the extraction prompt.
  Configurable per profile via the `few_shot` block.
- [x] **`riverbank validate-graph`.** Evaluates competency-question coverage
  against the compiled graph via SPARQL ASK queries. Exits non-zero if
  coverage falls below the profile threshold.
- [x] **Entity deduplication (Post-1).** `EntityDeduplicator` embeds entity IRI
  labels via sentence-transformers, clusters by cosine similarity (default
  threshold 0.92), promotes the shortest IRI as canonical, and writes
  `owl:sameAs` links for aliases.
  CLI: `riverbank deduplicate-entities --graph --threshold --dry-run`.
- [x] **Self-critique verification (Post-2).** `VerificationPass` issues a second
  LLM call per low-confidence triple. Confirmed triples receive a confidence
  boost; rejected triples are quarantined to `<draft>`. Configurable via
  the `verification` block in the compiler profile.
  CLI: `riverbank verify-triples --profile --graph --dry-run`.

**Exit criterion:** a 3-document corpus ingested with Phase 1 + Phase 2
preprocessing shows measurably higher CQ coverage than without. Entity
deduplication reduces unique IRI count by ≥ 15%. Verification pass quarantines
at least one low-confidence triple in a test run.

---

### v0.11.1 — Token Efficiency

Goal: offset the token cost increase from v0.12.0's permissive extraction
features before they ship. The four items below deliver a **32% token
reduction** from the v0.11.0 baseline in ≤ 1 day of implementation, ensuring
the net impact of v0.12.0 stays within 20% of today's token baseline.

- [ ] **Per-fragment entity catalog filtering.** Before injecting the entity
  catalog into an extraction prompt, filter it to only include entries whose
  `label` or `aliases` appear in the fragment text. A `min_entities_to_inject`
  floor (default 3) ensures the LLM always has some context even for fragments
  that don't surface entity names explicitly. Saves ~300–400 input tokens per
  fragment (50 entities → ~10 relevant). Controlled by
  `token_optimization.filter_entities_by_mention: true` in the profile.
- [ ] **Adaptive preprocessing skip for small documents.** Skip Phase 1
  preprocessing entirely for single-fragment documents shorter than
  `skip_preprocessing_below_chars: 2000`. For these documents the fragment IS
  the document — there is no inter-fragment terminology drift to resolve.
  Eliminates 2 LLM calls (~2 500 tokens) per small document.
- [ ] **Deduplicate Phase 2 pre-scan.** Cache the Phase 1 document summary so
  the Phase 2 corpus pre-scan does not recompute summaries that Phase 1 will
  compute anyway. Pass summaries from Phase 1 to the Phase 2 analyser via a
  shared `{source_iri: summary}` dict. Saves N × ~2 000 tokens —
  **20 000 tokens for a 10-document corpus** — at zero quality cost.
- [ ] **Ollama keep-alive prompt caching.** Set `keep_alive: "5m"` on all
  Ollama calls so the model KV cache persists across the fragments of an ingest
  run. The static system prompt (~200 tokens) is re-processed only once per
  run instead of once per fragment. For cloud providers (OpenAI / Anthropic)
  prompt caching is already active automatically.
- [ ] **Noise section filtering.** Wire up the `noise_sections` field in
  `PreprocessingResult` (the data model already exists but is never populated).
  Add an LLM call in `DocumentPreprocessor.preprocess()` that asks:
  "Identify headings that are pure boilerplate and carry no domain facts
  (navigation, disclaimers, change logs, legal notices). Return a JSON array
  of heading paths." Fragments whose heading path matches a noise section are
  skipped before extraction entirely. Saves one full LLM extraction call per
  boilerplate fragment. Controlled by `preprocessing.noise_filtering: true`.

**Exit criterion:** a 10-document corpus ingested with all v0.11.0 features
enabled uses ≤ 100 000 total tokens (down from ~144 600 baseline). Phase 2
pre-scan produces zero duplicate LLM summary calls. Small documents
(< 2 000 chars) are processed without any preprocessing LLM calls. At least
one corpus document has boilerplate sections correctly identified and skipped.

---

### v0.12.0 — Permissive Extraction

Goal: dramatically increase triple yield — especially for small corpora — by
extracting broadly within ontology-bounded constraints and routing per-triple by
confidence. For small corpora (< 20 documents), the primary win is immediate:
higher single-pass recall from the permissive prompt, not deferred accumulation.
Ontology grounding and permissive extraction are **codependent** and must ship
together — permissive extraction without vocabulary constraints floods the
tentative graph with hallucinated predicates; ontology grounding without
permissive extraction still skips implied facts.

- [x] **Ontology-grounded extraction.** `allowed_predicates` and
  `allowed_classes` fields in the compiler profile YAML. Injected into the
  extraction prompt as a closed-world constraint: "use ONLY these predicates;
  if a relationship does not fit, SKIP it." Triples with non-conforming
  predicates are rejected before writing (`triple_rejected_ontology` stat).
  Required companion to permissive extraction — prevents vocabulary explosion.
- [x] **CQ-guided extraction.** Competency questions from the profile are
  transformed into "EXTRACTION OBJECTIVES" and prepended to the extraction
  prompt, making extraction goal-directed rather than exhaustive. CQs also
  drive auto few-shot expansion (v0.13.0) and benchmark evaluation (v0.13.0),
  so this is the first step in making CQs a first-class quality driver.
- [x] **Permissive extraction prompt.** New `extraction_strategy.mode: permissive`
  option replaces the conservative "only extract claims directly supported by
  the text" instruction with a tiered guidance: EXPLICIT (0.9–1.0), STRONG
  (0.7–0.9), IMPLIED (0.5–0.7), WEAK (0.35–0.5). The four tiers correct the
  LLM's systematic mis-calibration — it over-scores hallucinations and
  under-scores true implied facts. Confidence at extraction time is treated
  as a routing signal, not a truth probability.
- [x] **Per-triple confidence routing.** Replace batch-level SHACL routing with
  per-triple confidence routing: ≥ 0.75 → trusted graph, 0.35–0.75 →
  `graph/tentative`, < 0.35 → discarded. New `tentative_graph` field in
  `CompilerProfile`. This is Phase A — independently shippable, delivering the
  full single-pass recall improvement without requiring Phase B (accumulation).
- [x] **Pre-write structural filtering.** Reuse the ontology allowlist as a fast
  write-time filter: before any triple enters the tentative graph, check that
  the predicate is in `allowed_predicates` and that subject/object types match
  declared domain/range (if specified). Zero graph queries, microsecond latency.
  Prevents structurally invalid triples from entering the tentative graph and
  polluting noisy-OR calculations.
- [x] **Extraction safety cap.** `max_triples_per_fragment: 50` in the
  `extraction_strategy` profile block. If the LLM produces more, keep the top-N
  by confidence and log a `triples_capped` warning. Prevents runaway token usage
  on dense documents with permissive extraction. Track `triples_capped` in stats.
- [x] **Two-tier query model.** `riverbank query` (default): trusted graph only
  — strict, fast, conservative. `riverbank query --include-tentative`: unions
  trusted + tentative graphs, results ordered by confidence descending —
  discovery-focused. Documented as a first-class CLI feature pair, not an
  implementation detail.
- [x] **Rejected triple analysis.** `riverbank explain-rejections --profile
  --since 1h` shows triples discarded in the last run: evidence span not found,
  below noise floor, or ontology mismatch. Feeds back into prompt improvement
  and surfaces which implied facts the conservative prompt was silently losing.
- [x] **Coreference resolution.** Before fragmentation, run a lightweight
  coreference resolution pass on the full document text to replace pronouns
  and anaphoric references with their resolved entity names: "it" →
  "the Pipeline", "this component" → "the Dataset Writer". Two modes
  controlled by `preprocessing.coreference: llm | spacy | disabled`:
  (a) LLM call with prompt "Replace all pronouns and anaphoric references
  in the following text with the entity they refer to. Return the full
  resolved text."; (b) spaCy `neuralcoref` or `coreferee` model (no extra
  LLM call). Only high-confidence resolutions applied — ambiguous pronouns
  left unchanged. Fragment-boundary coreference breaks are the primary reason
  procedural corpora produce phantom entities like `ex:_it`. Significant yield
  improvement on procedure, runbook, and tutorial corpora.
- [x] **Overlapping fragment windows.** `overlap_sentences` config in the
  fragmenter block prepends the last N sentences of the previous fragment to
  recover facts split across boundaries. Duplicate triples from overlap regions
  deduplicated by content hash.
- [x] **Literal normalization.** Normalize string literals (lowercase + trim),
  dates (ISO 8601 canonical form), and IRIs before writing. Deduplicate on
  normalized form; keep the highest-confidence instance.
- [x] **Compact output schema.** Replace verbose `_TripleIn` JSON field names
  with short keys (`s`, `p`, `o`, `c`, `e`, `cs`, `ce`) to save ~20 output
  tokens per triple. Mapped back to full field names in `ExtractionResult`.
  Saves ~300 output tokens per fragment (15 triples × 20 tokens), partially
  offsetting the input token increase from ontology and CQ injection.
  Controlled by `token_optimization.compact_output_schema: true` in profile.
- [x] **Token budget manager.** `max_input_tokens_per_fragment: 3000` in the
  `token_optimization` profile block. When the assembled prompt (system +
  entity catalog + few-shot + corpus context + fragment) exceeds the budget,
  components are trimmed in priority order: few-shot → corpus context → entity
  catalog → doc summary. Fragment text is never truncated. Uses byte-length
  approximation (`÷ 4`) for Ollama where tiktoken is unavailable. Mandatory
  companion to v0.13.0's knowledge-prefix adapter, which adds +100–300 tokens
  per fragment.
- [x] **Merged preprocessing for short documents.** For documents below
  `merge_preprocessing_below_chars: 4000`, combine the document summary and
  entity catalog into a single LLM call. Halves preprocessing LLM calls for
  short documents and saves ~2 000 input tokens per document.
- [x] **Extraction stats.** Track `triples_trusted`, `triples_tentative`,
  `triples_discarded`, `triples_rejected_ontology`, `triples_capped`.

**Exit criterion:** the 3-document example corpus produces ≥ 2x more triples
than v0.11.0 (trusted + tentative combined). CQ coverage with
`--include-tentative` exceeds 75%. Safety cap prevents any single fragment from
producing more than 50 triples. Total prompt tokens per ingest run do not
exceed the v0.11.0 baseline by more than 20% when `token_optimization` is
enabled (the permissive prompt additions are offset by compact schema,
budget trimming, and the v0.11.1 quick wins).

---

### v0.12.1 — Permissive Extraction Phase B

Goal: complete the tentative graph lifecycle by adding evidence accumulation,
explicit promotion, and the tooling to understand what the pipeline discards.

- [x] **Confidence consolidation (noisy-OR).** When a triple `(s, p, o)` is
  extracted from multiple fragments, consolidate confidence via
  $c_{final} = 1 - \prod_i (1 - c_i)$. Multi-provenance evidence spans stored
  per triple. Source diversity scoring: corroboration from multiple fragments
  of the same document counts as one vote (prevents correlated hallucination
  promotion from templated or copied documents).
- [x] **`riverbank promote-tentative`.** Explicit CLI command — promotion is never
  automatic. Requires `--dry-run` review before committing. Promotes tentative
  triples whose consolidated confidence crosses the trusted threshold. Writes
  `pgc:PromotionEvent` provenance records. Track `triples_promoted` in stats.
- [x] **Functional predicate hints in profile YAML.** Annotate predicates as
  functional (`max_cardinality: 1`) in the `predicate_constraints` block.
  Used in two ways: the extraction prompt says "pick the most specific value
  only" for functional predicates; contradiction detection in v0.13.0 uses the
  annotations to detect `(s, p, o₁)` vs `(s, p, o₂)` conflicts.
- [x] **`riverbank explain-rejections`.** `--profile --since 1h` shows triples
  discarded in the last run, grouped by reason: evidence span not found,
  below noise floor, ontology mismatch, safety cap. Feeds back into prompt
  improvement and surfaces which implied facts the conservative prompt was
  silently losing.
- [x] **`triples_promoted` stat.** Track in run stats alongside `triples_trusted`,
  `triples_tentative`, `triples_demoted`.

**Exit criterion:** `promote-tentative` successfully promotes at least one triple
after a second ingest pass. `riverbank explain-rejections` shows at least 5
correctly implied triples that Phase A discarded. Source diversity scoring
prevents a triple corroborated only by fragments of the same document from
crossing the promotion threshold.

---

### v0.13.0 — Entity Convergence

Goal: make the entity and predicate vocabularies converge and stabilise, close
the cold-start problem via schema induction, and complete the tentative graph
lifecycle with contradiction detection and automatic cleanup. These are the
critical correctness foundations — without stable vocabularies, the extraction
feedback loops planned for v0.13.1 learn from noisy data.

- [x] **Predicate normalization.** Embed predicate labels, cluster by similarity,
  map non-canonical predicates to ontology-defined canonical forms. Companion
  to entity deduplication — reduces predicate vocabulary by 30–50%.
- [x] **Incremental entity linking with synonym rings.** Persistent
  `entity_registry` table (IRI, label, type, embedding, first_seen, doc_count)
  grows as documents are processed. Before extraction, top-K relevant entities
  are injected as "KNOWN ENTITIES — prefer these IRIs." New CLI:
  `riverbank entities list` and `riverbank entities merge`.
  The vocabulary pass now explicitly produces `skos:altLabel` triples for every
  discovered variant (synonym rings, per ANSI Z39.19): "Dataset" / "data set" /
  "datasets" → one entity with three alt-labels. The `pg:fuzzy_match()` function
  validates synonymy before writing. Synonym rings improve query recall and
  anchor the entity linker to attested surface forms rather than canonical-only
  matching.
- [x] **Contradiction detection & demotion.** For functional predicates annotated
  in the profile YAML (from v0.12.0), detect when new `(s, p, o₂)` conflicts
  with existing `(s, p, o₁)`. Reduce confidence of both triples by 30%; demote
  below threshold. Create `pgc:ConflictRecord`. Works as an identity
  verification layer: triples that survive contradiction detection are
  demonstrably more trustworthy.
- [x] **`riverbank induce-schema`.** Cold-start onboarding: after an initial
  unconstrained extraction pass, collect all unique predicates and entity types
  from the graph, compute frequency statistics, and ask the LLM to propose a
  minimal OWL ontology (class hierarchy, domain/range, cardinality constraints).
  Present for human review before writing to `ontology/`. A second extraction
  pass with the induced ontology as constraints produces 2x better precision.
  Removes the adoption bottleneck: users no longer need ontology expertise to
  get quality results.
- [x] **Automatic tentative cleanup.** Track `first_seen` timestamp for tentative
  triples. Auto-run after each ingest: archive tentative triples that were
  never promoted and have not been corroborated within the configurable TTL
  (default 30 days). `riverbank gc-tentative --older-than 30d` available
  for manual invocation; `tentative_ttl_days` in profile YAML to configure.
  Without automatic cleanup, the tentative graph grows indefinitely and
  becomes noise.
- [x] **Quality regression tracking.** `riverbank benchmark --profile <name>
  --golden tests/golden/<name>/ --fail-below-f1 0.85` re-extracts the golden
  corpus and compares against ground truth (precision, recall, F1). Runs in
  CI on every release; fails the build if quality drops.

**Exit criterion:** entity duplication rate across a 10-document corpus is
< 1.15x. Synonym ring extraction produces `skos:altLabel` triples for ≥ 80%
of entities that have attested surface variants. Contradiction detection flags
at least one functional predicate conflict in a test run. Tentative cleanup
auto-runs and archives stale triples without manual intervention.
`riverbank benchmark` CI step catches a deliberately degraded prompt.

---

### v0.13.1 — Extraction Feedback Loops

Goal: close the self-improvement loop — the pipeline learns from its own
high-confidence outputs to improve future extractions. Depends on stable
vocabularies from v0.13.0; without them, feedback loops learn from noisy data.

- [x] **Auto few-shot expansion.** After validated ingests where CQ coverage
  exceeds threshold, high-confidence triples that satisfy competency questions
  are automatically sampled and appended to the profile's golden examples file.
  Capped at 10–15 examples per profile with diversity constraints (no two
  examples with the same predicate+type combination). CQs drive selection,
  completing the CQ-as-north-star feedback cycle begun in v0.12.0.
- [x] **Semantic few-shot selection.** Upgrade `FewShotInjector` to support
  `selection: semantic`. Embeds the fragment text and the golden examples at
  injection time and selects the top-K most similar examples by cosine
  similarity. Reduces injected examples from 3 to 1–2 highly relevant ones —
  saves ~80–150 tokens per fragment while anchoring the LLM to the most
  topically relevant examples. Falls back to random when sentence-transformers
  is unavailable.
- [x] **Batched verification.** Upgrade `VerificationPass` to group
  low-confidence triples into batches of up to `verification.batch_size: 5`
  per LLM call instead of one call per triple. Saves ~3 400 tokens for a
  typical 20-triple verification run.
- [x] **Knowledge-prefix adapter.** At extraction time, retrieve the local
  neighborhood of already-extracted entities from pg_ripple and inject as a
  structured "KNOWN GRAPH CONTEXT" prefix. Improves consistency of new
  extractions with the existing graph and reduces contradictory triples.
  Requires the v0.12.0 token budget manager — the graph context block is
  capped at `max_graph_context_tokens: 200` (default) to prevent prompt
  explosion.

**Exit criterion:** auto-expanded few-shot bank has ≥ 8 examples after two
full ingest cycles. Semantic few-shot selection demonstrably selects more
relevant examples than random (measured by extraction precision on held-out
corpus). Batched verification issues ≤ 4 LLM calls for a 20-triple
verification run (instead of 20). Knowledge-prefix adapter improves
entity IRI consistency across documents.

---

### v0.14.0 — Structural Improvements & Reasoning

Goal: improve fragment quality, add deductive reasoning, and support
grammar-constrained output for local models.

- [x] **Constrained decoding.** For Ollama backends, use grammar-constrained
  decoding via the `format` parameter to force JSON schema conformance at
  decode time. Eliminates 100% of JSON parsing failures for local models.
- [x] **Semantic chunking.** Embedding-based boundary detection: embed each
  sentence, split where cosine similarity drops below a threshold (topic
  transition). Fragments align with semantic units rather than fixed-size
  or heading-based boundaries.
- [x] **SHACL shape validation.** Define a `pgc-shapes.ttl` shapes graph
  alongside the ontology. After ingest, validate the named graph via pyshacl.
  Report violations as diagnostics; optionally reduce confidence of violating
  triples. CLI: `riverbank validate-shapes --graph --shapes`.
- [x] **SPARQL CONSTRUCT rules.** Profile-specific inference rules defined as
  SPARQL CONSTRUCT queries. Run after ingest, writing results to
  `graph/inferred`. Transparent, auditable, domain-specific reasoning.
- [x] **OWL 2 RL forward-chaining.** Lightweight deductive closure via owlrl:
  `owl:inverseOf`, `rdfs:subClassOf` transitivity, domain/range type
  assertions, `owl:TransitiveProperty`. Results written to `graph/inferred`
  — never contaminates the asserted evidence base.
**Exit criterion:** constrained decoding eliminates JSON parse errors in
Ollama CI tests. Semantic chunking produces fewer orphan triples than
heading-based fragmentation on a test corpus. OWL 2 RL closure at least
doubles queryable type assertions.

---

### v1.0.0 — Stable Release

Goal: full API stability guarantee; production SLOs that an operations team
can reference in a service-level agreement.

- API stability: all public Python APIs, CLI commands, and SPARQL vocabulary
  (`pgc:` ontology) follow semantic versioning; no breaking changes without a
  major version bump.
- Signed release artifacts: release wheel and sdist signed with Sigstore
  (`cosign`); signatures published to the Rekor transparency log.
- Helm chart stability: `helm install riverbank riverbank/riverbank` works
  on any Kubernetes 1.28+ cluster with the pg_ripple chart as a dependency;
  chart version follows the same semver contract as the Python package.
- SLOs verified in CI: worker availability ≥ 99.5% (rolling 30 days),
  p95 fragment-to-graph latency < 30 s, MTTR from LLM outage < 5 min.

---

## How these releases fit together

```
v0.1.0  ─── Skeleton: CLI, catalog migrations, no-op extractor, docker compose up
    │
v0.2.0  ─── MVP ingestion: Markdown → triples with citations, confidence, fragment skip
    │
v0.3.0  ─── MVP completion: query, runs, cost dashboards, golden corpus CI gate
    │
v0.4.0  ─── Incremental compilation core: dependency graph, explain, recompile flow,
    │        vocabulary pass, SKOS shape bundle, tenant_id schema scaffold
    │
v0.5.0  ─── Multi-format parsing and enrichment: Docling, spaCy NER, fuzzy matching,
    │        embeddings, Singer/pg-tide connector
    │
v0.6.0  ─── Quality gates: Label Studio review loop, active-learning queue,
    │        example bank, Langfuse evals, lint flow, Prefect introduced
    │
v0.7.0  ─── Production hardening: Helm chart, multi-replica workers, Prometheus,
    │        Perses dashboards, audit trail, secret management, circuit breakers
    │
v0.8.0  ─── Advanced epistemic: negative knowledge, argument graphs, assumptions,
    │        9 epistemic statuses, model ensemble, contradiction explanation
    │
v0.9.0  ─── Multi-tenant + rendering: RLS activation, federated compilation,
    │        Markdown/JSON-LD page rendering, streaming SSE render
    │
v0.10.0 ─── Release infrastructure: PyPI package, riverbank sbom, docs auto-publish
    │
v0.11.0 ─── Preprocessing & post-processing: document preprocessing, corpus
    │        clustering, few-shot injection, entity dedup, self-critique verification
    │
v0.11.1 ─── Token efficiency: entity catalog filtering, adaptive preprocessing,
    │        Phase 2 pre-scan dedup, Ollama keep-alive caching
    │
v0.12.0 ─── Permissive extraction Phase A: ontology-grounded prompts, per-triple
    │        routing, graph/tentative, safety cap, pre-write filtering, overlapping
    │        fragments, literal normalization
    │
v0.12.1 ─── Permissive extraction Phase B: noisy-OR accumulation, source diversity
    │        scoring, promote-tentative, functional predicate hints, explain-rejections
    │
v0.13.0 ─── Entity convergence: predicate normalization, entity linking + synonym
    │        rings, induce-schema, contradiction detection, tentative cleanup,
    │        quality benchmarks
    │
v0.13.1 ─── Extraction feedback loops: auto few-shot expansion, semantic few-shot,
    │        batched verification, knowledge-prefix adapter
    │
v0.14.0 ─── Structural improvements: constrained decoding, semantic chunking,
    │        SHACL shapes, SPARQL CONSTRUCT rules, OWL 2 RL inference
    │
v0.15.0 ─── Wikidata evaluation: benchmark dataset, property alignment, scoring
    │        pipeline, per-domain/per-property breakdowns, calibration curves
    │
v0.15.1 ─── Extraction improvement loop: per-property recall gap analysis,
    │        prompt tuning from failure modes, 200+ novel-discovery annotations
    │
v0.16.0 ─── Tuning diagnostics: DiagnosticsEngine (10 rules), corpus drift
    │        detection, MeasurementStrategy, cold-start bootstrap, tuning_diagnostics
    │
v0.16.1 ─── Hypothesis generation: HypothesisGenerator, 5 mutation backends,
    │        TriedPatchesRegistry, MutationEffectivenessRegistry
    │
v0.17.0 ─── A/B testing harness: CandidateRouter, SPRT SignificanceTester,
    │        ExperimentPostmortem, replay evaluation for low-volume corpora
    │
v0.17.1 ─── Orchestration: TuningOrchestrator, PlateauDetector, TuningScheduler,
    │        full auto_tuning YAML schema, stale-sources, convergence state machine
    │
v0.17.2 ─── Observability: Perses dashboard, tuning history, Pareto frontier,
    │        insights CLI, tuning init, convergence/maintenance mode, docs
    │
v0.18.0 ─── Measurement architecture: three-tier ground truth pipeline, human
    │        spot-sampling, miscalibration detection, per-tier audit labels
    │
v0.18.1 ─── Learning from history: ProposalCalibrator, multi-property triage,
    │        cross-profile transfer, mutation half-life, learning validation
    │
v1.0.0  ─── Stable: API stability guarantee, signed artifacts, Helm stability, SLOs in CI
```

v0.1.0 through v0.3.0 build and close out the MVP. v0.2.0 is the first
release worth demoing to external eyes: a real Markdown corpus compiles into
a governed knowledge graph in under 10 minutes from a clean checkout. v0.3.0
adds the query and inspection surface that makes the MVP useful day-to-day and
closes the CI gate that prevents regressions across pg_ripple/pg_trickle
version bumps.

v0.4.0 is the structural turning point. Fragment-level incremental compilation
is what separates riverbank from a batch re-indexer. The demo for v0.4.0 exit
is the clearest possible: change one paragraph, watch exactly one fragment
recompile, observe the affected facts update in SPARQL, see the semantic event
arrive on the pg_trickle outbox — end-to-end in under a second. This release
also scaffolds the `tenant_id` column on all catalog tables so that the
multi-tenancy migration in v0.9.0 is additive-only.

v0.5.0 extends the ingest surface to office documents and web content, and adds
the enrichment layer (Docling, spaCy, embeddings) that quality gates and
epistemic features in v0.6.0 and later depend on. Splitting this from the
incremental compilation core keeps both releases at a size that can ship
independently.

v0.6.0 closes the human-in-the-loop gap. A knowledge graph without a review
loop is a confidence claim without evidence. Label Studio integration, the
active-learning review queue, and the example bank together enable the quality
feedback cycle that makes extraction quality measurably improve over time.
Prefect is introduced here rather than earlier because it is an operational
dependency (it needs the pipeline to be stable before it adds value).

v0.7.0 is the production gate. Nothing before v0.7.0 is appropriate for
a regulated production environment. The Helm chart, multi-replica workers,
audit trail, and secret management form the minimum deployable production unit.
This release is deliberately large; every item in it is non-negotiable for
production readiness. LLM provider circuit breakers (aiobreaker) protect
against runaway API costs; relay pipeline circuit breakers, DLQ, and backpressure
are configured in pg-tide and do not add Python code to riverbank.

v0.8.0 addresses the epistemic features that distinguish riverbank from a
generic RAG pipeline. Negative knowledge (explicit absences), argument graphs
(structured reasoning), and model ensemble (verification by disagreement) are
all features that generic pipelines do not provide. These are deferred to v0.8.0
because they require a working review loop (v0.6.0) and stable production
infrastructure (v0.7.0) to be useful in practice.

v0.9.0 is additive infrastructure: multi-tenancy RLS activation and rendering.
Both can be developed in parallel with v0.8.0 work. Multi-tenancy is
straightforward because the `tenant_id` column has been present since v0.4.0 —
activating RLS is a policy change, not a schema migration. Rendering is the
last mile between a compiled knowledge graph and a documentation site that
humans can read without a SPARQL client.

v0.10.0 is release infrastructure. `riverbank render` already exists; wiring it
to a CI publish step is straightforward. The PyPI package and SBOM command are
self-contained packaging work that does not touch the core pipeline. Separating
this from the stability declaration keeps v1.0.0 focused on the policy commitment
rather than implementation.

v0.11.0 captures the preprocessing and post-processing work done since v0.10.0:
document-level and corpus-level LLM preprocessing that gives extraction prompts
entity-aware context, few-shot injection from golden examples, entity
deduplication via embedding similarity, and self-critique verification that
quarantines low-confidence hallucinations. These are foundational capabilities
that all subsequent quality work builds on.

v0.12.0 is the extraction quality turning point. Two insights from the research
underpinning this release: first, LLM confidence scores are not probabilities
— they reflect how "explicitly stated" something sounds, not how likely it is
to be true. Models systematically over-score hallucinations and under-score
true implied facts. The four-tier extraction prompt (EXPLICIT/STRONG/IMPLIED/WEAK)
corrects this by treating confidence as a routing signal rather than a truth
claim. Second, permissive extraction and ontology grounding are codependent:
permissive extraction without vocabulary constraints floods the tentative graph
with noise; ontology constraints without permissive extraction still silently
discards implied facts. They must ship together. For small corpora, the benefit
is immediate — Phase A (permissive prompt + per-triple routing) alone delivers
higher single-pass recall before any accumulation mechanism is in place.

v0.13.0 makes the entity vocabulary self-improving. Incremental entity linking
ensures that document N knows about entities discovered in documents 1 through
N−1. Auto few-shot expansion means the system organically builds its own
training examples from high-quality extractions. The knowledge-prefix adapter
closes the feedback loop by injecting the existing graph neighborhood into
extraction prompts, so the LLM sees what's already been asserted.

v0.14.0 addresses structural quality: better fragment boundaries (semantic
chunking), deductive reasoning (OWL 2 RL, SPARQL CONSTRUCT), and output
reliability for local models (constrained decoding). These are medium-complexity
improvements that deliver the most value once the extraction pipeline itself is
producing high-quality triples.

v0.15.0 and v0.15.1 establish the external benchmark that auto-tuning depends
on. Without a reproducible, externally-validated quality signal, auto-tuning
has no north star. The 1,000-article Wikidata benchmark and per-property recall
gap analysis together provide the Tier 1 measurement signal that v0.16.x builds
on.

v0.16.0 is the observation layer. The tuning loop cannot improve what it cannot
measure. Before any mutation is proposed, every quality signal (F1, SHACL,
CQ coverage, confidence calibration, cost, corpus drift) must be queryable and
trendable. The DiagnosticsEngine rule set is expanded from 7 to 10 rules to
cover signals that only became visible after the v0.15.x evaluation work.

v0.16.1 automates the creative work. Historically an operator would read the
diagnostics and manually edit a YAML profile. The HypothesisGenerator replaces
that step with five mutation backends, each targeting a different class of quality
gap. The TriedPatchesRegistry and MutationEffectivenessRegistry ensure the
system learns from failures rather than repeating them.

v0.17.0 adds the safety net. Mutations generated in v0.16.1 must never go live
without statistical evidence that they help. The SPRT harness (replacing the
less efficient fixed-sample Welch's t-test) provides statistically valid
sequential decisions — promotes on large effects quickly, avoids false positives
on small noisy effects, and auto-generates a post-mortem for every failure.
Replay evaluation handles low-volume corpora that would otherwise never
accumulate enough fresh documents for a SPRT decision.

v0.17.1 closes the loop. The orchestrator wires all preceding components into
an autonomous cycle that runs on schedule and on event-driven triggers. Plateau
detection prevents the loop from wasting experiments in a local optimum.
Convergence mode reduces overhead on stable profiles. The full auto_tuning YAML
schema documents every knob an operator might need to adjust.

v0.17.2 makes the system legible. A tuning loop that operators cannot inspect
and intervene in will not be trusted. The Perses dashboard, lineage tree, Pareto
frontier, and insights CLI together give operators complete visibility into what
changed, why it was promoted, and how to roll it back if needed.

v0.18.0 makes auto-tuning truly corpus-agnostic. The three-tier measurement
architecture ensures the tuner works whether the corpus has a curated gold
reference dataset, only structural SHACL/CQ signals, or requires human
spot-sampling to bootstrap. Without this release, auto-tuning is only practical
for corpora that have already invested in labeled ground truth.

v0.18.1 makes the system self-improving across experiments. A naive tuning loop
treats each experiment as independent. v0.18.1 adds cross-experiment memory
(MutationEffectivenessRegistry with time decay), hypothesis bias correction
(ProposalCalibrator), parallel gap handling (multi-property triage), and
cross-corpus knowledge transfer (transfer suggestions). After 20+ experiments
the system should be measurably better at predicting which mutations will work
than it was at experiment 1.

v1.0.0 completes the API stability contract. The goal is not to add features at
1.0 but to guarantee that v0.x adopters can upgrade to v1.0 without breaking
changes, with signed artifacts and SLOs that an operations team can reference
in a service-level agreement.
