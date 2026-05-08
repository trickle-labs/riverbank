# riverbank — Adaptive Auto-Tuning

> **Date:** 2026-05-08 · **Revised:** 2026-05-08
> **Status:** Strategy document and implementation plan  
> **Project:** [riverbank](https://github.com/trickle-labs/riverbank)  
> **Prerequisites:** v0.15.1 (evaluation framework + improvement loops must be stable)  
> **Target:** v0.16.0 or v1.1.0 (post-stability release)

---

## 1. Executive Summary

riverbank already contains all the individual components needed for a
self-improving knowledge compiler: evaluation scoring against Wikidata ground
truth, recall-gap analysis, prompt tuning patch generation, auto few-shot
expansion, confidence-based routing, and noisy-OR consolidation. What is missing
is the **orchestration layer** that wires these components into a closed-loop
adaptive system — one that observes extraction outcomes, diagnoses weaknesses,
hypothesizes improvements, validates them safely, and promotes winning
configurations without human intervention.

This document proposes an **adaptive compiler** design that transforms
riverbank from a manually-tuned pipeline into a self-optimizing system. The
design draws on four research threads:

1. **DSPy** (Khattab et al., 2023) — compiling declarative LM calls into
   self-improving pipelines via automatic prompt and demonstration optimization
2. **OPRO** (Yang et al., 2023) — using LLMs as optimizers via natural language
   "gradients" over a solution history
3. **APO** (Pryzant et al., 2023) — automatic prompt optimization with beam
   search and textual gradient descent
4. **MIPRO** (Opsahl-Ong et al., 2024) — multi-stage program optimization with
   credit assignment across pipeline modules

The key insight from this literature is that **prompt optimization is not a
one-shot task** — it is an iterative search process that requires:
- A clear metric to maximize (riverbank has this: F1 vs. Wikidata)
- A feedback signal per iteration (riverbank has this: per-property recall/precision)
- A mechanism for generating candidate improvements (riverbank has the PromptTuner)
- A mechanism for validating candidates safely (riverbank needs this: A/B testing)

A second insight, less prominent in the literature, is equally important:
**a self-improving system must distinguish between three failure modes** that look
identical in aggregate metrics: (a) the profile is wrong for the data, (b) the data
has changed, (c) the measurement instrument is miscalibrated. Treating all three the
same way produces random walks that look like improvement. The plan below handles
each differently.

---

## 2. The Gap: What Exists vs. What's Needed

### 2.1 Existing feedback loop (manual)

```
                    ┌──────────────┐
                    │  Human       │ ← reviews results, edits profile YAML
                    └──────┬───────┘
                           │
       ┌───────────────────▼────────────────────┐
       │  riverbank ingest (profile v1)         │
       └───────────────────┬────────────────────┘
                           │
       ┌───────────────────▼────────────────────┐
       │  riverbank evaluate-wikidata            │
       └───────────────────┬────────────────────┘
                           │
       ┌───────────────────▼────────────────────┐
       │  riverbank recall-gap-analysis          │ → JSON report
       └───────────────────┬────────────────────┘
                           │
       ┌───────────────────▼────────────────────┐
       │  riverbank tune-extraction-prompts      │ → PromptPatch objects
       └───────────────────┬────────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Human       │ ← applies patches manually, bumps version
                    └──────────────┘
```

### 2.2 Target: closed-loop adaptive compiler

```
       ┌────────────────────────────────────────────────────────┐
       │  OBSERVE                                                │
       │  • Per-run metrics (F1, cost, latency, rejection rate)  │
       │  • Per-property recall/precision distributions          │
       │  • Confidence calibration drift                         │
       │  • Token efficiency (cost per accepted triple)          │
       └───────────────────────┬────────────────────────────────┘
                               │
       ┌───────────────────────▼────────────────────────────────┐
       │  DIAGNOSE                                               │
       │  • Recall-gap analysis (automated, periodic)            │
       │  • FP/FN pattern clustering                             │
       │  • Confidence miscalibration detection                  │
       │  • Cost regression detection                            │
       │  • SHACL score trend analysis                           │
       └───────────────────────┬────────────────────────────────┘
                               │
       ┌───────────────────────▼────────────────────────────────┐
       │  HYPOTHESIZE                                            │
       │  • Prompt mutations (APO/OPRO-style textual gradients)  │
       │  • Threshold sweeps (confidence, routing, SHACL)        │
       │  • Few-shot selection mutations                         │
       │  • Knowledge-prefix tuning                              │
       │  • Preprocessing strategy changes                       │
       └───────────────────────┬────────────────────────────────┘
                               │
       ┌───────────────────────▼────────────────────────────────┐
       │  VALIDATE                                               │
       │  • A/B cohort assignment (10% traffic to candidate)     │
       │  • Statistical significance testing (t-test / Bayesian) │
       │  • Cost-aware comparison (quality per dollar)           │
       │  • Safety guardrails (max regression, max cost growth)  │
       └───────────────────────┬────────────────────────────────┘
                               │
       ┌───────────────────────▼────────────────────────────────┐
       │  PROMOTE / DEMOTE                                       │
       │  • Winner becomes active profile                        │
       │  • Loser retained 7d (rollback window)                  │
       │  • Audit trail: parent → mutation → outcome             │
       │  • Prometheus/Langfuse event on promotion               │
       └────────────────────────────────────────────────────────┘
```

---

## 3. Design Principles

### 3.1 One mutation at a time

Inspired by DSPy's modular credit assignment (MIPRO), each tuning cycle
proposes exactly **one** change to the profile. This ensures:
- Clear attribution: if F1 improves, we know which change caused it
- Safe rollback: one knob to revert
- Interpretable history: the audit trail reads like a lab notebook

### 3.2 Metrics-first, not vibes-first

Every decision is grounded in a numeric signal:
- **Primary metric:** F1 vs. Wikidata ground truth (existing `Scorer`)
- **Secondary metrics:** cost per accepted triple, SHACL score, novel discovery
  rate, confidence calibration Pearson ρ
- **Guardrails:** maximum acceptable precision drop (5%), maximum cost increase
  (30%), minimum sample size for significance (30 articles)

### 3.3 Cost-awareness as a first-class constraint

Auto-tuning must not silently increase token spend. The system optimizes:

$$\text{objective} = F_1 - \lambda \cdot \frac{\text{cost}}{\text{cost}_{\text{baseline}}}$$

where $\lambda$ is a user-configurable cost sensitivity (default 0.1). This means
a 10% cost increase must be justified by a >1 percentage point F1 improvement.

### 3.4 Pareto-optimal exploration

The system maintains a **Pareto frontier** of profiles on the
quality-vs-cost plane. A candidate is promoted only if it dominates the current
active profile on at least one axis without regressing on either beyond
tolerance.

### 3.5 Human override at every layer

- Operators can freeze a profile (disable auto-tuning)
- Operators can reject a pending promotion
- Operators can inject manual mutations into the candidate queue
- Every promotion fires a pg-tide event (webhook, Slack, email)

### 3.6 Measurement integrity before tuning

Auto-tuning is only as good as the signal it optimizes. Before any mutation is
proposed, the system must establish *which measurement tier is available* for
the active corpus, and it must treat low-quality signal appropriately.

**Three failure modes look identical in aggregate F1:**

| Mode | Root cause | Wrong response | Correct response |
|------|-----------|---------------|-----------------|
| Profile mis-tuned | Extraction prompt too strict/loose | Tune thresholds | Correct |
| Corpus drift | Topic or style of new documents has shifted | Tune prompt for old domain | Detect drift, adapt separately |
| Measurement miscalibration | Wikidata property alignment stale or coverage map outdated | React to phantom signal | Re-calibrate alignment table first |

The `DiagnosticsEngine` must distinguish these before triggering hypothesis
generation. Corpus drift is detected by comparing the embedding centroid and
predicate distribution of recent fragments against the profile's training
window. Measurement miscalibration is detected by checking the alignment
table's coverage fraction against the corpus's top-K predicates.

### 3.7 One mutation at a time — with interaction awareness

Each tuning cycle proposes exactly **one** change. This ensures:
- Clear attribution: if F1 improves, we know which change caused it
- Safe rollback: one knob to revert
- Interpretable history: the audit trail reads like a lab notebook

The exception is **coordinated mutations** — parameter pairs known to interact
strongly (e.g., `trusted_threshold` + `safety_cap`, or `few_shot.max_examples`
+ `knowledge_prefix.top_entities`). When both parameters are flagged by the
same diagnosis rule, the `HypothesisGenerator` may propose a joint mutation
tagged `mutation_type='coordinated_sweep'`. These require manual approval
regardless of individual change size.

---

## 4. Architecture

### 4.1 New components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `TuningOrchestrator` | `src/riverbank/auto_tuning/orchestrator.py` | Top-level loop: observe → diagnose → hypothesize → validate → promote |
| `DiagnosticsEngine` | `src/riverbank/auto_tuning/diagnostics.py` | Aggregates run metrics, detects regressions, identifies gaps |
| `HypothesisGenerator` | `src/riverbank/auto_tuning/hypothesis.py` | Proposes profile mutations (LLM-assisted + rule-based) |
| `CandidateRouter` | `src/riverbank/auto_tuning/router.py` | Assigns fragments to baseline vs. candidate cohorts |
| `SignificanceTester` | `src/riverbank/auto_tuning/significance.py` | Welch's t-test / Bayesian comparison for promotion decisions |
| `MutationRegistry` | `src/riverbank/auto_tuning/registry.py` | Tracks mutation lineage (parent → child → outcome) |
| `TuningScheduler` | `src/riverbank/auto_tuning/scheduler.py` | Periodic trigger (APScheduler or Prefect) |

### 4.2 Database extensions

```sql
-- Mutation lineage and A/B experiment tracking
CREATE TABLE _riverbank.tuning_experiments (
    id              BIGSERIAL PRIMARY KEY,
    parent_profile_id BIGINT NOT NULL REFERENCES _riverbank.profiles(id),
    candidate_profile_id BIGINT NOT NULL REFERENCES _riverbank.profiles(id),
    mutation_type   TEXT NOT NULL,        -- 'prompt_patch', 'threshold_sweep', 'few_shot', ...
    mutation_yaml   TEXT NOT NULL,        -- the diff applied to parent
    rationale       TEXT NOT NULL,        -- human-readable explanation
    status          TEXT NOT NULL DEFAULT 'active',  -- 'active', 'promoted', 'demoted', 'expired'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    -- Metrics at resolution time
    baseline_f1     FLOAT,
    candidate_f1    FLOAT,
    baseline_cost   FLOAT,
    candidate_cost  FLOAT,
    sample_size     INTEGER,
    p_value         FLOAT,
    decision_reason TEXT
);

-- Per-article cohort assignment for A/B testing
CREATE TABLE _riverbank.tuning_cohorts (
    id              BIGSERIAL PRIMARY KEY,
    experiment_id   BIGINT NOT NULL REFERENCES _riverbank.tuning_experiments(id),
    source_iri      TEXT NOT NULL,
    cohort          TEXT NOT NULL,        -- 'baseline' or 'candidate'
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON _riverbank.tuning_cohorts (experiment_id, cohort);

-- Aggregated diagnostics snapshots (one per diagnosis cycle)
CREATE TABLE _riverbank.tuning_diagnostics (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT NOT NULL REFERENCES _riverbank.profiles(id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    window_hours    INTEGER NOT NULL,
    metrics         JSONB NOT NULL,       -- {f1, precision, recall, cost_per_triple, shacl_score, ...}
    gaps            JSONB NOT NULL,       -- [{property_id, recall, note}, ...]
    recommendations JSONB NOT NULL        -- [{mutation_type, rationale, priority}, ...]
);
```

### 4.3 Profile YAML extension

```yaml
# profiles/docs-adaptive-v1.yaml
name: docs-adaptive-v1
version: 1

# ... existing profile fields ...

auto_tuning:
  enabled: true
  
  # How often to run the diagnose→hypothesize cycle
  diagnosis_interval_hours: 24
  
  # A/B testing parameters
  validation:
    split_ratio: 0.10          # 10% of new sources go to candidate
    min_sample_size: 30        # minimum articles before significance test
    max_experiment_days: 14    # expire experiment after 14 days
    
  # Promotion / demotion thresholds
  thresholds:
    promotion_f1_delta: 0.02   # candidate must beat baseline by +2% F1
    demotion_f1_delta: -0.05   # demote if regression exceeds 5%
    max_cost_increase: 0.30    # max 30% cost increase tolerated
    min_precision: 0.60        # absolute precision floor (never go below)
    
  # Mutation generation settings
  mutations:
    max_active_candidates: 3   # max simultaneous experiments
    allowed_types:             # which mutation types are permitted
      - prompt_patch
      - threshold_sweep
      - few_shot_expansion
      - knowledge_prefix_tuning
      - preprocessing_strategy
    # LLM used for hypothesis generation (can differ from extraction model)
    hypothesis_model: "gpt-4o-mini"
    
  # Cost sensitivity: higher = more cost-averse
  cost_sensitivity: 0.10       # λ in the objective function
  
  # Notification on promotion/demotion
  notify:
    pg_tide_event: true        # emit event to pg-tide outbox
    log_level: "info"          # also log to structured log
```

---

## 5. Measurement Architecture

The auto-tuner cannot optimize what it cannot measure. The measurement
architecture defines *what* is measurable, *when*, and *how much to trust it*.
This section is the most important part of the plan — every subsequent decision
depends on it.

### 5.1 The Three-Tier Signal Hierarchy

For any given corpus, exactly one of three measurement tiers is available:

```
Tier 1 (Gold)   — Wikidata F1
  Available:    Wikipedia-sourced corpora with Wikidata-aligned entities
  Signal:       Absolute precision/recall/F1 per property against curated facts
  Drives:       All promotion/demotion decisions when available
  Limitation:   Only covers ~20% of real-world use cases

Tier 2 (Silver) — Structural quality
  Available:    Always (requires only the compiled graph)
  Signals:      SHACL score, CQ coverage fraction, predicate distribution,
                entity IRI fragmentation rate, noisy-OR promotion rate
  Drives:       Diagnosis and candidate selection when Tier 1 absent
  Limitation:   Measures consistency and structure, not factual correctness

Tier 3 (Bronze) — Self-assessed quality
  Available:    Always (requires only extraction run data)
  Signals:      Self-critique NLI pass rate, confidence calibration ρ,
                triple yield per fragment, rejection rate by reason,
                cost per accepted triple
  Drives:       Cost and efficiency optimisation; early-warning drift signal
  Limitation:   Can be gamed by over-confident or tautological extractions

Tier 4 (Human)  — Spot-sampling
  Available:    On demand (requires Label Studio + reviewer time)
  Signal:       Human-validated accuracy on a random sample of 20–50 triples
  Drives:       Re-anchoring calibration after N promotions without Tier 1 data
  Limitation:   Expensive; not automatable; sampled, not exhaustive
```

### 5.2 Tier Selection and Blending

The `DiagnosticsEngine` selects the appropriate tier automatically:

```python
class MeasurementStrategy:
    """Select and blend measurement tiers for a given profile and corpus."""
    
    def select(self, profile: CompilerProfile, corpus_stats: CorpusStats) -> MeasurementPlan:
        tier1_available = self._check_wikidata_coverage(corpus_stats)
        tier2_metrics   = self._compute_structural(profile)
        tier3_metrics   = self._compute_self_assessed(profile)
        
        if tier1_available:
            # Gold: use F1 as primary, structural/self-assessed as guards
            return MeasurementPlan(
                primary=tier1_available,
                guards=[tier2_metrics, tier3_metrics],
                confidence="high",
            )
        
        # Silver/Bronze blend: use composite structural score
        composite = self._compute_composite_score(tier2_metrics, tier3_metrics)
        
        # Trigger human spot-sampling if no Tier 1 data after N promotions
        if profile.promotions_since_human_review >= profile.spot_sample_every_n:
            return MeasurementPlan(
                primary=composite,
                guards=[tier3_metrics],
                confidence="low",
                request_human_review=True,
            )
        
        return MeasurementPlan(
            primary=composite,
            guards=[tier3_metrics],
            confidence="medium",
        )
```

**Composite score for Tier 2+3 (when Tier 1 is unavailable):**

$$\text{composite} = w_1 \cdot \text{shacl\_score} + w_2 \cdot \text{cq\_coverage} + w_3 \cdot \text{noisy\_or\_rate} + w_4 \cdot \text{calibration\_}\rho$$

Default weights: $w_1 = 0.35$, $w_2 = 0.30$, $w_3 = 0.20$, $w_4 = 0.15$.
The weights are themselves tunable (via the `measurement.weights` profile YAML
section) but require a Tier 1 calibration run to justify any change.

### 5.3 Human Spot-Sampling Protocol

When `MeasurementPlan.request_human_review = True`, the system:

1. Samples 20 triples uniformly at random from recent extractions (last 7d),
   stratified by predicate type
2. Enqueues them in Label Studio with task type `spot_check` (binary accept/reject)
3. Pauses hypothesis generation (not experiment execution — running experiments
   continue) until the review is complete
4. On completion, computes `human_accuracy = accepted / 20` and uses it to
   re-calibrate the composite score weights for this corpus

**Trigger condition:** default is every 5 promotions without Tier 1 data, configurable
via `auto_tuning.spot_sample_every_n_promotions` (default 5, minimum 2).

### 5.4 Corpus Drift Detection

Corpus drift must be detected *before* the diagnostics engine attributes a quality
drop to the profile. Two drift signals are tracked continuously:

**Embedding centroid drift:** The `pg_trickle` stream table maintains
`avg(embedding)::vector` per named graph. If the cosine distance between the
centroid of the last N fragments and the centroid of the profile's training window
exceeds a threshold, drift is flagged.

**Predicate distribution drift:** The distribution of extracted predicate types
(top-20 by frequency) is compared between the current sliding window and the
profile's baseline window using Jensen–Shannon divergence. A JSD above 0.15 flags
drift.

When either drift signal fires:
1. The `DiagnosticsEngine` labels the cycle as `drift_detected` rather than
   `quality_degraded`
2. Hypothesis generation shifts to **domain adaptation** mutations rather than
   quality-improvement mutations: enabling corpus-level clustering
   (`corpus_preprocessing`), re-generating the entity catalog for the new domain,
   or (with human approval) spawning a new child profile for the drifted segment

### 5.5 Measurement Miscalibration Detection

Before running the diagnosis cycle, verify that the measurement instrument is
itself calibrated:

- Wikidata alignment table: `alignment_coverage = aligned_predicates / top_k_corpus_predicates`
  If < 0.5, alignment table is outdated for this corpus; flag before diagnosing recall gaps
- CQ coverage: if the profile's competency questions don't cover any extracted
  predicates (CQ relevance < 0.2), the CQ-based signals are uninformative; flag
  before using them as guards
- Calibration freshness: if the last calibration run was > 30d ago, mark Tier 3
  confidence as stale

---

## 6. The Tuning Loop in Detail

*(See §6.1 through §6.7 in the Measurement Architecture section above — the loop
detail was expanded into the measurement section to keep measurement and tuning
steps co-located. This section header is retained for cross-reference.)*

---

## 7. Learning from History

One of the most important properties of a self-improving system is that it learns
*across experiments*, not just within them. The naive implementation of a tuning
loop treats each experiment as independent; an advanced one accumulates a living
memory of what works, what fails, and why.

### 7.1 Experiment Post-Mortem

After every experiment that ends in `'demoted'` or `'expired'`, the system
automatically runs an `ExperimentPostmortem`:

```python
@dataclass
class ExperimentPostmortem:
    experiment_id: str
    mutation_type: str
    failure_mode: str       # 'regression', 'no_improvement', 'expired'
    diagnostic_snapshot: DiagnosticsReport   # stored at creation time
    actual_f1_delta: float
    predicted_f1_delta: float   # from the hypothesis model
    calibration_error: float    # |predicted - actual|
    root_cause: str             # derived by analysis
    lesson: str                 # e.g. "threshold sweep does not help when corpus drift > 0.15 JSD"
```

Post-mortems are stored in `_riverbank.experiment_postmortems` and surface via
`riverbank tuning insights`.

### 7.2 Mutation Effectiveness Registry

The `MutationEffectivenessRegistry` maintains historical evidence about which
mutation types work for which failure modes:

```python
class MutationEffectivenessRegistry:
    """Track empirical effectiveness of mutation types by failure mode.
    
    Used by HypothesisGenerator to rank candidate mutations and by
    PromptMutator to avoid previously failed approaches.
    """
    
    @dataclass
    class Entry:
        mutation_type: str
        failure_mode: str        # matches DiagnosticsEngine rule ID
        corpus_domain: str       # coarse domain tag
        success_count: int
        failure_count: int
        mean_f1_lift: float
        last_success: datetime | None
        decay_weight: float      # time-decayed relevance (exp decay, half-life=90d)
    
    def recommend(self, failure_mode: str, corpus_domain: str) -> list[str]:
        """Return mutation types ranked by expected effectiveness."""
        entries = self._get_relevant_entries(failure_mode, corpus_domain)
        return sorted(
            entries,
            key=lambda e: e.success_count / max(e.success_count + e.failure_count, 1)
                          * e.decay_weight,
            reverse=True,
        )
    
    def record(self, mutation_type: str, failure_mode: str, corpus_domain: str,
               outcome: str, f1_delta: float) -> None:
        """Update registry after experiment resolves."""
        ...
```

The `HypothesisGenerator` consults this registry when choosing which mutation
type to try next. Rather than cycling mutation types in round-robin order, it
preferentially tries approaches that have worked before for this type of failure.

### 7.3 Cross-Profile Transfer

When a mutation is promoted for profile A in domain D, the system checks whether
other profiles share domain D and have similar failure modes. If so, it queues a
"transfer suggestion" — not an automatic mutation, but a recommendation:

```
Profile B (domain: biographies) has been successfully improved by 
"few_shot_expansion targeting P569" in Profile A. Profile B currently 
has P569 recall = 0.12. Consider running: riverbank tuning suggest --profile B
```

Transfer suggestions are surfaced in `riverbank tuning insights` and require
human approval before any action is taken.

### 7.4 Mutation Half-Life

The effectiveness of a mutation decays over time because:
- The underlying LLM may have changed (model provider updates)
- The corpus may have drifted
- What worked 6 months ago may not work today

All entries in the `MutationEffectivenessRegistry` are weighted by
$w = e^{-\lambda \cdot \Delta t}$ where $\Delta t$ is days since last success
and $\lambda = \ln(2) / 90$ (half-life of 90 days). Entries with $w < 0.1$
are still retained but flagged as "stale evidence" in recommendations.

---

## 8. Mutation Lineage and Audit Trail

Every profile carries a `generation` counter and a `parent_id`:

```yaml
# Auto-generated metadata (not hand-edited)
_tuning_metadata:
  generation: 3
  parent_profile: "docs-adaptive-v1@v2"
  mutation_type: "prompt_patch"
  mutation_applied_at: "2026-05-08T14:22:00Z"
  rationale: "Added targeted birthDate extraction instruction (P569 recall was 0.12)"
  experiment_id: 42
```

This creates a tree of profile variants:

```
docs-adaptive-v1@v1 (baseline)
├── docs-adaptive-v1@v2 (promoted: +3% F1 from threshold sweep)
│   ├── docs-adaptive-v1@v3 (promoted: +2% F1 from prompt patch)
│   │   └── docs-adaptive-v1@v4 (active candidate: few-shot expansion)
│   └── docs-adaptive-v1@v3-alt (demoted: -1% F1 from preprocessing change)
└── docs-adaptive-v1@v2-alt (expired: inconclusive after 14d)
```

The `riverbank tuning history` command displays this tree with metrics at each
node.

---

## 9. Safety Mechanisms

### 7.1 Guardrails

| Guardrail | Default | Behavior |
|-----------|---------|----------|
| Precision floor | 0.60 | Demote immediately if candidate precision < floor |
| Cost ceiling | 1.3× baseline | Demote if cost exceeds 130% of baseline |
| Max generation depth | 10 | Pause tuning; require human review before continuing |
| Max concurrent experiments | 3 | Queue new mutations until a slot opens |
| Freeze on regression | enabled | If F1 drops >5% in 24h, freeze ALL experiments |
| Minimum eval coverage | 10 articles | No promotion decision without ≥10 scored articles |

### 7.2 Rollback

```bash
# Manual rollback to any previous generation
riverbank tuning rollback --profile docs-adaptive-v1 --to-generation 2

# Emergency freeze: stop all experiments, revert to last promoted version
riverbank tuning freeze --profile docs-adaptive-v1

# Resume tuning after freeze
riverbank tuning unfreeze --profile docs-adaptive-v1
```

### 7.3 Human-in-the-loop checkpoints

Certain mutations require human approval before activation:

| Mutation type | Auto-approve? | Reason |
|---------------|---------------|--------|
| Threshold sweep (±1 step) | Yes | Bounded, reversible |
| Few-shot expansion (≤3 examples) | Yes | Additive, low risk |
| Prompt patch (≤50 words changed) | Yes | Small edit, bounded impact |
| Prompt patch (>50 words changed) | **No** | Large edit requires review |
| Preprocessing backend change | **No** | Structural change to pipeline |
| Model change | **No** | Fundamental capability shift |

When approval is required, the experiment enters `status='pending_review'` and
emits a notification event.

---

## 10. Integration with Existing Systems

### 8.1 Wikidata Evaluation (v0.15.x)

The auto-tuner uses `Scorer.score_article()` directly as its objective
function. No modification to the evaluation framework is needed — it is already
designed to produce per-property breakdowns that feed directly into the
diagnostics engine.

### 8.2 PromptTuner (v0.15.1)

The existing `PromptTuner` becomes a **backend** for the `HypothesisGenerator`.
Instead of producing patches for human review, its output feeds directly into
the mutation pipeline:

```python
# Before (manual):
tuner = PromptTuner()
report = tuner.analyze_json("eval_results.json")
patches = report.patches  # human reviews and applies these

# After (automated):
hypothesis_gen = HypothesisGenerator(backends=[
    PromptTunerBackend(),      # existing PromptTuner
    OPROBackend(),             # new: LLM-as-optimizer
    ThresholdSweepBackend(),   # new: grid search
    FewShotMutatorBackend(),   # new: evaluation-driven
])
mutation = hypothesis_gen.propose(diagnostics_report)
# → automatically creates experiment, assigns cohort, begins validation
```

### 8.3 RecallGapAnalyzer (v0.15.1)

The recall-gap report feeds into the `EvalDrivenFewShotMutator`:

```python
# Before: recall-gap-analysis → JSON → human injects examples manually
# After: recall-gap-analysis → FewShotMutator → experiment → A/B test → promote
```

### 8.4 FewShotExpander (v0.13.1)

The existing auto-expansion mechanism (CQ-gated) continues to operate
independently. The auto-tuner adds a **second** expansion path that targets
specific recall gaps rather than general high-confidence triples.

### 8.5 NoisyOR Consolidator (v0.12.1)

Promoted tentative triples provide **additional ground truth** for the auto-
tuner. When a triple is promoted via cross-document corroboration, the scorer
can use it as a "soft positive" in future evaluations (with lower weight than
Wikidata statements).

### 8.6 Prometheus Metrics (v0.7.0)

New gauges and counters:

```python
# Auto-tuning metrics
riverbank_tuning_experiments_active = Gauge(
    "riverbank_tuning_experiments_active",
    "Number of active A/B experiments",
    ["profile"]
)
riverbank_tuning_promotions_total = Counter(
    "riverbank_tuning_promotions_total",
    "Total profile promotions",
    ["profile", "mutation_type"]
)
riverbank_tuning_demotions_total = Counter(
    "riverbank_tuning_demotions_total",
    "Total profile demotions",
    ["profile", "mutation_type"]
)
riverbank_tuning_f1_current = Gauge(
    "riverbank_tuning_f1_current",
    "Current F1 score for active profile",
    ["profile"]
)
riverbank_tuning_cost_per_triple = Gauge(
    "riverbank_tuning_cost_per_triple",
    "Current cost per accepted triple (USD)",
    ["profile"]
)
```

### 8.7 Langfuse (v0.3.0)

Each experiment creates a Langfuse dataset with:
- Baseline cohort results
- Candidate cohort results
- Diff annotations (which triples changed between variants)

This enables visual inspection of what changed and why.

---

## 11. CLI Commands

```bash
# Run diagnosis manually
riverbank tuning diagnose --profile docs-adaptive-v1 --window 48h

# View active experiments
riverbank tuning experiments --profile docs-adaptive-v1

# View mutation history (lineage tree)
riverbank tuning history --profile docs-adaptive-v1

# Manually trigger a mutation (bypasses diagnosis)
riverbank tuning propose --profile docs-adaptive-v1 --type prompt_patch

# Approve a pending experiment
riverbank tuning approve --experiment-id 42

# Reject a pending experiment
riverbank tuning reject --experiment-id 42 --reason "too risky for production"

# Freeze / unfreeze
riverbank tuning freeze --profile docs-adaptive-v1
riverbank tuning unfreeze --profile docs-adaptive-v1

# Rollback
riverbank tuning rollback --profile docs-adaptive-v1 --to-generation 2

# Run the full loop once (for testing)
riverbank tuning run-once --profile docs-adaptive-v1

# Show Pareto frontier (quality vs. cost)
riverbank tuning pareto --profile docs-adaptive-v1
```

---

## 12. Worked Example

### Initial state

Profile `wikidata-eval-v1` achieves:
- F1 = 0.42, Precision = 0.68, Recall = 0.31
- Cost per triple = $0.0023
- P569 (birthDate) recall = 0.12
- P106 (occupation) recall = 0.08

### Cycle 1: Diagnosis

The `DiagnosticsEngine` identifies:
- Priority 3: P569 recall is 0.12 (below 0.25 → "prompt lacks examples")
- Priority 3: P106 recall is 0.08 (below 0.25 → "prompt lacks examples")
- Priority 5: Confidence miscalibrated (ρ = 0.21, bucket 0.75–1.0 has only 45% accuracy)

### Cycle 1: Hypothesis

The `HypothesisGenerator` proposes: **few_shot_expansion** targeting P569 and P106.

Mutation YAML:
```yaml
few_shot:
  additional_examples:
    - text: "Marie Curie was born on 7 November 1867 in Warsaw"
      triple: "(ex:Marie_Curie, pgc:birthDate, '1867-11-07')"
      property: P569
    - text: "She worked as a physicist and chemist"
      triple: "(ex:Marie_Curie, pgc:occupation, ex:Physicist)"
      property: P106
```

### Cycle 1: Validation

10% of new articles are processed with the candidate profile. After 35 articles:

| Metric | Baseline | Candidate |
|--------|----------|-----------|
| F1 | 0.42 | 0.47 |
| P569 recall | 0.12 | 0.58 |
| P106 recall | 0.08 | 0.34 |
| Cost/triple | $0.0023 | $0.0025 |
| p-value | — | 0.003 |

### Cycle 1: Promotion

- ΔF1 = +0.05 > promotion threshold (0.02) ✓
- ΔCost = +8.7% < max cost increase (30%) ✓
- p-value = 0.003 < 0.05 ✓
- Precision = 0.71 > precision floor (0.60) ✓

**Result:** Candidate promoted → becomes `wikidata-eval-v1@v2`.

### Cycle 2: Diagnosis (24h later)

With the new profile active:
- F1 = 0.47 (stable)
- Confidence miscalibration still present (ρ = 0.25)
- `trusted_threshold` at 0.70 but bucket 0.5–0.75 has 72% accuracy

### Cycle 2: Hypothesis

The `ThresholdSweepBackend` proposes: lower `trusted_threshold` from 0.70 → 0.65
(move more triples from tentative to trusted, since the 0.5–0.75 bucket is
well-calibrated).

### Cycle 2: Validation

After 42 articles:
- F1: 0.47 → 0.50 (+0.03)
- Cost: $0.0025 → $0.0024 (slightly lower — fewer self-critique calls needed)
- p-value: 0.012

**Result:** Promoted → `wikidata-eval-v1@v3`.

### After 5 cycles

The profile has evolved from F1=0.42 to F1=0.56 with only 12% cost increase,
without any human intervention. The mutation tree shows exactly which changes
contributed and by how much.

---

## 13. Comparison with Related Work

| Approach | Key idea | riverbank adaptation |
|----------|----------|---------------------|
| **DSPy** (Stanford, 2023) | Declarative LM pipelines with compiler-optimized prompts and demonstrations | Profile YAML is the "signature"; the tuning loop is the "teleprompter" |
| **OPRO** (Google DeepMind, 2023) | LLM generates new prompts from solution history + scores | `PromptMutator` uses the same pattern: past results + failure analysis → improved prompt |
| **APO** (Microsoft, 2023) | Natural language "gradients" (criticisms) propagated into prompt edits | `PromptTuner.generate_patches()` produces textual gradients from FP/FN patterns |
| **MIPRO** (Stanford, 2024) | Multi-stage pipeline optimization with credit assignment | Per-module diagnosis: is the problem in preprocessing, extraction, or validation? |
| **Self-Rewarding LMs** (Meta, 2024) | Model provides its own reward signal for iterative DPO | Verification pass (`nli` backend) provides a self-critique score; high-confidence verified triples feed back as ground truth |
| **Bayesian Optimization** (classical) | Surrogate model + acquisition function for expensive black-box optimization | Threshold sweeps use a simpler grid + adjacent-step heuristic (fewer parameters than classic BO warrants) |
| **Multi-Armed Bandits** (classical) | Explore vs. exploit under uncertainty | A/B split ratio could be adaptive (Thompson sampling); deferred to Phase B |

### Why not just use DSPy directly?

DSPy is designed for **prompt-and-demonstration optimization** of individual LM
calls. riverbank's tuning problem is broader:

1. **Multi-stage pipeline** — preprocessing, fragmentation, extraction,
   validation, and post-processing each have tunable parameters
2. **Non-prompt parameters** — confidence thresholds, entity counts, token
   budgets are numeric, not natural language
3. **Cost as a first-class constraint** — DSPy optimizes for a single metric;
   riverbank needs Pareto-optimal exploration on quality×cost
4. **Evaluation against external ground truth** — DSPy uses held-out training
   examples; riverbank uses Wikidata as an independent oracle
5. **Production safety** — A/B testing with statistical significance,
   guardrails, and human override are not part of DSPy's design

The architecture borrows DSPy's *ideas* (textual gradients, demonstration
selection, modular credit assignment) but implements them within riverbank's
existing profile and evaluation infrastructure.

