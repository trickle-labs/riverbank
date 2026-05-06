# Concepts

This section explains the ideas behind riverbank. It's for readers who want to understand the system, not just operate it.

| Concept | What it explains |
|---------|-----------------|
| [The compiler analogy](the-compiler-analogy.md) | Why treating documents as source code makes sense |
| [Pipeline stages](pipeline-stages.md) | What happens at each step of compilation |
| [Compiler profiles](compiler-profiles.md) | The primary configuration surface |
| [Fragment and artifact model](fragment-and-artifact-model.md) | How documents become queryable units |
| [Incremental compilation](incremental-compilation.md) | Why only changed content gets recompiled |
| [Epistemic model](epistemic-model.md) | All 9 status values, negative knowledge, argument graphs |
| [Provenance model](provenance-model.md) | PROV-O chains, citation grounding, GDPR erasure |
| [Quality gates](quality-gates.md) | SHACL validation, ingest gates, score functions |
| [Multi-tenancy](multi-tenancy.md) | RLS, named graph isolation, tenant lifecycle |
| [Federation](federation.md) | Pulling triples from remote pg_ripple instances |
| [Rendering](rendering.md) | Generating pages from compiled knowledge |
