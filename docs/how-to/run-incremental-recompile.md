# Run incremental recompile

When a source document changes, only the fragments derived from it need recompilation. This guide shows how to trigger and monitor incremental recompiles.

## How it works

1. Re-ingest the changed document with `riverbank ingest`
2. The hash check detects which fragments changed
3. Only changed fragments go through extraction
4. The artifact dependency graph (`_riverbank.artifact_deps`) tracks which compiled facts depend on which fragments
5. Stale facts are invalidated and recompiled

## Re-ingest a changed corpus

```bash
riverbank ingest /path/to/corpus/
```

The ingest summary shows:

- **Fragments skipped (hash)** — unchanged fragments, zero LLM cost
- **Fragments processed** — changed fragments that were re-extracted

## Monitor what changed

```bash
riverbank runs --since 1h
```

Only the runs for changed fragments will appear.

## Explain dependencies

To see what depends on a specific artifact:

```bash
riverbank explain http://example.org/entity/Acme
```

This shows the full dependency tree: which fragments, profile version, and rule set contributed to the artifact.

## Force recompile

To force recompilation of all sources for a profile (ignoring hashes):

```bash
riverbank recompile --profile docs-policy-v1 --version 1
```

See [Bulk reprocess a profile](bulk-reprocess-a-profile.md) for details.
