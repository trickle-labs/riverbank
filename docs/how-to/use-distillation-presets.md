# Use Distillation Presets

Distillation lets you control how much information the LLM extracts from documents by using preset system prompts.

## Distillation Levels

- **default** — All atomic facts (comprehensive knowledge graph)
- **essential** — Core facts only (WHO + WHAT, reduced noise)  
- **minimal** — Achievements/discoveries (filtered, focused)

## Quick Start

### Command Line (Easiest)

```bash
# Default - comprehensive knowledge graph
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-statement.yaml

# Essential - core facts only  
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-essential.yaml

# Minimal - achievements only
riverbank evaluate-wikidata --article "Marie Curie" \
  --profile examples/profiles/wikidata-eval-v1-llm-minimal.yaml
```

### YAML Configuration

Add to your profile:

```yaml
fragmenter: llm_statement
llm_statement_fragmentation:
  max_doc_chars: 20000
  max_statements: 200
  distillation_level: "essential"  # or "default", "minimal"
```

### Programmatic

```python
from riverbank.fragmenters.llm_statement import LLMStatementFragmenter
from riverbank.config import get_settings

settings = get_settings()

# Essential: core facts only
fragmenter = LLMStatementFragmenter(
    settings=settings,
    distillation_level="essential"
)

# Process documents
for doc in documents:
    fragments = list(fragmenter.fragment(doc))
```

## Real Example: Marie Curie

### Default (12 statements)
- Born in Warsaw, Nov 24, 1867
- Father was math/physics teacher
- Studied at University of Paris
- Married Pierre Curie in 1895
- Discovered polonium and radium
- Won 1903 Nobel Prize in Physics
- Pierre died in 1906
- Won 1911 Nobel Prize in Chemistry
- First woman to win Nobel Prize
- Founded Curie Institute in 1909
- Died July 4, 1934
- *+ more details*

### Essential (2 statements)
- Polish-born physicist and chemist born in Warsaw on November 24, 1867
- Won Nobel Prizes in Physics (1903) and Chemistry (1911) for pioneering research on radioactivity and discovery of radium and polonium

### Minimal (5 statements)
- Conducted pioneering research on radioactivity
- Discovered polonium and radium
- Won 1903 Nobel Prize in Physics
- Won 1911 Nobel Prize in Chemistry
- Founded the Curie Institute in Paris in 1909

## When to Use Each

| Level | Use Case |
|-------|----------|
| **default** | Wikipedia/biographical extraction, comprehensive graphs |
| **essential** | Reduced noise, focus on primary contributions, cleaner datasets |
| **minimal** | Achievement tracking, discovery databases, competitive analysis |

## Built-in Profiles

Located in `examples/profiles/`:

- `wikidata-eval-v1-llm-statement.yaml` (default)
- `wikidata-eval-v1-llm-essential.yaml` (essential)  
- `wikidata-eval-v1-llm-minimal.yaml` (minimal)