---

## 14. Implementation Plan

Phases A–E address the core auto-tuning loop. Phases F–G address the new
components added by this revised plan (measurement architecture, learning from
history, corpus drift, plateau detection, SPRT, and post-promotion recompilation).

### Phase A: Instrumentation & Diagnostics (2 weeks)

**Goal:** Close the observability gap — make all tuning-relevant metrics
queryable and trendable. Add corpus drift detection and measurement tier selection.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Add `_riverbank.tuning_diagnostics` table + Alembic migration | 2h | — |
| Implement `MeasurementStrategy` with three-tier selection logic | 1d | Scorer, SHACL module |
| Implement `DiagnosticsEngine` with 10 diagnosis rules (expanded from 7) | 3d | Scorer, RecallGapAnalyzer, MeasurementStrategy |
| Add corpus drift detection: embedding centroid + JSD signals | 1d | pg_trickle stream table |
| Add cold-start bootstrap mode (< min_history_runs → skip baseline rules) | 4h | DiagnosticsEngine |
| `riverbank tuning diagnose` CLI command | 4h | DiagnosticsEngine |
| Add `riverbank_tuning_f1_current` and `cost_per_triple` Prometheus gauges | 2h | metrics module |
| Aggregate per-run metrics into sliding-window snapshots (SQL view) | 4h | existing runs table |
| Store full `DiagnosticsReport` JSON per diagnosis (not just aggregates) | 2h | DiagnosticsEngine |
| Unit tests for diagnosis rules + drift detection | 1.5d | — |

