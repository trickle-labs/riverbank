# riverbank — Adaptive Auto-Tuning

> **Date:** 2026-05-08  
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

## 5. The Tuning Loop in Detail

### 5.1 OBSERVE — Metrics Collection

**Trigger:** After every `riverbank ingest` or `riverbank evaluate-wikidata` run.

**Collected signals:**

| Signal | Source | Granularity |
|--------|--------|-------------|
| F1, precision, recall | `Scorer.score_article()` | Per article, per property |
| Confidence calibration | `DatasetEvaluator.aggregate()` | Per confidence bucket |
| Token cost | `_riverbank.runs.cost_usd` | Per fragment |
| SHACL score | `shacl_score()` | Per named graph |
| Rejection rate | `_riverbank.runs.outcome` counts | Per profile |
| Novel discovery rate | `DatasetEvaluator` | Per article |
| Latency | `_riverbank.runs.finished_at - started_at` | Per fragment |
| Triple yield | `triples_written / fragments_processed` | Per run |

**Storage:** Metrics are stored in the existing `_riverbank.runs` table and
aggregated into `_riverbank.tuning_diagnostics` snapshots by the diagnosis
engine.

### 5.2 DIAGNOSE — Gap Identification

**Trigger:** Periodic (every `diagnosis_interval_hours`) or on-demand via
`riverbank diagnose --profile <name>`.

**Algorithm:**

```python
class DiagnosticsEngine:
    """Aggregate metrics and identify improvement opportunities."""
    
    def diagnose(self, profile: CompilerProfile, window_hours: int = 24) -> DiagnosticsReport:
        # 1. Aggregate recent run metrics
        metrics = self._aggregate_metrics(profile, window_hours)
        
        # 2. Compare against historical baseline (rolling 7-day average)
        baseline = self._get_baseline(profile, days=7)
        drift = self._detect_drift(metrics, baseline)
        
        # 3. Run recall-gap analysis on recent evaluation results
        gaps = self._recall_gap_analysis(profile, threshold=0.50)
        
        # 4. Identify FP/FN pattern clusters
        patterns = self._fp_fn_patterns(profile, window_hours)
        
        # 5. Check confidence calibration
        calibration = self._calibration_check(profile)
        
        # 6. Generate ranked recommendations
        recommendations = self._rank_recommendations(
            drift, gaps, patterns, calibration, metrics
        )
        
        return DiagnosticsReport(
            metrics=metrics,
            baseline=baseline,
            drift=drift,
            gaps=gaps,
            patterns=patterns,
            calibration=calibration,
            recommendations=recommendations,
        )
```

**Diagnosis rules (priority-ordered):**

| Priority | Condition | Recommendation |
|----------|-----------|----------------|
| 1 (Critical) | F1 dropped >5% vs. 7-day baseline | Roll back last promotion; freeze tuning |
| 2 (High) | Precision < `min_precision` floor | Tighten confidence thresholds |
| 3 (High) | Property recall = 0 for common P-ids | Add targeted few-shot examples |
| 4 (Medium) | Cost/triple increased >20% vs. baseline | Reduce `safety_cap` or `max_tokens` |
| 5 (Medium) | Confidence miscalibrated (ρ < 0.3) | Adjust routing thresholds |
| 6 (Low) | SHACL score declining | Enable/tighten SHACL validation |
| 7 (Low) | Novel discovery rate > 40% | Review alignment table coverage |

### 5.3 HYPOTHESIZE — Mutation Generation

**Trigger:** When `DiagnosticsReport.recommendations` is non-empty and fewer
than `max_active_candidates` experiments are running.

**Mutation types:**

#### 5.3.1 Prompt Patches (OPRO-style)

Uses the LLM as an optimizer. The hypothesis model receives:
- Current prompt text
- Last 5 evaluation results (F1, per-property breakdown)
- Top FN patterns (what the model missed)
- Top FP patterns (what the model hallucinated)
- A meta-instruction to propose one targeted edit

```python
class PromptMutator:
    """Generate prompt mutations using OPRO-style optimization."""
    
    MUTATION_PROMPT = """
You are optimizing an extraction prompt for a knowledge compiler.

CURRENT PROMPT:
{current_prompt}

RECENT PERFORMANCE (last {n} articles):
- F1: {f1:.3f} | Precision: {precision:.3f} | Recall: {recall:.3f}
- Cost per triple: ${cost_per_triple:.4f}

TOP MISSED EXTRACTIONS (false negatives):
{fn_patterns}

TOP HALLUCINATIONS (false positives):
{fp_patterns}

CONSTRAINT: Propose exactly ONE targeted edit to the prompt that would
address the highest-priority issue. The edit should be minimal — change
as few words as possible while maximizing expected F1 improvement.

Return your edit as a JSON object:
{{
  "section": "system" | "few_shot" | "output_format",
  "action": "add" | "modify" | "remove",
  "original_text": "...",   // null for 'add'
  "new_text": "...",         // null for 'remove'
  "rationale": "...",
  "estimated_f1_lift": 0.0   // percentage points
}}
"""
```

