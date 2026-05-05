# Architecture

## Overview

Ariadne consists of three layers:

1. **Ingestion layer** — parses documents and fragments them into sections
2. **Extraction layer** — applies an LLM-based extraction profile to each section
3. **Storage layer** — persists validated triples in a PostgreSQL knowledge graph

```
Documents → Parser → Fragmenter → Extractor → Validator → Graph store
```

## Ingestion layer

The ingestion layer supports three document formats:

| Format | Parser | Notes |
|---|---|---|
| Markdown | `ariadne.parsers.markdown` | Default for plain text |
| PDF | `ariadne.parsers.pdf` | Requires `pdfplumber` |
| DOCX | `ariadne.parsers.docx` | Requires `python-docx` |

Document parsing is handled by the `DocumentParser` protocol. Third-party
parsers can be registered via Python entry points under the
`ariadne.parsers` group.

## Extraction layer

Extraction uses a **profile** — a Pydantic schema combined with a system prompt.
The profile defines:

- the target entity types (e.g. `Person`, `Organisation`, `Claim`)
- the relationship types to extract
- the minimum confidence threshold for acceptance
- the citation grounding strategy

The default profile ships with Ariadne. Custom profiles are YAML files placed in
`~/.ariadne/profiles/`.

### LLM providers

Ariadne supports any OpenAI-compatible endpoint:

| Provider | Config key |
|---|---|
| Ollama (local) | `provider: ollama` |
| OpenAI | `provider: openai` |
| Anthropic | `provider: anthropic` |
| vLLM | `provider: vllm` |

The default provider is Ollama with the `llama3.2` model, which requires no API key.

## Storage layer

Ariadne stores all triples in a PostgreSQL database using the `pg_ripple`
extension. The `pg_ripple` extension provides:

- RDF-native quad storage (subject, predicate, object, named graph)
- SPARQL 1.1 query support
- SHACL constraint validation
- pgvector integration for embedding-based similarity search

The storage layer is **append-only by default**. Superseded claims are marked
with a `prov:invalidatedAtTime` timestamp rather than deleted.

## Deployment

Ariadne is distributed as a Docker image. A single `docker compose up` command
starts the full stack: PostgreSQL with `pg_ripple`, the Ariadne worker,
and Langfuse for LLM observability.

The Meridian Institute operates a hosted version of Ariadne for institutional
members. The self-hosted version is functionally equivalent.