**Acceptance:** `riverbank tuning diagnose --profile X` produces a JSON report
with gaps, patterns, ranked recommendations, active measurement tier, and drift
status.

### Phase B: Hypothesis Generation with Mutation Registry (2 weeks)

**Goal:** Automatically generate profile mutations from diagnostic reports.
Add the `TriedPatchesRegistry` and `MutationEffectivenessRegistry` from §7.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Define `ProfileMutation` dataclass | 2h | — |
| Implement `TriedPatchesRegistry` + `_riverbank.tried_patches` table | 1d | — |
| Implement `MutationEffectivenessRegistry` + `_riverbank.mutation_effectiveness` table | 1d | — |
| Implement `PromptMutatorBackend` (OPRO-style, feeds tried-patches and effectiveness to LLM) | 2d | DiagnosticsEngine, TriedPatchesRegistry |
| Implement `ThresholdSweepBackend` (grid + adjacent-step) | 1d | — |
| Implement `EvalDrivenFewShotMutator` (recall-gap → examples) | 1d | RecallGapAnalyzer |
| Implement `KnowledgePrefixTuner` (token budget optimization) | 4h | KnowledgePrefixAdapter |
| Implement coordinated mutation detection (§6.3.7) | 1d | DiagnosticsEngine |
| Wire backends into `HypothesisGenerator` with effectiveness-ranked selection | 1d | all backends, MutationEffectivenessRegistry |
| `riverbank tuning propose` CLI command | 4h | HypothesisGenerator |
| Unit tests for each mutation backend + registry | 2d | — |

