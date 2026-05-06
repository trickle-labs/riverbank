# riverbank

**A knowledge compiler for PostgreSQL.**

riverbank transforms raw documents into a governed, queryable knowledge graph. Feed it Markdown files, PDFs, tickets, or API feeds — it compiles them into structured facts with citations, confidence scores, and provenance chains you can query with SPARQL or retrieve with plain English.

Documents are bad runtime formats. riverbank compiles them into something better.

---

## Get started in three commands

```bash
docker compose up -d postgres ollama
riverbank init
riverbank ingest examples/markdown-corpus/
riverbank query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
```

You now have a compiled knowledge graph. Every fact traces back to the source fragment it came from.

---

## Who is this for?

<div class="grid cards" markdown>

-   **Practitioners**

    Senior engineers and ML engineers who want to compile internal documentation into a governed knowledge graph they can query directly.

    [:octicons-arrow-right-24: Quick start](getting-started/quickstart.md)

-   **Operators**

    Platform engineers and SREs deploying riverbank at scale on Kubernetes with Prometheus, advisory locks, and circuit breakers.

    [:octicons-arrow-right-24: Operations](operations/index.md)

-   **Evaluators**

    Architects and researchers assessing whether riverbank's epistemic model and provenance guarantees fit their use case.

    [:octicons-arrow-right-24: Concepts](concepts/index.md)

</div>

---

## Documentation sections

| Section | What you'll find |
|---------|-----------------|
| [Getting started](getting-started/index.md) | Install, run your first compilation, understand the output |
| [Tutorials](tutorials/index.md) | End-to-end walkthroughs for realistic scenarios |
| [How-to guides](how-to/index.md) | Task-oriented recipes: "how do I do X?" |
| [Concepts](concepts/index.md) | Design philosophy, epistemic model, provenance, incremental compilation |
| [Reference](reference/index.md) | CLI, configuration, ontology, metrics — complete lookup tables |
| [Operations](operations/index.md) | Helm chart, observability, scaling, upgrades |
| [Contributing](contributing/index.md) | Development setup, tests, plugin authoring, release process |
