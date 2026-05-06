# Writing a plugin

riverbank supports five plugin extension points. This guide covers all of them.

## Entry-point groups

| Group | When to use |
|-------|-------------|
| `riverbank.parsers` | Support a new document format |
| `riverbank.fragmenters` | Custom splitting logic |
| `riverbank.extractors` | Alternative LLM or rule-based extraction |
| `riverbank.connectors` | Pull documents from APIs, S3, queues |
| `riverbank.reviewers` | Route to alternative review systems |

## Step 1: Implement the base class

Each group has a base class in `riverbank.<group>.base`:

```python
# Example: custom extractor
from riverbank.extractors.base import BaseExtractor, ExtractionResult, EvidenceSpan

class MyExtractor(BaseExtractor):
    name = "my-extractor"

    def extract(self, fragment_text: str, profile: dict) -> ExtractionResult:
        triples = []
        # Your extraction logic
        triples.append({
            "subject": "http://example.org/entity/X",
            "predicate": "http://example.org/relatedTo",
            "object_value": "Y",
            "confidence": 0.85,
            "evidence": EvidenceSpan(
                char_start=0,
                char_end=20,
                excerpt=fragment_text[:20],
            ),
        })
        return ExtractionResult(triples=triples)
```

## Step 2: Register the entry point

In your `pyproject.toml`:

```toml
[project.entry-points."riverbank.extractors"]
my-extractor = "my_package.extractors:MyExtractor"
```

## Step 3: Write tests

Use the existing `conftest.py` fixtures:

```python
def test_my_extractor():
    from my_package.extractors import MyExtractor

    extractor = MyExtractor()
    result = extractor.extract("Sample text for extraction.", {})

    assert len(result.triples) >= 1
    for triple in result.triples:
        assert triple["confidence"] > 0
        assert triple["evidence"].char_start >= 0
        assert triple["evidence"].char_end > triple["evidence"].char_start
```

## Step 4: Install and verify

```bash
pip install -e .
python -c "from importlib.metadata import entry_points; print([e.name for e in entry_points(group='riverbank.extractors')])"
```

Your extractor should appear in the list.

## Step 5: Use in a profile

```yaml
name: my-profile
version: 1
extractor: my-extractor
```

## Base class contracts

### Parser contract

- `parse(file_path)` → `ParsedDocument(content, headings, metadata)`
- Must preserve character offsets (evidence spans depend on this)
- `supported_extensions` determines file matching

### Fragmenter contract

- `fragment(document, policy)` → `list[Fragment]`
- Fragments must have non-overlapping character ranges
- Each fragment gets a stable `fragment_key`

### Extractor contract

- `extract(fragment_text, profile)` → `ExtractionResult(triples)`
- Every triple must include an `EvidenceSpan` with valid offsets
- The excerpt must match `fragment_text[char_start:char_end]`

### Connector contract

- `discover(config)` → `list[SourceDocument]`
- Each document needs a stable IRI for deduplication
- Configuration comes from the profile or environment

### Reviewer contract

- `enqueue(task)` → `task_id | None`
- `collect()` → yields `ReviewDecision` objects
- Decisions include: accepted, corrected, or rejected

## Review process for core inclusion

To get a plugin included in the riverbank core package:

1. Open an issue describing the plugin's purpose
2. Implement with full test coverage
3. Add an entry in `pyproject.toml` under the appropriate group
4. Submit a PR with the implementation, tests, and a docs page
5. Maintainers review for API contract compliance and test quality