**Acceptance:** `riverbank tuning propose --profile X` produces a valid candidate
profile YAML with documented rationale, and does not reproduce recently-tried-and-failed
mutations.

### Phase C: A/B Testing Harness with SPRT (2 weeks)

**Goal:** Route traffic to candidate profiles and compare outcomes using
statistically correct sequential testing.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Add `_riverbank.tuning_experiments` and `tuning_cohorts` tables | 4h | — |
| Implement `CandidateRouter` with consistent hashing | 1d | — |
| Modify `pipeline.ingest()` to check for active experiments and route | 1d | CandidateRouter |
| Replace Welch's t-test with SPRT (`SignificanceTester` with `_compute_llr`) | 1.5d | scipy |
| Implement held-out validation set management (20% of benchmark reserved) | 1d | Scorer |
| Implement event-driven OBSERVE trigger (after N articles, not just periodic) | 4h | pipeline.ingest() |
| Implement promotion/demotion logic with audit trail + `ExperimentPostmortem` | 1d | MutationEffectivenessRegistry |
| `riverbank tuning experiments` CLI (list, approve, reject) | 1d | — |
| pg-tide event emission on promotion/demotion | 4h | pg-tide integration |
| Integration tests: full cycle (propose → route → score → promote) | 2d | all above |

**Acceptance:** A synthetic experiment with a clearly-better candidate is
automatically promoted. The SPRT reaches a decision in fewer articles than
the fixed-sample test for large effects, and reaches the correct decision on
small effects given sufficient data.

