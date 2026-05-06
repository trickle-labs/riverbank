# Plugin API

riverbank discovers plugins via Python entry points. Five extension groups are supported.

## Entry point groups

| Group | Purpose | Base class |
|-------|---------|------------|
| `riverbank.parsers` | Convert document formats to normalized text | `BaseParser` |
| `riverbank.fragmenters` | Split parsed documents into compilation units | `BaseFragmenter` |
| `riverbank.extractors` | Transform fragments into RDF triples | `BaseExtractor` |
| `riverbank.connectors` | Discover and fetch documents from external sources | `BaseConnector` |
| `riverbank.reviewers` | Route extractions to human review systems | `BaseReviewer` |

## Registration

In your `pyproject.toml`:

```toml
[project.entry-points."riverbank.parsers"]
my-parser = "my_package.parsers:MyParser"

[project.entry-points."riverbank.extractors"]
my-extractor = "my_package.extractors:MyExtractor"
```

## Built-in plugins

### Parsers

| Name | Module | Description |
|------|--------|-------------|
| `markdown` | `riverbank.parsers.markdown:MarkdownParser` | Markdown via `markdown-it-py` |
| `docling` | `riverbank.parsers.docling:DoclingParser` | PDF, DOCX, HTML via Docling |

### Fragmenters

| Name | Module | Description |
|------|--------|-------------|
| `heading` | `riverbank.fragmenters.heading:HeadingFragmenter` | Split at heading boundaries |

### Extractors

| Name | Module | Description |
|------|--------|-------------|
| `noop` | `riverbank.extractors.noop:NoOpExtractor` | Synthetic triples for testing |
| `instructor` | `riverbank.extractors.instructor_extractor:InstructorExtractor` | Real LLM extraction via Instructor |

### Connectors

| Name | Module | Description |
|------|--------|-------------|
| `filesystem` | `riverbank.connectors.fs:FilesystemConnector` | Local file system traversal |

### Reviewers

| Name | Module | Description |
|------|--------|-------------|
| `file` | `riverbank.reviewers.file:FileReviewer` | File-based review queue |
| `label_studio` | `riverbank.reviewers.label_studio:LabelStudioReviewer` | Label Studio integration |

## Base class contracts

### `BaseParser`

```python
class BaseParser:
    name: str
    supported_extensions: list[str]

    def parse(self, file_path: str) -> ParsedDocument:
        """Parse a file and return normalized content with heading positions."""
        ...
```

### `BaseFragmenter`

```python
class BaseFragmenter:
    name: str

    def fragment(self, document: ParsedDocument, policy: EditorialPolicy) -> list[Fragment]:
        """Split a parsed document into fragments."""
        ...
```

### `BaseExtractor`

```python
class BaseExtractor:
    name: str

    def extract(self, fragment_text: str, profile: dict) -> ExtractionResult:
        """Extract RDF triples from a text fragment."""
        ...
```

### `BaseConnector`

```python
class BaseConnector:
    name: str

    def discover(self, config: dict) -> list[SourceDocument]:
        """Discover available documents from the source."""
        ...
```

### `BaseReviewer`

```python
class BaseReviewer:
    name: str

    def enqueue(self, task: ReviewTask) -> str | None:
        """Submit a task for human review. Return task ID."""
        ...

    def collect(self) -> Iterator[ReviewDecision]:
        """Collect completed review decisions."""
        ...
```

## Discovery mechanism

Plugins are discovered at startup via:

```python
from importlib.metadata import entry_points

eps = entry_points(group="riverbank.extractors")
for ep in eps:
    extractor_class = ep.load()
```

The package must be installed in the same Python environment as riverbank.
