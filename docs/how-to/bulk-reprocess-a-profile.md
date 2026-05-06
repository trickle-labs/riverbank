# Bulk reprocess a profile

Re-extract all sources compiled by a specific profile version. Useful when you've improved extraction prompts and want to recompile the entire corpus.

## Basic usage

```bash
riverbank recompile --profile docs-policy-v1 --version 1
```

This:

1. Finds all sources associated with the profile
2. Re-runs the full ingestion pipeline for each source
3. Produces a summary with triples added, removed, and unchanged

## Dry-run mode

Preview what would be recompiled without executing:

```bash
riverbank recompile --profile docs-policy-v1 --version 1 --dry-run
```

## Limit the scope

Recompile only the first N sources (useful for testing):

```bash
riverbank recompile --profile docs-policy-v1 --version 1 --limit 10
```

## When to recompile

- After updating the profile's `prompt_text`
- After upgrading the LLM model (e.g., switching from `gpt-4` to `gpt-4o`)
- After fixing an extractor bug
- After expanding `competency_questions` and wanting to verify the full corpus

## Cost considerations

Bulk recompile triggers LLM calls for every fragment (hash check is bypassed). Estimate the cost first:

```bash
riverbank runs --since 30d --profile docs-policy-v1
```

Look at the "Cost" column to estimate per-fragment cost, then multiply by fragment count.

!!! warning
    A full recompile of a large corpus can be expensive. Consider using `--limit` to test on a subset first.