### Phase D: Orchestration, Plateau Detection, and Scheduling (1.5 weeks)

**Goal:** Wire the full loop to run autonomously, with plateau detection and
restart strategy.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Implement `TuningOrchestrator` (diagnose → hypothesize → validate → promote) | 1d | Phases A–C |
| Implement `PlateauDetector` with 3-window rolling mean check (§6.6) | 1d | TuningOrchestrator |
| Implement plateau response: strategy shift, search-space expansion, escalation | 1d | PlateauDetector, HypothesisGenerator |
| Implement `TuningScheduler` (APScheduler periodic + event-driven trigger) | 4h | TuningOrchestrator |
| Add `auto_tuning:` section to profile YAML schema (including measurement weights) | 4h | CompilerProfile |
| `riverbank tuning run-once` CLI command | 2h | TuningOrchestrator |
| Safety guardrails: freeze on regression, generation depth limit | 1d | — |
| Post-promotion recompilation policy (`recompile_on_promotion` config) | 1d | TuningOrchestrator |
| `riverbank tuning stale-sources` CLI command | 4h | sources table |
| End-to-end integration test with Wikidata benchmark subset | 2d | all above |

**Acceptance:** `riverbank tuning run-once` executes the full loop and either
promotes, demotes, or logs "no improvement found". After 3 small-delta promotions,
plateau detection fires and strategy shifts.

