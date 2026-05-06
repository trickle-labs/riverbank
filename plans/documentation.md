# riverbank — Documentation Plan

> **Date:** 2026-05-06
> **Status:** Plan — targets v0.10.0
> **Owner:** trickle-labs
> **Toolchain:** MkDocs Material · GitHub Pages · GitHub Actions

---

## 1. Vision

The goal is a documentation site that treats first-time readers as peers, not
students. A developer who arrives from a blog post about knowledge compilers
should be able to understand what riverbank does, run it against their own
corpus, and trust the compiled output — all within a single afternoon. An
operator deploying it to Kubernetes should be able to find every configuration
knob, SLO reference, and runbook entry without opening source code. A
researcher evaluating the epistemic model should be able to follow the `pgc:`
ontology from concept to SPARQL example without leaving the site.

These are three different readers with three different goals. Great
documentation acknowledges that distinction at every level: in the navigation
structure, in the writing register, and in the way examples scale from "try it
in five minutes" to "tune it for production." The documentation site is itself
a product. It deserves the same design attention as the compiler it describes.

---

## 2. Audience profiles

Understanding exactly who reads the docs — and what they already know — prevents
the most common documentation failure: writing for the person who built the
system rather than the person who needs to use it.

**The practitioner** is a senior engineer or ML engineer who has already heard
of knowledge graphs, is comfortable with SQL and Python, and wants to compile
their company's internal documentation corpus or product wiki. They arrive with
a concrete corpus in mind. They do not need a lecture on why RDF is better than
a search index; they need to see a real ingestion run, understand how the
compiler profile controls extraction, and know what queries to run against the
result. Tutorials, how-to guides, and the compiler profile reference are the
sections they will use most.

**The operator** is a platform engineer or SRE who has been asked to deploy
riverbank at scale. They care about the Helm chart, Prometheus metrics,
advisory-lock semantics, circuit breaker configuration, secret management, and
the Alembic migration story. They will go straight to the Operations section and
never read the conceptual material unless something breaks. Their documentation
must be complete, precise, and unambiguous — a missing default value or an
undocumented environment variable is a production incident waiting to happen.

**The evaluator** is a technical decision-maker — an architect, a researcher, or
a team lead — assessing whether riverbank is the right foundation for a project.
They want to understand the design philosophy, the epistemic model, the
dependency story, and the limits of the system. The Concepts section, the
architecture diagrams, and the comparison with alternative approaches are what
they read first. This audience will not tolerate vague claims; every assertion
about quality, provenance, or incremental correctness must be backed by a
concrete example or a reference to a test case.

---

## 3. Principles

**Principle 1 — Show before you tell.** Every concept section ends with a
working example. Every reference page opens with the simplest possible usage.
Readers should never encounter prose explanation without a concrete anchor to
hold it against. The golden rule: if you cannot show a reader what it looks like
in two lines of code or a ten-line SPARQL query, the explanation is probably too
abstract.

**Principle 2 — One idea per page.** Each page answers one question completely,
then stops. A page titled "Compiler profiles" explains what a compiler profile
is, how to write one, and how to register it. It does not also explain
embeddings or the ingest gate. Navigation should feel like a map, not a maze.

**Principle 3 — Honest about limits.** The documentation explicitly states what
riverbank does not do: it is not a workflow editor, not a connector marketplace,
not a custom UI. Readers who discover a missing feature through the docs rather
than a production failure are better served — and more likely to contribute.

**Principle 4 — Living documentation.** The auto-generated knowledge pages
produced by `riverbank render` are part of the published site. This creates a
feedback loop: improving the compiled knowledge graph directly improves the
documentation. The handwritten reference docs and the compiled knowledge pages
are built together in one MkDocs run and live side by side.

**Principle 5 — Test the examples.** Code blocks in the documentation are
validated against the golden corpus in CI. A README example that does not work
is a lie. The CI workflow that publishes the docs site also runs the code
samples; a broken example blocks the publish step.

---

## 4. Toolchain

### 4.1 MkDocs Material

