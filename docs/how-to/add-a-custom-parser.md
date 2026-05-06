# Add a custom parser

Parsers convert raw document formats into a normalized text representation that the fragmenter can split. riverbank ships parsers for Markdown and Docling-supported formats.

## The base class

```python
from riverbank.parsers.base import BaseParser, ParsedDocument

class MyParser(BaseParser):
    name = "my-parser"
    supported_extensions = [".rst", ".txt"]

    def parse(self, file_path: str) -> ParsedDocument:
        with open(file_path) as f:
            content = f.read()

        return ParsedDocument(
            content=content,
            headings=self._extract_headings(content),
            metadata={"format": "rst"},
        )

    def _extract_headings(self, content: str) -> list[dict]:
        # Return list of {"level": int, "text": str, "char_start": int}
        ...
```

## Register via entry point

```toml
[project.entry-points."riverbank.parsers"]
my-parser = "my_package.parsers:MyParser"
```

## Key requirements

- Return a `ParsedDocument` with the full text content and heading positions
- Heading positions are used by the fragmenter to split the document
- The `supported_extensions` field determines which files your parser handles
- The parser must preserve character offsets accurately (evidence spans depend on this)

## Test your parser

```python
def test_my_parser():
    from my_package.parsers import MyParser

    parser = MyParser()
    doc = parser.parse("tests/fixtures/sample.rst")
    assert doc.content
    assert len(doc.headings) > 0
```