### Phase E: Observability & Polish (1 week)

**Goal:** Dashboards, lineage visualization, and operator experience.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Prometheus metrics for all tuning events | 4h | Phase D |
| Perses dashboard panel: tuning experiments, F1 trend, cost trend | 1d | Prometheus |
| `riverbank tuning history` CLI (tree visualization) | 1d | MutationRegistry |
| `riverbank tuning pareto` CLI (quality×cost frontier) | 4h | — |
| `riverbank tuning insights` CLI (post-mortems + effectiveness registry) | 1d | §7 components |
| Langfuse dataset integration (experiment results as datasets) | 1d | Langfuse |
| `riverbank tuning rollback` and `freeze`/`unfreeze` commands | 1d | — |
| Documentation: how-to guide, concepts page | 1d | — |

**Acceptance:** Operators can visualize the tuning history, understand why each
promotion happened, and intervene at any point.

### Phase F: Measurement Architecture — Non-Wikidata Corpora (1.5 weeks)

**Goal:** Enable auto-tuning for arbitrary domain corpora without Wikidata
ground truth.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Implement `MeasurementPlan` and composite score computation (§5.2) | 1d | DiagnosticsEngine |
| Human spot-sampling integration with Label Studio (§5.3) | 1.5d | Label Studio connector |
| Add `spot_sample_every_n_promotions` config; trigger logic | 4h | TuningOrchestrator |
| Implement measurement miscalibration detection (alignment coverage check, §5.5) | 4h | eval module |
| Update `SignificanceTester` to use composite score when Tier 1 unavailable | 4h | SignificanceTester |
| Add per-tier confidence labels to all promotion audit records | 2h | audit trail |
| Add `riverbank tuning status` output: current measurement tier + drift status | 2h | CLI |
| Integration tests: full cycle without Wikidata ground truth | 1.5d | — |