The primary site generator is [MkDocs Material](https://squidfunk.github.io/mkdocs-material/).
It is a natural fit for a Python project — installed with `pip install
mkdocs-material` alongside the rest of the dev dependencies, no separate build
toolchain required. The Material theme provides full-text search out of the box,
versioned docs support via `mike`, light and dark mode, and admonitions
(`!!! note`, `!!! warning`) that make reference pages easy to scan. The config
lives in `mkdocs.yml` at the repo root.

Additional plugins used:

| Plugin | Purpose |
|---|---|
| `mkdocstrings[python]` | Auto-generates API reference pages from Python docstrings |
| `mkdocs-gen-files` | Generates the `docs/reference/api/` subtree at build time |
| `mkdocs-literate-nav` | Reads navigation from `docs/SUMMARY.md` instead of duplicating it in `mkdocs.yml` |
| `mkdocs-section-index` | Makes section landing pages clickable in the nav tree |
| `pymdownx.superfences` | Syntax-highlighted code blocks with tabs and line numbers |
| `pymdownx.tabbed` | Side-by-side code examples for different LLM providers or output formats |

### 4.2 GitHub Pages via GitHub Actions

A GitHub Actions workflow (`docs.yml`) publishes the site on every push to
`main` and on every version tag. The workflow installs the `[docs]` extras,
runs `mkdocs build --strict` (failing on warnings), and deploys with `mike
deploy --push --update-aliases <version> latest`. This gives the site both a
stable `latest` URL and versioned snapshots at `/<version>/` so that operators
pinned to a particular release can always find the documentation that matches
their deployment.

### 4.3 Local development

Running `mkdocs serve` from the repo root starts a live-reload server on
`http://localhost:8000`. Writers can edit Markdown files and see changes
instantly without a build step. The `[docs]` extras group in `pyproject.toml`
installs everything needed: `pip install -e ".[docs]"`.

---

## 5. Site structure

The top-level navigation follows the [Diátaxis framework](https://diataxis.fr/):
tutorials for learning, how-to guides for problem solving, reference for
information lookup, and explanation for understanding. This is not a philosophical
choice — it is a practical one. Readers arrive with different needs, and
structuring navigation around those needs rather than around the source tree
prevents the most common documentation pathology: a single enormous "guide" that
tries to be everything and succeeds at nothing.

```
docs/
├── SUMMARY.md                    ← mkdocs-literate-nav navigation source
├── index.md                      ← Home page
│
├── getting-started/
│   ├── index.md                  ← "What is riverbank?" — 5-minute overview
│   ├── quickstart.md             ← docker compose up → first compiled query
│   ├── installation.md           ← pip install, uv, Docker, Kubernetes
│   └── first-corpus.md           ← ingest examples/markdown-corpus/, run a query
│
├── tutorials/
│   ├── index.md
│   ├── compile-a-policy-corpus.md
│   ├── compile-a-runbook-corpus.md     ← procedural-v1 profile
│   ├── multi-tenant-setup.md
│   └── render-a-mkdocs-site.md         ← riverbank render → GitHub Pages
│
├── how-to/
│   ├── index.md
│   ├── write-a-compiler-profile.md
│   ├── add-a-custom-extractor.md
│   ├── add-a-custom-parser.md
│   ├── connect-a-new-source.md
│   ├── configure-label-studio.md
│   ├── run-incremental-recompile.md
│   ├── explain-a-compiled-artifact.md
│   ├── explain-a-conflict.md
│   ├── manage-tenants.md
│   ├── deploy-on-kubernetes.md
│   ├── rotate-secrets.md
│   ├── bulk-reprocess-a-profile.md
│   └── generate-an-sbom.md
│
├── concepts/
│   ├── index.md
│   ├── the-compiler-analogy.md
│   ├── pipeline-stages.md
│   ├── compiler-profiles.md
│   ├── fragment-and-artifact-model.md
│   ├── incremental-compilation.md
│   ├── epistemic-model.md               ← all 9 statuses, negative knowledge
│   ├── provenance-model.md              ← PROV-O, citation grounding
│   ├── quality-gates.md                 ← SHACL, ingest gate, shacl_score()
│   ├── multi-tenancy.md
│   ├── federation.md
│   └── rendering.md
│
├── reference/
│   ├── index.md
│   ├── cli.md                           ← every subcommand, flag, exit code
│   ├── configuration.md                 ← all RIVERBANK_* env vars + TOML keys
│   ├── compiler-profile-schema.md       ← full YAML schema with every field
│   ├── ontology.md                      ← pgc: vocabulary, all classes + properties
│   ├── sparql-helpers.md                ← rag_context(), rag_retrieve(), etc.
│   ├── plugin-api.md                    ← entry point groups, base classes
│   ├── api/                             ← auto-generated from docstrings
│   │   └── (generated by mkdocstrings)
│   ├── metrics.md                       ← all Prometheus metric names + labels
│   ├── error-codes.md
│   └── changelog.md
│
├── operations/
│   ├── index.md
│   ├── helm-chart.md
│   ├── multi-replica-workers.md
│   ├── advisory-locks.md
│   ├── circuit-breakers.md
│   ├── audit-trail.md
│   ├── backup-and-restore.md
│   ├── secret-management.md
│   ├── observability.md                 ← OTel, Langfuse, Prometheus, Perses
│   ├── scaling.md
│   └── upgrading.md
│
├── contributing/
│   ├── index.md
│   ├── development-setup.md
│   ├── running-tests.md
│   ├── writing-a-plugin.md
│   └── release-process.md
│
└── knowledge/                           ← auto-generated by riverbank render
    └── (generated at build time)
```

---

## 6. Page-by-page content plan

### 6.1 Home page (`index.md`)

The home page has one job: answer "what is this and why should I care?" in under
sixty seconds of reading time. It opens with a one-paragraph description of the
core idea — that documents are bad runtime formats, and riverbank compiles them
into something better. It then shows the three-command path from zero to a
working query against a compiled corpus, so readers can calibrate the barrier
to entry immediately. Below the quick-start snippet, it links out to the four
top-level sections with a one-sentence description of who each section is for.
It does not try to describe every feature — that is the job of the reference.

### 6.2 Getting started

**`quickstart.md`** is the most important page on the site. It must work. Every
command must be tested. The path is: clone the repo, `docker compose up -d`,
`riverbank init`, `riverbank ingest examples/markdown-corpus/`, `riverbank query
"SELECT ?s ?p ?o WHERE { ?s ?p ?o }"`. The page ends with "you have compiled
your first knowledge graph" and links to the tutorials for what to do next. It
avoids explaining every flag — that belongs in the reference.

**`first-corpus.md`** walks through what actually happened during that ingest
run: what the markdown parser did, how the heading fragmenter split the corpus,
what the ingest gate checked, what the extractor produced, and how to inspect
the result with `riverbank runs` and `riverbank query`. This is the page that
bridges quick-start enthusiasm to genuine understanding.

### 6.3 Tutorials

Tutorials follow a strict format: a realistic scenario, a complete walkthrough
that produces a working result, and a summary of what was learned. They are
never reference material — they do not list every option. They show one path
through the system that a real user might take.

**`compile-a-policy-corpus.md`** uses the `docs-policy-v1` profile from
`examples/profiles/` and the `examples/markdown-corpus/` corpus. It shows
competency-question-driven profile design: start with the questions the compiled
graph must answer, then work backward to the extraction rules that produce the
facts needed to answer them. The finished graph passes the golden corpus CI gate
— readers can verify by running `pytest tests/golden/`.

**`compile-a-runbook-corpus.md`** uses the `procedural-v1` profile to compile
a set of incident-response runbooks. It demonstrates the step-sequence
extraction (`pko:nextStep`, `pko:previousStep`, `pko:nextAlternativeStep`),
shows how to query "what is the rollback path for step X", and explains why
this kind of structured knowledge is more reliable for AI-assisted incident
response than a plain search index over the same docs.

**`render-a-mkdocs-site.md`** shows the full `riverbank render --format markdown
--target docs/knowledge/` flow, the resulting MkDocs nav entries, and how to
wire GitHub Actions to publish the rendered site on every commit to main. This
tutorial is self-referential: the reader is, in effect, building the same
pipeline that generates part of the riverbank documentation site itself.

### 6.4 How-to guides

How-to guides are task-oriented and assume the reader already understands the
concepts. They answer "how do I do X?" and stop when X is done.

**`write-a-compiler-profile.md`** is one of the most important how-to guides
because the compiler profile is the primary configuration surface for end users.
It covers every YAML field with brief explanations, shows three progressively
complex profiles (docs-policy-v1, procedural-v1, and a custom multi-model
ensemble profile), and explains how competency questions drive profile evolution.
It links to the full compiler profile schema reference for exhaustive field
documentation.

**`add-a-custom-extractor.md`** explains the `riverbank.extractors` entry point,
the `BaseExtractor` base class, and the `EvidenceSpan` type contract. It shows
a minimal extractor in thirty lines of Python and the `pyproject.toml` entry
point declaration. Readers should leave this page able to ship a first-party
extractor in a day.

**`explain-a-conflict.md`** walks through the `riverbank explain-conflict <iri>`
command against a corpus that contains a real contradiction. It explains what
`pg_ripple.explain_contradiction()` computes (a minimal hitting set over the
inference dependency graph), why that is more useful than a raw SPARQL query for
contradiction detection, and how to use the output to resolve the conflict —
either by correcting a source document or by annotating one of the conflicting
facts with a `pgc:NegativeKnowledge` record.

**`manage-tenants.md`** covers the full tenant lifecycle: `riverbank tenant
create`, per-tenant profiles and named graphs, the GDPR erasure path
(`riverbank tenant delete --erase`), and the RLS verification query that
confirms no cross-tenant data leakage. This page is especially important for
operators deploying shared infrastructure, and it should be explicit about what
RLS does and does not protect against.

### 6.5 Concepts

The concepts section is the intellectual heart of the documentation. It is where
readers who want to understand the system — not just operate it — will spend
most of their time.

**`the-compiler-analogy.md`** explains the Karpathy compiler framing that
underpins riverbank's design. Raw documents are source code. The compiler
(riverbank) transforms them into a compiled artifact (the knowledge graph). At
query time you interrogate the compiled artifact, not the raw source. The page
should be engaging and persuasive — this is the core idea that differentiates
riverbank from a generic RAG pipeline — but it should also be honest about where
the analogy breaks down and what problems it does not solve.

**`epistemic-model.md`** is the most technically dense concept page. It explains
all nine `pgc:epistemicStatus` values (`observed`, `extracted`, `inferred`,
`verified`, `deprecated`, `normative`, `predicted`, `disputed`, `speculative`),
how each is assigned, how they flow through the inference pipeline, and how they
surface in `rag_context()` output. It also covers `pgc:NegativeKnowledge` (why
recording explicit absences is as important as recording facts), argument graphs
(`pgc:ArgumentRecord` with claim, evidence, objection, and rebuttal), and the
assumption registry. This page will be read by the evaluators who need to
understand whether riverbank's epistemic commitments match their use case.

**`incremental-compilation.md`** explains the artifact dependency graph recorded
in `_riverbank.artifact_deps`, the hash-based fragment skip logic, the
recompile flow triggered by a changed source, and the semantic diff event
emitted via pg-trickle. Diagrams are essential here — a sequence diagram
showing what happens when one paragraph in one document changes, with exactly
which nodes in the dependency graph are invalidated, will do more work than five
paragraphs of prose.

**`provenance-model.md`** covers the PROV-O provenance chain from source
document to fragment to extraction run to triple, including the `prov:wasDerivedFrom`
edge that carries character-range evidence and the verbatim excerpt. It explains
why fabricated citations are rejected at the type-system level (`EvidenceSpan`
requires an exact character offset, and the validator confirms the offset
resolves to the claimed text), and how GDPR erasure works: erasing a source
cascades via the provenance graph to all derived facts.

### 6.6 Reference

The reference section is not prose — it is a structured lookup surface. Every
entry follows the same template: name, type, default, description, example. No
waffle.

**`cli.md`** documents every subcommand (`init`, `health`, `ingest`, `query`,
`runs`, `lint`, `explain`, `explain-conflict`, `render`, `recompile`, `profile`,
`source`, `tenant`, `sbom`), every flag, and every exit code. It is generated
from Click's `--help` output via a MkDocs build script so it can never drift
from the implementation. Where the generated output is insufficient, a
human-written "notes" block below the generated section adds context.

**`configuration.md`** lists every `RIVERBANK_*` environment variable and every
TOML key, with the type, default value, which release introduced it, and a brief
description. Settings that affect security or data integrity are called out
explicitly with `!!! warning` admonitions.

**`compiler-profile-schema.md`** documents the full YAML schema for compiler
profiles — every field, its type, whether it is required or optional, the
default, and an example. A `docs-policy-v1` annotated listing at the top of the
page gives readers a complete real-world profile to reference while reading the
field-by-field breakdown below.

**`ontology.md`** documents the `pgc:` SPARQL vocabulary: every class
(`pgc:Fragment`, `pgc:Run`, `pgc:NegativeKnowledge`, `pgc:ArgumentRecord`,
`pgc:CoverageMap`, `pgc:RenderedPage`, `pgc:LintFinding`, …), every property
(`pgc:fromFragment`, `pgc:epistemicStatus`, `pgc:confidence`, `pgc:tenantId`,
…), and every named individual (the nine epistemic status values). Each entry
links to the concept page that explains it and to an example SPARQL query that
uses it. The source of truth is the Turtle file at `ontology/pgc.ttl`, and the
reference page is generated from it at build time.

**`metrics.md`** documents every Prometheus metric emitted by the `/metrics`
endpoint: `riverbank_runs_total`, `riverbank_run_duration_seconds`,
`riverbank_llm_cost_usd_total`, `riverbank_shacl_score`,
`riverbank_review_queue_depth`, `riverbank_context_efficiency_ratio`. For each
metric: the name, type (counter/gauge/histogram), label dimensions, and a
note on what to alert on.

### 6.7 Operations

The operations section is written for the operator profile and assumes fluency
with Kubernetes, Prometheus, and PostgreSQL. It does not re-explain what
advisory locks are — it explains what riverbank's use of advisory locks means
in practice for operators: which lock key is used, what happens when a worker
crashes while holding a lock, and how to diagnose and clear stuck locks without
data loss.

**`helm-chart.md`** covers the `values.yaml` reference for the riverbank Helm
chart, the dependency on the pg_ripple chart, the upgrade path between minor
versions, and the rollback procedure. It includes a worked example of a
production `values.yaml` with replicas, resource limits, secret references, and
Prometheus scrape annotations.

**`observability.md`** connects the three observability layers: Langfuse for
LLM call traces (with deep-links from `riverbank runs`), OpenTelemetry for
pipeline spans, and Prometheus/Perses for aggregate metrics. It shows a typical
alert rule for review queue depth, a Perses dashboard screenshot, and the Jaeger
trace for a single fragment compilation from source read to triple write.

**`upgrading.md`** documents the Alembic migration story: how to check the
current schema version, how to run migrations, and what the rollback path is for
each migration. It lists every migration that added a column or index and calls
out any that required a table lock, with the expected lock duration at various
corpus sizes.

### 6.8 Contributing

**`writing-a-plugin.md`** is the community-facing version of the how-to guide
for custom extractors and parsers, but broader: it covers all five entry-point
groups (`parsers`, `fragmenters`, `extractors`, `connectors`, `reviewers`),
explains the base class contracts, shows how to write tests using the existing
`conftest.py` fixtures, and describes the review process for a plugin that
targets inclusion in the core package.

---

## 7. Writing guidelines

### Register

The writing register is friendly and direct, not academic. Contractions are
fine. "You" is preferred over "the user" or "one". Sentences should be short
enough to parse in one pass. Technical terms are used precisely and defined on
first use; after that, they are used without apology. The goal is a site that
a reader can use at speed — skimming to find the relevant section, then reading
that section fully — without encountering ambiguity that requires a second read.

### Length

Concept pages may be long — the epistemic model is genuinely complex and
deserves thorough treatment. How-to guides should be as short as possible: if a
task can be completed with four commands, the how-to guide should have four
commands and brief commentary, not four commands buried under four paragraphs
of preamble. Reference pages have no length target — they are complete or they
are not.

### Diagrams

Diagrams are produced in Mermaid (rendered natively by MkDocs Material) for
flowcharts and sequence diagrams, and in plain ASCII art embedded in code blocks
for architecture diagrams that need to appear in both the docs site and plain
Markdown renderers (GitHub, terminal). Every diagram has a caption and alt text.

### Admonitions

`!!! note` — additional context that is useful but not on the critical path.
`!!! tip` — a shortcut or non-obvious best practice.
`!!! warning` — a behaviour that can cause data loss, cost overruns, or security
issues if misunderstood.
`!!! danger` — actions that are irreversible or destructive (GDPR erasure,
`riverbank tenant delete`, dropping catalog tables).

### Code examples

Every code example specifies its language for syntax highlighting. Shell examples
show the prompt (`$`) for commands run as the user and no prompt for commands
that are part of a script or compose file. SPARQL examples use the `sparql`
language tag. YAML examples use the `yaml` tag. Python examples use `python`.
Long output is truncated with `# ... (truncated)` rather than shown in full.

---

## 8. Auto-generated knowledge pages

The `docs/knowledge/` subtree is populated at build time by running:

```bash
riverbank render --format markdown --target docs/knowledge/ --corpus examples/markdown-corpus/
```

This produces one Markdown page per compiled entity and one survey page per
topic cluster, each with a citations section linking back to the source
fragments. The MkDocs build picks them up automatically via `mkdocs-gen-files`.

The knowledge pages serve a dual purpose: they demonstrate the `riverbank render`
capability to readers who have not yet tried it, and they validate that the
feature works correctly — a broken render would fail the CI build and block the
site publish.

For the initial v0.10.0 launch, the knowledge corpus is limited to the
`examples/markdown-corpus/` (riverbank's own concept introductions). Later
releases can expand this to the full pg_ripple documentation corpus, producing
a cross-linked site that covers the entire stack.

---

## 9. CI workflow

```yaml
# .github/workflows/docs.yml (simplified)
name: docs
on:
  push:
    branches: [main]
    tags: ["v*"]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[docs]"
      - run: riverbank render --format markdown --target docs/knowledge/
        env:
          RIVERBANK_DB_DSN: ${{ secrets.DOCS_DB_DSN }}
      - run: mkdocs build --strict
      - run: mike deploy --push --update-aliases ${{ github.ref_name }} latest
        if: startsWith(github.ref, 'refs/tags/')
      - run: mkdocs gh-deploy --force
        if: github.ref == 'refs/heads/main'
```

The `--strict` flag causes the build to fail on any broken internal link, any
undefined reference in a docstring page, or any Mermaid diagram that fails to
parse. This is the quality gate that keeps the docs honest.

---

## 10. `pyproject.toml` extras

```toml
[project.optional-dependencies]
docs = [
    "mkdocs-material>=9.5",
    "mkdocstrings[python]>=0.25",
    "mkdocs-gen-files>=0.5",
    "mkdocs-literate-nav>=0.6",
    "mkdocs-section-index>=0.3",
    "mike>=2.1",
]
```

The `[docs]` extras are separate from `[dev]` so that CI jobs that only need to
build the docs do not install pytest, mypy, and testcontainers, and vice versa.

---

## 11. `mkdocs.yml` skeleton

```yaml
site_name: riverbank
site_description: A knowledge compiler for PostgreSQL
site_url: https://trickle-labs.github.io/riverbank/
repo_url: https://github.com/trickle-labs/riverbank
repo_name: trickle-labs/riverbank
edit_uri: edit/main/docs/

theme:
  name: material
  palette:
    - scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.code.annotate

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [src]
  - gen-files:
      scripts:
        - docs/gen_ref_pages.py
  - literate-nav:
      nav_file: SUMMARY.md
  - section-index
  - mike:
      version_selector: true

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.inlinehilite
  - attr_list
  - md_in_html
  - tables
  - toc:
      permalink: true
```

---

## 12. Phased delivery

Documentation work is delivered in two phases within v0.10.0 to keep the pull
request size manageable and to allow the tooling to be validated before the full
content is written.

**Phase 1 — Skeleton and tooling** (first PR):
- `mkdocs.yml`, `pyproject.toml [docs]`, `docs/` directory structure
- Home page, quick-start, and installation pages
- CLI reference (auto-generated)
- Configuration reference (complete)
- GitHub Actions workflow
- Validated CI build with `--strict`

**Phase 2 — Content** (subsequent PRs per section):
- Concepts section (compiler analogy, epistemic model, provenance, incremental compilation)
- Tutorials (policy corpus, runbook corpus, render to MkDocs)
- How-to guides (compiler profiles, custom extractor, tenant management, conflict explanation)
- Operations section (Helm chart, observability, upgrading)
- Ontology and metrics reference
- Auto-generated knowledge pages from `examples/markdown-corpus/`

Each Phase 2 PR covers one top-level section so that reviewers can focus on
content quality without being overwhelmed by scope. The CI build gate applies
from Phase 1 onward — no broken links, no undefined references, no untested
code samples are merged.

---

## 13. Success criteria

The documentation is complete when:

1. A developer with no prior knowledge of riverbank can follow `quickstart.md`
   and produce a working SPARQL query against a compiled corpus without
   consulting any other resource.
2. An operator can configure, deploy, and monitor a multi-replica Kubernetes
   deployment using only the Operations section and the Helm chart reference.
3. Every `pgc:` class and property documented in `ontology/pgc.ttl` has a
   corresponding entry in `reference/ontology.md` with at least one SPARQL
   example.
4. Every CLI subcommand documented in `reference/cli.md` matches the output of
   `riverbank <subcommand> --help` exactly (enforced by the CI generation script).
5. The docs CI build passes with `mkdocs build --strict` on every commit to
   `main`.