#### 5.3.2 Threshold Sweeps (Grid Search)

Numeric parameters are swept deterministically:

```python
SWEEP_SPACE = {
    "confidence_routing.trusted_threshold": [0.60, 0.65, 0.70, 0.75, 0.80],
    "confidence_routing.tentative_threshold": [0.30, 0.35, 0.40, 0.45, 0.50],
    "extraction_strategy.safety_cap": [50, 75, 100, 150, 200],
    "knowledge_prefix.max_graph_context_tokens": [100, 150, 200, 300, 400],
    "knowledge_prefix.top_entities": [5, 10, 15, 20],
    "few_shot.max_examples": [2, 3, 5, 7],
    "preprocessing.max_entities": [20, 30, 50, 75],
}
```

The sweep selects the **adjacent** value to the current setting (one step up
or down) based on the diagnosis:
- If recall is low → lower `trusted_threshold`
- If precision is low → raise `trusted_threshold`
- If cost is high → lower `safety_cap`
- If entity consistency is poor → increase `knowledge_prefix.top_entities`

#### 5.3.3 Few-Shot Mutations

Extends the existing `FewShotExpander` with evaluation-driven selection:

```python
class EvalDrivenFewShotMutator:
    """Select few-shot examples targeting specific recall gaps."""
    
    def mutate(self, profile, gaps: list[PropertyRecallGap]) -> ProfileMutation:
        # For each gap with recall < 0.25, inject a targeted example
        # from RecallGapAnalyzer._BUILTIN_EXAMPLES
        new_examples = []
        for gap in sorted(gaps, key=lambda g: g.recall)[:3]:
            examples = self.recall_gap_analyzer.get_examples(gap.property_id)
            if examples:
                new_examples.append(examples[0])
        
        return ProfileMutation(
            mutation_type="few_shot_expansion",
            mutation_yaml=self._format_examples_yaml(new_examples),
            rationale=f"Targeting {len(new_examples)} properties with recall < 0.25",
        )
```

#### 5.3.4 Knowledge-Prefix Tuning

Adjusts `max_graph_context_tokens` and `top_entities` based on entity
consistency metrics:

- If entity IRI fragmentation is high (many IRIs for the same real-world
  entity) → increase `top_entities` and `max_graph_context_tokens`
- If token budget is tight (truncation observed) → decrease context size

#### 5.3.5 Preprocessing Strategy Mutations

- Toggle `preprocessing.backend` between `"nlp"` and `"llm"` when NLP backend
  produces poor entity catalogs (measured by entity recall in extraction)
- Adjust `preprocessing.max_entities` based on prompt truncation rate
- Enable/disable `corpus_preprocessing` based on corpus size

### 5.4 VALIDATE — A/B Testing

**Cohort assignment:**

When an experiment is active, the `CandidateRouter` assigns new sources:

```python
class CandidateRouter:
    """Deterministic cohort assignment for A/B testing."""
    
    def assign(self, source_iri: str, experiment: TuningExperiment) -> str:
        """Assign a source to 'baseline' or 'candidate' cohort.
        
        Uses consistent hashing so the same source always lands in the
        same cohort within an experiment (idempotent re-ingest).
        """
        h = xxhash.xxh64(f"{experiment.id}:{source_iri}").intdigest()
        if (h % 100) < (experiment.split_ratio * 100):
            return "candidate"
        return "baseline"
```

**Evaluation:**

Both cohorts are scored using the same `Scorer` against Wikidata ground truth.
The comparison uses **paired evaluation** — the same article is always scored
in both cohorts, eliminating variance from article difficulty.

**Statistical significance:**

