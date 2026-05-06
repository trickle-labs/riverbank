# Add a custom extractor

Extractors transform fragments into structured RDF triples. riverbank ships two built-in extractors (`noop` and `instructor`), but you can add your own via Python entry points.

## The base class

```python
from riverbank.extractors.base import BaseExtractor, ExtractionResult, EvidenceSpan

class MyExtractor(BaseExtractor):
    name = "my-extractor"

    def extract(self, fragment_text: str, profile: dict) -> ExtractionResult:
        # Your extraction logic here
        triples = []
        # Each triple needs: subject, predicate, object_value, confidence, evidence
        triples.append({
            "subject": "http://example.org/entity/Acme",
            "predicate": "http://example.org/produces",
            "object_value": "widgets",
            "confidence": 0.92,
            "evidence": EvidenceSpan(
                char_start=42,
                char_end=78,
                excerpt="Acme produces widgets for the enterprise market",
            ),
        })
        return ExtractionResult(triples=triples)
```

## The EvidenceSpan contract

Every extracted triple **must** carry an `EvidenceSpan` with:

- `char_start` — character offset in the fragment where evidence begins
- `char_end` — character offset where evidence ends
- `excerpt` — the verbatim text at that range

The pipeline validates that the excerpt matches the text at the declared offset. Fabricated citations are rejected.

## Register via entry point

In your `pyproject.toml`:

```toml
[project.entry-points."riverbank.extractors"]
my-extractor = "my_package.extractors:MyExtractor"
```

After installing the package, the extractor is available in profiles:

```yaml
extractor: my-extractor
```

## Test your extractor

```python
def test_my_extractor():
    from my_package.extractors import MyExtractor

    extractor = MyExtractor()
    result = extractor.extract("Acme produces widgets for the enterprise market.", {})
    assert len(result.triples) >= 1
    assert result.triples[0]["confidence"] > 0.5
    assert result.triples[0]["evidence"].char_start >= 0
```

## Plugin discovery

riverbank discovers extractors at startup via `importlib.metadata.entry_points(group="riverbank.extractors")`. Your package must be installed in the same environment as riverbank.
