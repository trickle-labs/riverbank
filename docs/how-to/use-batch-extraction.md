# Use Batch Extraction

Batch extraction groups multiple document fragments into a single LLM call, reducing API costs and overhead.

## Enable Batch Extraction

Add to your profile's `extraction_strategy`:

```yaml
extraction_strategy:
  batch_size: 3  # Group 3 fragments per LLM call
```

## Cost Model

| Setup | Per-Fragment Calls | Per-Batch Calls | Savings |
|-------|-------------------|-----------------|---------|
| 10 fragments, no batching | 10 | — | — |
| 10 fragments, batch_size=2 | — | 5 | 50% |
| 10 fragments, batch_size=5 | — | 2 | 80% |

## Trade-offs

| Without Batching | With Batching |
|------------------|---------------|
| ✓ Minimal hallucination | ✗ Risk of cross-fragment connections |
| ✗ More LLM calls | ✓ Fewer calls |
| ✓ Per-token efficiency | ✗ More tokens/call |

## Quick Examples

### Use pre-built batched profile
```bash
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-batched.yaml
```

### Set batch_size in your profile
```yaml
extraction_strategy:
  mode: "permissive"
  batch_size: 2  # Batch 2 fragments per call
```

### Disable batching (default)
```yaml
extraction_strategy:
  mode: "permissive"
  # batch_size: 0 or omitted
```

## When to Use Batching

✅ **Use if:**
- Using OpenAI/hosted APIs (per-call overhead is high)
- Fragments are semantically independent
- Cost per call is significant

❌ **Don't use if:**
- Using Ollama locally (per-call overhead is minimal)
- Fragments are closely related (risk of hallucination)
- Paying per-token (fewer tokens is better)

## Implementation Details

- **Method:** `InstructorExtractor.extract_batch(fragments: list)`
- **Return:** Dict mapping `fragment_key → ExtractionResult`
- **Automatic:** No pipeline changes needed (optional in extractor)
- **Backward compatible:** Falls back to per-fragment if `batch_size` not set

## Supported LLM Backends

Batch extraction works with LLM backends that properly support JSON structured output:

- ✅ OpenAI (JSON mode)
- ✅ Claude/Copilot (JSON mode)
- ❌ Ollama/Gemma (limited structured output support)

If you're using Ollama locally, batch extraction may not work reliably. Per-fragment extraction is recommended.