```python
class SignificanceTester:
    """Welch's t-test for A/B comparison with early stopping."""
    
    def test(self, experiment: TuningExperiment) -> SignificanceResult:
        baseline_scores = self._get_cohort_scores(experiment, "baseline")
        candidate_scores = self._get_cohort_scores(experiment, "candidate")
        
        if len(candidate_scores) < experiment.min_sample_size:
            return SignificanceResult(ready=False, reason="insufficient samples")
        
        # Welch's t-test (unequal variance)
        t_stat, p_value = scipy.stats.ttest_ind(
            candidate_scores, baseline_scores, equal_var=False
        )
        
        # Effect size (Cohen's d)
        effect_size = (
            np.mean(candidate_scores) - np.mean(baseline_scores)
        ) / np.sqrt(
            (np.var(candidate_scores) + np.var(baseline_scores)) / 2
        )
        
        return SignificanceResult(
            ready=True,
            p_value=p_value,
            effect_size=effect_size,
            candidate_mean=np.mean(candidate_scores),
            baseline_mean=np.mean(baseline_scores),
            should_promote=(
                p_value < 0.05
                and effect_size > 0
                and (np.mean(candidate_scores) - np.mean(baseline_scores))
                    >= experiment.promotion_f1_delta
            ),
            should_demote=(
                p_value < 0.05
                and effect_size < 0
                and (np.mean(baseline_scores) - np.mean(candidate_scores))
                    >= abs(experiment.demotion_f1_delta)
            ),
        )
```

**Early stopping:** If after `min_sample_size` articles the candidate is
clearly worse (p < 0.01 and effect negative), demote immediately without
waiting for `max_experiment_days`.

### 5.5 PROMOTE / DEMOTE — Profile Lifecycle

**Promotion:**
1. Candidate profile becomes the new active profile
2. Parent profile is archived (retained for `rollback_retention_days`)
3. `_riverbank.tuning_experiments.status` → `'promoted'`
4. Audit log entry: `operation='tuning_promotion'`
5. pg-tide event: `riverbank.tuning.promoted` (downstream alerting)
6. Prometheus counter: `riverbank_tuning_promotions_total`

**Demotion:**
1. Candidate profile is deactivated
2. `_riverbank.tuning_experiments.status` → `'demoted'`
3. Audit log entry: `operation='tuning_demotion'`
4. If the demotion was for a *regression* on an already-promoted variant,
   automatic rollback to the parent profile

**Expiry:**
1. If `max_experiment_days` elapsed without reaching significance
2. `_riverbank.tuning_experiments.status` → `'expired'`
3. Candidate profile deleted (insufficient evidence either way)

---

## 6. Mutation Lineage and Audit Trail

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

## 7. Safety Mechanisms

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

## 8. Integration with Existing Systems

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

## 9. CLI Commands

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

## 10. Worked Example

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

## 11. Comparison with Related Work

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

## 12. Implementation Plan

### Phase A: Instrumentation & Diagnostics (2 weeks)

**Goal:** Close the observability gap — make all tuning-relevant metrics
queryable and trendable.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Add `_riverbank.tuning_diagnostics` table + Alembic migration | 2h | — |
| Implement `DiagnosticsEngine` with 7 diagnosis rules | 3d | Scorer, RecallGapAnalyzer |
| `riverbank tuning diagnose` CLI command | 4h | DiagnosticsEngine |
| Add `riverbank_tuning_f1_current` and `cost_per_triple` Prometheus gauges | 2h | metrics module |
| Aggregate per-run metrics into sliding-window snapshots (SQL view) | 4h | existing runs table |
| Unit tests for diagnosis rules | 1d | — |

**Acceptance:** `riverbank tuning diagnose --profile X` produces a JSON report
with gaps, patterns, and ranked recommendations.

### Phase B: Hypothesis Generation (2 weeks)

**Goal:** Automatically generate profile mutations from diagnostic reports.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Define `ProfileMutation` dataclass and `MutationRegistry` | 4h | — |
| Implement `PromptMutatorBackend` (OPRO-style LLM optimizer) | 2d | DiagnosticsEngine |
| Implement `ThresholdSweepBackend` (grid + adjacent-step) | 1d | — |
| Implement `EvalDrivenFewShotMutator` (recall-gap → examples) | 1d | RecallGapAnalyzer |
| Implement `KnowledgePrefixTuner` (token budget optimization) | 4h | KnowledgePrefixAdapter |
| Wire backends into `HypothesisGenerator` with priority selection | 1d | all backends |
| `riverbank tuning propose` CLI command | 4h | HypothesisGenerator |
| Unit tests for each mutation backend | 2d | — |

**Acceptance:** `riverbank tuning propose --profile X` produces a valid
candidate profile YAML with documented rationale.

### Phase C: A/B Testing Harness (2 weeks)

