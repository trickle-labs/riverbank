# How-to guides

How-to guides are task-oriented. They answer "how do I do X?" and stop when X is done. They assume you already understand the [concepts](../concepts/index.md).

| Guide | Task |
|-------|------|
| [Write a compiler profile](write-a-compiler-profile.md) | Design and register a profile for your corpus |
| [Tune extraction quality](tune-extraction-quality.md) | Adjust volume, vocabulary, evidence grounding, SHACL validation, and all other quality levers |
| [Add a custom extractor](add-a-custom-extractor.md) | Ship a first-party extractor via entry points |
| [Add a custom parser](add-a-custom-parser.md) | Support a new document format |
| [Connect a new source](connect-a-new-source.md) | Pull documents from an API or message queue |
| [Configure Label Studio](configure-label-studio.md) | Set up the human review loop |
| [Run incremental recompile](run-incremental-recompile.md) | Recompile only what changed |
| [Explain a compiled artifact](explain-a-compiled-artifact.md) | Trace a fact back to its sources |
| [Explain a conflict](explain-a-conflict.md) | Diagnose and resolve contradictions |
| [Manage tenants](manage-tenants.md) | Full tenant lifecycle with GDPR erasure |
| [Deploy on Kubernetes](deploy-on-kubernetes.md) | Production Helm deployment |
| [Rotate secrets](rotate-secrets.md) | Update credentials without downtime |
| [Bulk reprocess a profile](bulk-reprocess-a-profile.md) | Re-extract all sources for a profile version |
| [Generate an SBOM](generate-an-sbom.md) | Produce a software bill of materials |
| [Control extraction focus](use-distillation-presets.md) | Tune precision vs recall with `comprehensive`, `high_precision`, and `facts_only` modes |
| [Use batch extraction](use-batch-extraction.md) | Group fragments into a single LLM call to reduce API costs |