**Acceptance:** `riverbank tuning diagnose --profile X` correctly identifies Tier
1/2/3 availability and adjusts recommendations accordingly. Human spot-sampling
is triggered after N promotions on a non-Wikidata corpus.

### Phase G: Learning from History (1 week)

**Goal:** The system accumulates cross-experiment knowledge and transfers it.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Implement `ExperimentPostmortem` analysis and storage | 1d | Phase C outcomes |
| Add cross-profile transfer suggestions (§7.3) | 1d | MutationEffectivenessRegistry |
| Implement mutation half-life decay in effectiveness registry (§7.4) | 4h | MutationEffectivenessRegistry |
| Surface insights in `riverbank tuning insights` | 4h | Phase E CLI |
| A/B test that Phase G actually improves proposal hit-rate | 1d | — |

**Acceptance:** After 20+ experiments, recommended mutation types succeed at a
higher rate than random selection. `riverbank tuning insights` surfaces actionable
cross-profile transfer suggestions.

---

## 15. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Auto-tuning degrades quality silently | Medium | High | Precision floor guardrail + freeze on regression + 7-day rollback window + SPRT early stopping |
| LLM-generated mutations are nonsensical | Medium | Low | Syntax validation + bounded impact (one mutation per cycle) + A/B testing catches bad mutations |
| Cost explosion from hypothesis generation | Low | Medium | Hypothesis model is cheap (gpt-4o-mini); cap at 1 hypothesis/day |
| Overfitting to Wikidata benchmark | Medium | Medium | Held-out validation set (20% of benchmark never used during A/B); novel discovery rate tracking; periodic benchmark expansion |
| Statistical noise in small corpora / underpowered tests | High | Medium | SPRT reaches decision faster on large effects; minimum 50 articles with explicit power trade-off documented; expire inconclusive experiments after 14 days |
| Corpus drift misdiagnosed as profile weakness | Medium | High | Corpus drift detection (embedding centroid + JSD) must clear before hypothesis generation; drift → domain adaptation path, not quality tuning |
| Mutation loop (same fix tried repeatedly) | Medium | Medium | TriedPatchesRegistry suppresses mutations tried ≥3 times in 30d; MutationEffectivenessRegistry favours proven approaches |
| Tuning plateau wastes experiments | Medium | Low | Plateau detection (3 consecutive promotions with ΔF1 < 0.01) triggers strategy shift and human escalation |
| Stale compiled graph after promotion | Medium | Medium | Post-promotion stale-graph flag in `_riverbank.sources.metadata`; `recompile_on_promotion` policy (default=off); `riverbank tuning stale-sources` command |
| Measurement miscalibration (alignment table stale) | Medium | High | Pre-diagnosis alignment coverage check; flag when < 50% predicates aligned before running recall-gap rules |
| Human spot-sampling never triggered on non-Wikidata corpora | Low | High | Configurable `spot_sample_every_n_promotions` (default 5); alert fires regardless of whether human responds |
| Interaction effects between parameters cause confounded attribution | Low | Medium | Coordinated mutations require manual approval; interaction pairs documented in §6.3.7; single-mutation default always preserved |
| Mutation conflicts (two experiments touch same parameter) | Low | Low | Max 1 active experiment per parameter type |
| Profile drift makes lineage tree unreadable | Low | Low | Generation depth limit (10); periodic "squash" operation |