**Goal:** Route traffic to candidate profiles and compare outcomes.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Add `_riverbank.tuning_experiments` and `tuning_cohorts` tables | 4h | — |
| Implement `CandidateRouter` with consistent hashing | 1d | — |
| Modify `pipeline.ingest()` to check for active experiments and route | 1d | CandidateRouter |
| Implement `SignificanceTester` (Welch's t-test + early stopping) | 1d | scipy |
| Implement promotion/demotion logic with audit trail | 1d | — |
| `riverbank tuning experiments` CLI (list, approve, reject) | 1d | — |
| pg-tide event emission on promotion/demotion | 4h | pg-tide integration |
| Integration tests: full cycle (propose → route → score → promote) | 2d | all above |

**Acceptance:** A synthetic experiment with a clearly-better candidate is
automatically promoted after `min_sample_size` evaluations.

### Phase D: Orchestration & Scheduling (1 week)

**Goal:** Wire the full loop to run autonomously.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Implement `TuningOrchestrator` (diagnose → hypothesize → validate → promote) | 1d | Phases A–C |
| Implement `TuningScheduler` (APScheduler periodic trigger) | 4h | TuningOrchestrator |
| Add `auto_tuning:` section to profile YAML schema | 4h | CompilerProfile |
| `riverbank tuning run-once` CLI command | 2h | TuningOrchestrator |
| Safety guardrails: freeze on regression, generation depth limit | 1d | — |
| End-to-end integration test with Wikidata benchmark subset | 2d | all above |

**Acceptance:** `riverbank tuning run-once` executes the full loop and either
promotes, demotes, or logs "no improvement found".

### Phase E: Observability & Polish (1 week)

**Goal:** Dashboards, lineage visualization, and operator experience.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Prometheus metrics for all tuning events | 4h | Phase D |
| Perses dashboard panel: tuning experiments, F1 trend, cost trend | 1d | Prometheus |
| `riverbank tuning history` CLI (tree visualization) | 1d | MutationRegistry |
| `riverbank tuning pareto` CLI (quality×cost frontier) | 4h | — |
| Langfuse dataset integration (experiment results as datasets) | 1d | Langfuse |
| `riverbank tuning rollback` and `freeze`/`unfreeze` commands | 1d | — |
| Documentation: how-to guide, concepts page | 1d | — |
| Update ROADMAP.md | 1h | — |

**Acceptance:** Operators can visualize the tuning history, understand why each
promotion happened, and intervene at any point.

---

## 13. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Auto-tuning degrades quality silently | Medium | High | Precision floor guardrail + freeze on regression + 7-day rollback window |
| LLM-generated mutations are nonsensical | Medium | Low | Syntax validation + bounded impact (one mutation per cycle) + A/B testing catches bad mutations |
| Cost explosion from hypothesis generation | Low | Medium | Hypothesis model is cheap (gpt-4o-mini); cap at 1 hypothesis/day |
| Overfitting to Wikidata benchmark | Medium | Medium | Track novel discovery rate; periodically add new benchmark articles; separate validation set |
| Statistical noise in small corpora | High | Medium | Minimum sample size (30); expire inconclusive experiments after 14 days |
| Mutation conflicts (two experiments touch same parameter) | Low | Low | Max 1 active experiment per parameter type |
| Profile drift makes lineage tree unreadable | Low | Low | Generation depth limit (10); periodic "squash" operation |

---

## 14. Success Criteria

The auto-tuning system is successful when:

1. **F1 improves autonomously** — Starting from a baseline profile, 5 tuning
   cycles should produce ≥5 percentage points of F1 improvement without human
   intervention (validated on held-out articles)
2. **Cost stays bounded** — Total cost (extraction + tuning overhead) grows by
   <15% over 30 days of auto-tuning
3. **No silent regressions** — Zero cases where a promoted variant is later
   found to have regressed on the full benchmark (detected within 48h)
4. **Human time saved** — Operator effort for profile maintenance drops by >80%
   (from ~2h/week manual tuning to <30min/week review of promotion events)
5. **Audit trail is complete** — Every promoted mutation can be explained: what
   triggered it, what it changed, what evidence justified promotion

---

## 15. Future Extensions (Out of Scope for v0.16)

| Extension | Description | When |
|-----------|-------------|------|
| **Thompson Sampling for split ratio** | Adaptive exploration rate based on uncertainty about candidate quality | v1.2 |
| **Cross-model tuning** | Auto-select between Ollama models based on quality/cost/latency Pareto | v1.2 |
| **Transfer learning across profiles** | Mutations that worked for one domain (biography) transferred to another (organization) | v1.3 |
| **Ensemble extraction with voting** | Route the same fragment to 2-3 profiles, merge outputs via majority vote | v1.3 |
| **Curriculum learning** | Order corpus ingestion from easy → hard articles based on estimated extraction difficulty | v1.4 |
| **Active evaluation** | Auto-select which articles to evaluate next (uncertainty sampling on F1 estimate) | v1.4 |
| **RL-based prompt optimization** | Replace OPRO with PPO/DPO over prompt space (requires many more evaluations) | v2.0 |
| **Federated tuning** | Share mutation results across riverbank instances (privacy-preserving) | v2.0 |

---

## 16. References

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

## 17. Summary

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