---

## 16. Success Criteria

The auto-tuning system is successful when the following criteria are met,
organized by the measurement tier available:

### Tier 1 (Gold — Wikidata corpora)

1. **F1 improves autonomously** — Starting from a baseline profile, 5 tuning
   cycles produce ≥5 percentage points of absolute F1 improvement without human
   intervention (validated on held-out articles not used during A/B testing)
2. **No silent regressions** — Zero cases where a promoted variant later
   regresses on the full benchmark (detected by continuous monitoring within 48h)
3. **Statistical validity** — All promotion decisions are made with SPRT
   log-likelihood ratio ≥ A threshold; no promotions with fewer than 10 paired
   observations
4. **Overfitting guard** — Novel discovery rate stays within 10–30% band after
   5 tuning cycles (the system is not just fitting Wikidata facts)

### Tier 2+3 (Silver/Bronze — arbitrary corpora)

5. **Structural quality improves** — SHACL score + CQ coverage composite
   increases by ≥10% over baseline after 5 tuning cycles
6. **Human spot-sampling** — At least one spot-sampling review completed per
   5 promotions; human accuracy ≥ 0.75 on reviewed triples
7. **Calibration maintained** — Confidence calibration ρ stays ≥ 0.4 throughout
   tuning (the system doesn't inflate confidence to game the composite score)

### Operational

8. **Cost stays bounded** — Total cost (extraction + tuning overhead) grows by
   <15% over 30 days of auto-tuning
9. **Human time saved** — Operator effort for profile maintenance drops >80%
   (from ~2h/week manual tuning to <30min/week reviewing promotion events)
10. **Audit trail is complete** — Every promoted mutation can be explained: what
    triggered it, what it changed, what evidence justified promotion, and which
    measurement tier drove the decision
11. **Learning accumulates** — After 20 experiments, `MutationEffectivenessRegistry`
    predicts outcome better than random (success rate of recommended mutations
    > base rate)

---

## 17. Future Extensions (Out of Scope for v0.16)

| Extension | Description | When |
|-----------|-------------|------|
| **Thompson Sampling for split ratio** | Adaptive exploration rate based on uncertainty about candidate quality — replaces fixed 50/50 split | v1.2 |
| **Active evaluation** | Auto-select which articles to evaluate next using uncertainty sampling on F1 estimate — reduces evaluation cost by 40–60% | v1.2 |
| **Cross-model tuning** | Auto-select between Ollama models based on quality/cost/latency Pareto front | v1.2 |
| **Ensemble extraction with voting** | Route the same fragment to 2-3 profiles, merge outputs via majority vote | v1.3 |
| **Curriculum learning** | Order corpus ingestion from easy → hard articles based on estimated extraction difficulty | v1.4 |
| **RL-based prompt optimization** | Replace OPRO with PPO/DPO over prompt space (requires many more evaluations) | v2.0 |
| **Federated tuning** | Share mutation results across riverbank instances (privacy-preserving) | v2.0 |

---

## 18. References

1. Khattab, O. et al. "DSPy: Compiling Declarative Language Model Calls into
   Self-Improving Pipelines." arXiv:2310.03714 (2023). ICLR 2024.
2. Yang, C. et al. "Large Language Models as Optimizers." arXiv:2309.03409
   (2023). ICLR 2024.
3. Pryzant, R. et al. "Automatic Prompt Optimization with 'Gradient Descent'
   and Beam Search." arXiv:2305.03495 (2023). EMNLP 2023.
4. Opsahl-Ong, K. et al. "Optimizing Instructions and Demonstrations for
   Multi-Stage Language Model Programs." arXiv:2406.11695 (2024). EMNLP 2024.
5. Yuan, W. et al. "Self-Rewarding Language Models." arXiv:2401.10020 (2024).
   ICML 2024.
6. Battle, R. & Gollapudi, T. "The Unreasonable Effectiveness of Eccentric
   Automatic Prompts." arXiv:2402.10949 (2024).
7. Karpathy, A. "LLM Wiki — A Knowledge Base Architecture."
   gist.github.com/karpathy (2025).
8. Talisman, J. "The Ontology Pipeline." jessicatalisman.substack.com (2025).

---

## 19. Summary

riverbank already contains 80% of the machinery needed for auto-tuning:
evaluation scoring, gap analysis, prompt patch generation, few-shot expansion,
and confidence routing. The remaining 20% is orchestration: wiring the existing
components into a closed loop with A/B validation, statistical significance
testing, and safety guardrails.

The proposed design adds **5 new modules** (`DiagnosticsEngine`,
`HypothesisGenerator`, `CandidateRouter`, `SignificanceTester`,
`TuningOrchestrator`) and **2 new database tables** (`tuning_experiments`,
`tuning_cohorts`). It reuses the existing `Scorer`, `RecallGapAnalyzer`,
`PromptTuner`, `FewShotExpander`, and `CompilerProfile` without modification.

The implementation is phased across 8 weeks, with each phase independently
useful:
- Phase A gives operators visibility into what *should* be tuned
- Phase B automates the creative work of proposing improvements
- Phase C adds safe validation before any change goes live
- Phase D makes it fully autonomous
- Phase E makes it observable and auditable

The system respects the compiler analogy: just as `gcc -O2` optimizes code
without changing semantics, `riverbank tuning` optimizes extraction quality
without changing the knowledge contract (competency questions, SHACL shapes,
and schema constraints remain fixed anchors).
