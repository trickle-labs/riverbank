# Wikidata Evaluation Framework — Implementation Plan

> **Status:** Ready for implementation  
> **Blocked by:** None  
> **Depends on:** v0.14.0 (structural improvements complete)  
> **Phase 1 Duration:** 1 week  
> **Total Duration (Phases 1–4):** 4 weeks  
> **Delivery:** v0.15.0 (v0.15.1 follows as feedback loop)

---

## 1. Architecture Overview

### 1.1 Module structure

```
src/riverbank/
├── eval/                                 # New package
│   ├── __init__.py
│   ├── wikidata_client.py               # Wikidata SPARQL queries
│   ├── wikipedia_client.py              # Wikipedia API + caching
│   ├── property_alignment.py            # P-id ↔ predicate mapping
│   ├── entity_resolution.py             # Entity linking
│   ├── scorer.py                        # Precision/recall computation
│   ├── models.py                        # Dataclasses (ArticleEvalResult, etc.)
│   └── cache.py                         # Cache management
├── cli.py                               # Add evaluate-wikidata commands
└── ...existing code...

tests/
├── eval/
│   ├── test_wikidata_client.py          # Unit tests
│   ├── test_wikipedia_client.py
│   ├── test_property_alignment.py
│   ├── test_entity_resolution.py
│   ├── test_scorer.py
│   └── integration/
│       └── test_evaluate_wikidata_e2e.py

examples/
├── profiles/
│   └── wikidata-eval-v1.yaml            # Evaluation profile
└── golden/
    └── wikidata-benchmark-10.yaml       # PoC dataset (10 articles)

eval/                                    # New directory (outputs)
├── wikidata-benchmark-1k.yaml          # Full dataset definition
├── property-alignment-v1.yaml          # Property mapping table
├── results/                            # Evaluation run outputs
│   └── .gitkeep
└── .article_cache/                     # Article cache
    └── .gitkeep
```

### 1.2 Key dependencies to add

```
# pyproject.toml extras: [eval]
requests>=2.31.0                    # MediaWiki API + Wikidata SPARQL
aiohttp>=3.9.0                      # Async HTTP for parallel Wikipedia batches
html2text>=2024.2.26                # Convert Wikipedia HTML → Markdown
rapidfuzz>=3.0.0                    # Fuzzy string matching for entity resolution
numpy>=1.24.0                       # Calibration curve + Pearson ρ computation
matplotlib>=3.7.0                   # Calibration curve plots

# Already in riverbank (no new deps needed):
# rdflib>=7.0.0, pydantic>=2.0.0, scipy (for Pearson ρ if needed)
```

> **Note on `models.py` and `cache.py`:** These two modules are part of Phase 1
> but their APIs are foundational for the whole package:
>
> **`src/riverbank/eval/models.py`** — All shared dataclasses live here to avoid
> circular imports between modules. Exports: `WikipediaArticle`, `CacheMetadata`,
> `WikidataStatement`, `WikidataItem`, `PropertyAlignment`, `EntityMatch`,
> `ResolutionCache`, `TripleMatch`, `ArticleScore`, `DatasetResult`, `RunMetadata`.
>
> **`src/riverbank/eval/cache.py`** — Cache management independent of Wikipedia
> client, so it can be tested and reused. Class `ArticleCache` wraps the
> `.riverbank/article_cache/` directory. Methods: `get(title)`, `put(article)`,
> `invalidate(title)`, `list_all()`, `prune(max_age_days)`, `stats()`.
> Serialization: article Markdown in `<normalized_title>.md`, metadata in
> `<normalized_title>.meta.json`. This backing class powers all `riverbank cache`
> CLI subcommands.

> **Note:** `scikit-learn` is NOT required; `numpy.corrcoef` covers the Pearson ρ
> computation. `scipy.stats.pearsonr` is available via `scipy` if riverbank already
> has it as a transitive dependency.

---

## 2. Phase 1: Proof of Concept (Week 1)

**Goal:** Extract, align, score, and validate 50 articles (10 per domain × 5 domains). Manual review of 10 results. Go/no-go gate before Phase 2.

> **PoC scope:** 50 articles total across 5 domains. The benchmark dataset YAML
> (`examples/golden/wikidata-benchmark-poc.yaml`) lists all 50; CI smoke tests
> run `--sample 10` to keep CI under 10 minutes.

### 2.1 Step 1.1: Wikipedia client + caching (Day 1)

**File:** `src/riverbank/eval/wikipedia_client.py`

**Dataclasses:**
```python
@dataclass
class WikipediaArticle:
    title: str
    url: str
    qid: str  # Wikidata Q-id
    content: str  # Markdown
    source_wikilinks: list[str]  # [[Links]] from article
    fetch_timestamp: datetime
    cache_path: Path | None

@dataclass
class CacheMetadata:
    title: str
    url: str
    qid: str
    fetch_timestamp: datetime
    cache_ttl_days: int
    is_stale: bool
```

**Class: `WikipediaClient`**
```python
class WikipediaClient:
    def __init__(self, cache_dir: Path = None, cache_ttl_days: int = 30):
        self.cache_dir = cache_dir or Path.home() / ".riverbank" / "article_cache"
        self.cache_ttl_days = cache_ttl_days
        
    def fetch_article(self, query: str, force_fresh: bool = False) -> WikipediaArticle:
        """
        Resolve query (title/URL/Q-id) → fetch article + cache.
        
        1. Normalize query (extract title from URL, resolve Q-id to article)
        2. Check cache; return if valid and not force_fresh
        3. Fetch from MediaWiki API (stable version, Markdown format)
        4. Save to cache with metadata
        5. Return WikipediaArticle
        """
        
    def get_qid_from_article(self, article_title: str) -> str:
        """Query Wikipedia API for article's Wikidata sitelink."""
        
    def _normalize_query(self, query: str) -> str:
        """Handle 'Marie Curie', URLs, Q-ids uniformly."""
        
    def _fetch_from_wikipedia_api(self, title: str) -> str:
        """
        Fetch article as Markdown via MediaWiki REST API.
        
        MediaWiki does NOT return Markdown natively. Strategy:
        1. Call action=parse with prop=text (renders HTML)
           OR use the REST API: /api/rest_v1/page/html/{title}
        2. Convert HTML → Markdown via html2text.HTML2Text()
           - Set ignore_links=False (keep wikilinks)
           - Set body_width=0 (no line wrapping)
        3. Strip navigation/footer boilerplate sections
        
        User-Agent header REQUIRED:
           'User-Agent: riverbank-eval/0.15.0 (trickle-labs/riverbank)'
        Both Wikipedia and Wikidata reject requests without a descriptive UA.
        """
        
    def cache_is_valid(self, cache_path: Path) -> bool:
        """Check TTL; return False if stale."""
```

**CLI commands added to `src/riverbank/cli.py`:**
```bash
riverbank cache list wikidata-articles
riverbank cache clear wikidata-articles [--title "Title"]
riverbank cache stats wikidata-articles
```

**Tests:** `tests/eval/test_wikipedia_client.py`
- Mock Wikipedia API; verify title/URL/Q-id resolution
- Cache write/read cycle
- TTL staleness detection

### 2.2 Step 1.2: Wikidata client (Day 1)

**File:** `src/riverbank/eval/wikidata_client.py`

**Dataclasses:**
```python
@dataclass
class WikidataStatement:
    property_id: str  # P31, P106, etc.
    property_label: str
    value: str | int | date
    value_type: str  # "wikibase-item" | "string" | "quantity" | "time"
    value_label: str | None  # Human-readable label for Q-ids
    qualifiers: dict[str, list[str]]  # P580 (start) → [date], etc.
    rank: str  # "normal" | "preferred" | "deprecated"
    references: list[dict]  # Source citations

@dataclass
class WikidataItem:
    qid: str
    label: str
    description: str
    aliases: list[str]
    statements: list[WikidataStatement]
```

**Class: `WikidataClient`**
```python
class WikidataClient:
    def __init__(self, sparql_endpoint: str = "https://query.wikidata.org/sparql"):
        self.endpoint = sparql_endpoint
        
    def get_item_by_qid(self, qid: str) -> WikidataItem:
        """Fetch Wikidata item and all its statements (excluding external IDs, media)."""
        
    def get_item_by_wikipedia_title(self, title: str, language: str = "en") -> WikidataItem:
        """Query sitelink index; resolve to Q-id; fetch item."""
        
    def query_sparql(self, sparql: str, timeout: int = 60) -> list[dict]:
        """
        Execute SPARQL query against Wikidata endpoint.
        
        IMPORTANT: Wikidata SPARQL requires a User-Agent header:
            'User-Agent: riverbank-eval/0.15.0 (trickle-labs/riverbank)'
        Requests without User-Agent are rejected with HTTP 403.
        
        Retry policy: 3 attempts with exponential backoff (2s, 4s, 8s).
        On timeout or endpoint unavailability, raise WikidataUnavailableError.
        """
        
    def _filter_statements(self, raw_statements: list) -> list[WikidataStatement]:
        """Exclude external identifiers, media, interwiki links."""
```

**Template SPARQL query** (embedded in the code):
```sparql
SELECT ?property ?propertyLabel ?value ?valueLabel ?rank
WHERE {
  wd:{QID} ?p ?statement .
  ?statement ?ps ?value .
  ?property wikibase:claim ?p .
  ?property wikibase:statementProperty ?ps .
  
  # Exclude external identifiers and media
  ?property wikibase:propertyType ?type .
  FILTER(?type NOT IN (
    wikibase:ExternalId,
    wikibase:CommonsMedia,
    wikibase:Url
  ))
  
  OPTIONAL { ?statement wikibase:rank ?rank . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?propertyLabel
```

**Tests:** `tests/eval/test_wikidata_client.py`
- Mock SPARQL endpoint
- Verify statement filtering (no external IDs)
- Multi-item batch queries

### 2.3 Step 1.3: Property alignment table (Day 2)

**File:** `src/riverbank/eval/property_alignment.py`

**Dataclass:**
```python
@dataclass
class PropertyAlignment:
    wikidata_pid: str  # P31, P106, P569, ...
    wikidata_label: str  # "instance of", "occupation", "birth date"
    riverbank_predicates: list[str]  # ["rdf:type", "ex:hasOccupation"]
    value_mapping: dict[str, str]  # Wikidata Q-id → riverbank IRI
    alignment_confidence: float  # 0.0–1.0 (manual assessment)
    notes: str  # "Riverbank extracts both P106 and P108 as occupation"
```

**Initial table** (50 properties for PoC → 50+ for full):

```python
PROPERTY_ALIGNMENT_TABLE = [
    # Biographies
    PropertyAlignment(
        wikidata_pid="P31",
        wikidata_label="instance of",
        riverbank_predicates=["rdf:type", "pgc:isA"],
        value_mapping={},  # Q5 (human) → ex:Person, etc.
        alignment_confidence=0.95,
        notes="Universal: every entity has P31"
    ),
    PropertyAlignment(
        wikidata_pid="P106",
        wikidata_label="occupation",
        riverbank_predicates=["pgc:hasOccupation", "ex:occupation"],
        value_mapping={},
        alignment_confidence=0.90,
        notes="String or Q-id values"
    ),
    PropertyAlignment(
        wikidata_pid="P569",
        wikidata_label="birth date",
        riverbank_predicates=["pgc:birthDate", "foaf:birthday"],
        value_mapping={},
        alignment_confidence=0.92,
        notes="ISO 8601 date format"
    ),
    # ... 47 more
]
```

**Class: `PropertyAlignmentTable`**
```python
class PropertyAlignmentTable:
    def __init__(self, alignment_data: list[PropertyAlignment] = None):
        self.alignments = alignment_data or PROPERTY_ALIGNMENT_TABLE
        self._pid_index = {a.wikidata_pid: a for a in self.alignments}
        
    def get_alignment(self, wikidata_pid: str) -> PropertyAlignment | None:
        """Look up P-id in table."""
        
    def get_riverbank_predicates(self, wikidata_pid: str) -> list[str]:
        """Return equivalent riverbank predicates."""
        
    def to_yaml(self, path: Path) -> None:
        """Export table as examples/property-alignment-v1.yaml."""
```

**Examples file:** `examples/property-alignment-v1.yaml`
```yaml
version: 1
date: 2026-05-07
alignments:
  - wikidata_pid: P31
    label: instance of
    riverbank_predicates: [rdf:type, pgc:isA]
    confidence: 0.95
    notes: "Universal: every entity has P31"
  # ... 49 more
```

**Tests:** `tests/eval/test_property_alignment.py`
- Load alignment table
- Verify no duplicate P-ids
- Round-trip YAML serialization

### 2.4 Step 1.4: Entity resolution (Day 2)

**File:** `src/riverbank/eval/entity_resolution.py`

**Dataclasses:**
```python
@dataclass
class EntityMatch:
    riverbank_iri: str
    wikidata_qid: str
    match_type: str  # "sitelink" | "label" | "fuzzy_label" | "context_disambig"
    confidence: float  # 0.0–1.0
    explanation: str

@dataclass
class ResolutionCache:
    """In-memory cache of IRI → EntityMatch to avoid redundant Wikidata lookups."""
    _cache: dict[str, EntityMatch] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
```

**Class: `EntityResolver`**
```python
class EntityResolver:
    def __init__(self, wikidata_client: WikidataClient):
        self.wikidata = wikidata_client
        
    def resolve_entity(
        self,
        riverbank_iri: str,
        article_title: str,
        article_context: str,
        candidate_entities: list[str] = None
    ) -> EntityMatch | None:
        """
        Attempt to resolve riverbank entity to Wikidata Q-id.
        
        Strategy:
        1. Extract label from IRI (e.g., ex:Marie_Curie → "Marie Curie")
        2. If article_title in label, use article's main entity Q-id (sitelink)
        3. Fuzzy match label against Wikidata labels/aliases (Levenshtein ≥0.9)
        4. If multiple matches, disambiguate via article_context (P31 type)
        5. Return best match with confidence
        """
        
    def _extract_label_from_iri(self, iri: str) -> str:
        """Parse ex:Marie_Curie or http://example.org/person/marie-curie."""
        
    def _fuzzy_match_wikidata(
        self,
        label: str,
        min_ratio: float = 0.9
    ) -> list[tuple[str, float]]:
        """Query Wikidata; fuzzy-match candidates; return [(qid, ratio)]."""
        
    def _disambiguate_by_context(
        self,
        candidates: list[str],  # List of Q-ids
        context_type: str  # "person" | "organization" | ...
    ) -> str | None:
        """Filter candidates by P31 (instance of) type."""
```

**Tests:** `tests/eval/test_entity_resolution.py`
- Mock Wikidata client
- Test label extraction from IRIs
- Fuzzy matching with known results
- Disambiguation by entity type

### 2.5 Step 1.5: Scoring engine (Day 3)

**File:** `src/riverbank/eval/scorer.py`

**Dataclasses:**
```python
@dataclass
class TripleMatch:
    riverbank_triple: tuple[str, str, str]  # (s, p, o)
    riverbank_confidence: float
    wikidata_statement: WikidataStatement | None
    match_type: str  # "exact" | "partial" | "no_match"
    match_score: float  # 0.0–1.0
    evidence: str

@dataclass
class ArticleScore:
    article_title: str
    wikidata_qid: str
    riverbank_triples: int
    wikidata_statements: int
    triple_matches: list[TripleMatch]
    
    precision: float
    recall: float
    f1: float
    
    true_positives: int
    false_positives: int
    false_negatives: int
    novel_discoveries: int  # Unmatched riverbank triples
    
    confidence_buckets: dict[str, tuple[int, float]]  # bucket → (count, observed_accuracy)
```

**Class: `Scorer`**
```python
class Scorer:
    def __init__(
        self,
        alignment_table: PropertyAlignmentTable,
        entity_resolver: EntityResolver
    ):
        self.alignment = alignment_table
        self.resolver = entity_resolver
        
    def score_article(
        self,
        article_title: str,
        riverbank_triples: list[tuple[str, str, str, float]],  # (s, p, o, confidence)
        wikidata_item: WikidataItem
    ) -> ArticleScore:
        """
        Main scoring pipeline:
        1. For each riverbank triple, attempt to match against Wikidata statements
        2. Compute precision, recall, F1
        3. Bucket confidence scores and compute calibration
        4. Return ArticleScore
        """
        
    def _match_triple(
        self,
        riverbank_s: str,
        riverbank_p: str,
        riverbank_o: str,
        wikidata_statements: list[WikidataStatement],
        article_context: str
    ) -> TripleMatch:
        """
        Attempt to find corresponding Wikidata statement.
        
        1. Resolve riverbank subject to Q-id (entity resolver)
        2. Map riverbank predicate to Wikidata P-id (alignment table)
        3. Normalize object (fuzzy string match or Q-id resolution)
        4. Find matching statement in Wikidata
        5. Return TripleMatch with score
        """
        
    def _compute_precision_recall(self, matches: list[TripleMatch]) -> tuple[float, float, float]:
        """From true/false positive/negative counts, compute P, R, F1."""
        
    def _compute_confidence_calibration(self, matches: list[TripleMatch]) -> dict:
        """
        Bucket matches by confidence (0–0.25, 0.25–0.5, ..., 0.75–1.0).
        For each bucket, compute observed accuracy (what % were true positives).
        Return {bucket: (count, observed_accuracy)}.
        """
```

**Tests:** `tests/eval/test_scorer.py`
- Mock alignment table and entity resolver
- Known good triples → expect high score
- Known bad triples → expect low score
- Calibration bucket computation

### 2.6 Step 1.6: CLI + integration (Day 3–4)

**File:** `src/riverbank/cli.py` — Add commands:

```python
@click.command()
@click.option("--article", type=str, required=True,
              help="Wikipedia article title, URL, or Wikidata Q-id")
@click.option("--profile", type=str, default="wikidata-eval-v1",
              help="Compiler profile to use")
@click.option("--no-cache", is_flag=True,
              help="Bypass local cache; fetch fresh from Wikipedia")
@click.option("--cache-only", is_flag=True,
              help="Use only cached articles; error if not found")
def evaluate_wikidata_article(article, profile, no_cache, cache_only):
    """
    Evaluate riverbank extraction on a single Wikipedia article.
    
    Steps:
    1. Fetch Wikipedia article (with caching)
    2. Ingest article via riverbank compiler (using specified profile)
    3. Fetch corresponding Wikidata item
    4. Score extracted triples against Wikidata
    5. Print precision/recall/F1 summary
    """
    # Implementation

@click.command()
@click.option("--dataset", type=Path, required=True,
              help="Dataset YAML with article list")
@click.option("--profile", type=str, default="wikidata-eval-v1")
@click.option("--output", type=Path, default=Path("eval/results/latest.json"))
@click.option("--parallel", type=int, default=8,
              help="Number of articles to evaluate in parallel")
@click.option("--sample", type=int, default=None,
              help="Evaluate only first N articles (for smoke tests)")
def evaluate_wikidata_dataset(dataset, profile, output, parallel, sample):
    """
    Batch evaluate riverbank over full benchmark dataset.
    
    Steps:
    1. Load dataset YAML (list of 1,000 articles)
    2. For each article in parallel:
       a. Fetch Wikipedia article
       b. Ingest via riverbank
       c. Fetch Wikidata item
       d. Score
    3. Aggregate results (per-domain, per-property)
    4. Write JSON report to output path
    5. Print summary statistics
    """
```

**Integration with `riverbank ingest`:**
The `evaluate_wikidata_article` command will:
1. Create a temporary named graph: `<eval:{uuid4}>` (unique per evaluation run)
2. Call the existing `riverbank ingest` flow with the fetched Markdown article,
   routing output to the temporary named graph via `--graph <eval:uuid4>`
3. Query triples from the temporary graph via SPARQL:
   ```sparql
   SELECT ?s ?p ?o ?confidence
   WHERE {
     GRAPH <eval:{run_id}> { ?s ?p ?o }
     OPTIONAL { ?s pgc:confidence ?confidence }
   }
   ```
4. Pass extracted triples to `Scorer.score_article()`
5. **Always** drop the temporary graph after scoring:
   `pg_ripple.drop_graph(conn, f'eval:{run_id}')`
   (use try/finally to guarantee cleanup even on error)

### 2.7 Step 1.7: PoC dataset + manual validation (Day 4–5)

**File:** `examples/golden/wikidata-benchmark-poc.yaml`

> **Naming convention:** The PoC file is `wikidata-benchmark-poc.yaml` (not `10`),
> containing all 50 articles. CI uses `--sample 10` to run quickly.

```yaml
# 50 articles (10 per domain × 5 domains) for Phase 1 PoC
version: 1
dataset_name: "wikidata-benchmark-poc"
articles:
  # Biography (living)
  - title: "Elon Musk"
    qid: Q317521
    domain: "biography_living"
    reason: "Well-structured Wikipedia infobox; ~50 Wikidata statements"
    
  - title: "Serena Williams"
    qid: Q34782
    domain: "biography_living"
    
  # ... 8 more biographies ...
  
  # Organization
  - title: "Apple Inc."
    qid: Q312
    domain: "organization"
    
  # ... remaining domains ...
```

**Manual validation steps:**
- Run `riverbank evaluate-wikidata --article "Elon Musk" --profile wikidata-eval-v1`
- Inspect JSON output; verify P31 (instance of), P106 (occupation), P580/P582 (dates) are matched
- Fix alignment table entries that produce false negatives
- Update property alignment table based on learnings

### 2.8 Step 1.8: Tests + CI integration (Day 5)

**Tests:**
```
tests/eval/
├── test_wikidata_client.py
├── test_wikipedia_client.py
├── test_property_alignment.py
├── test_entity_resolution.py
├── test_scorer.py
└── integration/
    └── test_evaluate_wikidata_e2e.py  # End-to-end mock flow
```

**Run tests:**
```bash
pytest tests/eval/ -v
```

**CI:** `.github/workflows/wikidata-poc.yml` (temporary; runs on push to `main`)
```yaml
name: Wikidata PoC Evaluation
on:
  workflow_dispatch:  # Manual trigger only during PoC
  schedule:
    - cron: '0 3 * * 0'  # Weekly Sunday 3am

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -e .[eval]
      - name: Run PoC evaluation (10-article smoke test)
        run: |
          riverbank evaluate-wikidata \
            --dataset examples/golden/wikidata-benchmark-poc.yaml \
            --profile wikidata-eval-v1 \
            --output eval/results/latest.json \
            --sample 10  # 10 articles keeps CI under 10 min
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: wikidata-poc-results
          path: eval/results/
```

**Phase 1 exit criteria:**
- ✅ All 7 modules implemented + tested (wikipedia_client, wikidata_client, property_alignment, entity_resolution, scorer, models, cache)
- ✅ 50-article PoC evaluation runs end-to-end (10-article CI smoke test passes)
- ✅ Precision > 0.75, Recall > 0.50 on PoC set (expected baseline)
- ✅ Manual review of 10 results confirms alignment logic is working
- ✅ JSON output schema finalized

---

## 3. Phase 2: Full Benchmark Dataset (Weeks 2–3)

**Goal:** Scale to 1,000 articles, finalize property alignment (50+ properties), CI integration.

### 3.1 Step 2.1: Expand property alignment table

- Identify properties missing from PoC by analyzing failures
- Add ~20 more Wikidata P-ids based on article coverage
- Update `examples/property-alignment-v1.yaml` to 50+ properties
- Document any unmappable properties

### 3.2 Step 2.2: Build full 1,000-article dataset

**File:** `eval/wikidata-benchmark-1k.yaml`

```yaml
version: 1
dataset_name: "wikidata-benchmark-1k"
stratified_sampling:
  biography_living: 200
  biography_historical: 200
  organization: 200
  geographic: 150
  creative_works: 100
  scientific_concepts: 100
  events: 50
articles:
  - title: "Albert Einstein"
    qid: Q937
    domain: "biography_historical"
  # ... 999 more
```

**Curation strategy:**
- For each domain, query Wikidata for entities with:
  - High statement count (≥ 20 statements)
  - Corresponding Wikipedia article in English
  - Recent edits (article maintained by active editors)
- Manually review first 5 per domain to ensure quality

**Dataset curation SPARQL** (run once; output drives `wikidata-benchmark-1k.yaml`):
```sparql
# Example: biography_historical — 200 entities
SELECT DISTINCT ?item ?itemLabel ?article ?statementCount
WHERE {
  # Instance of: human
  ?item wdt:P31 wd:Q5 .
  
  # Has English Wikipedia sitelink
  ?article schema:about ?item ;
    schema:isPartOf <https://en.wikipedia.org/> .
  
  # Has birth date (historical = born before 1970)
  ?item wdt:P569 ?born .
  FILTER(YEAR(?born) < 1970)
  
  # Count statements to ensure data richness
  {
    SELECT ?item (COUNT(*) AS ?statementCount)
    WHERE { ?item ?p ?o . FILTER(STRSTARTS(STR(?p), STR(wdt:))) }
    GROUP BY ?item
    HAVING(COUNT(*) >= 20)
  }
  
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY DESC(?statementCount)
LIMIT 250  # Over-select; manually prune to 200
```
Adapt the `wdt:P31` / `FILTER` clause for each domain (org, geo, works, etc.).

### 3.3 Step 2.3: Optimize entity resolution for scale

- Cache intermediate results (Wikidata item fetches) in `ResolutionCache`
- Implement batch SPARQL queries (up to 100 Q-ids per VALUES clause) to minimize
  round-trips to query.wikidata.org
- Add `rich` progress bar for long-running evaluations
- Implement `--parallel N` using `asyncio.gather` over coroutines:
  - Wikipedia fetch and ingest pipeline: `asyncio` with `aiohttp`
  - Wikidata SPARQL: `asyncio` with `aiohttp` (same session, connection pooling)
  - Scoring: CPU-bound but fast; run synchronously per article
  - Default `N=8`; reduce to `N=4` in CI to avoid Wikidata rate limits
- Wikidata rate limit: max ~200 req/sec; with N=8 and ~3 SPARQL queries/article,
  peak rate is ~24 req/sec — well within limit

### 3.4 Step 2.4: Full evaluation run + reporting

```bash
riverbank evaluate-wikidata \
  --dataset eval/wikidata-benchmark-1k.yaml \
  --profile wikidata-eval-v1 \
  --output eval/results/v0.15.0-baseline.json \
  --parallel 8 \
  --verbose
```

**Output JSON schema:**
```json
{
  "run_metadata": {
    "date": "2026-05-14T00:00:00Z",
    "riverbank_version": "v0.15.0",
    "dataset": "wikidata-benchmark-1k",
    "profile": "wikidata-eval-v1",
    "articles_evaluated": 1000,
    "duration_seconds": 3600,
    "llm_model": "gpt-4o-mini",
    "total_llm_cost_usd": 42.50
  },
  "aggregate": {
    "precision": 0.87,
    "recall": 0.63,
    "f1": 0.73,
    "confidence_calibration_pearson_r": 0.84,
    "novel_discovery_rate": 0.58,
    "false_positive_rate": 0.08,
    "total_riverbank_triples": 28450,
    "total_wikidata_statements": 41200
  },
  "by_domain": {
    "biography_living": {
      "articles": 200,
      "precision": 0.91,
      "recall": 0.72,
      "f1": 0.80,
      "novel_discovery_rate": 0.62
    },
    "biography_historical": {...},
    "organization": {...},
    // ... 4 more domains
  },
  "by_property": {
    "P31": {"precision": 0.99, "recall": 0.98, "count": 850},
    "P106": {"precision": 0.88, "recall": 0.65, "count": 320},
    // ... top 20 properties
  },
  "calibration_curve": {
    "0.0-0.25": {"count": 120, "observed_accuracy": 0.38},
    "0.25-0.5": {"count": 450, "observed_accuracy": 0.62},
    "0.5-0.75": {"count": 1200, "observed_accuracy": 0.82},
    "0.75-1.0": {"count": 2150, "observed_accuracy": 0.94}
  },
  "article_results": [
    {
      "article_title": "Elon Musk",
      "qid": "Q317521",
      "precision": 0.92,
      "recall": 0.75,
      "f1": 0.83,
      "novel_discovery_rate": 0.55,
      "triples_extracted": 28,
      "triples_matched": 21
    },
    // ... 999 more
  ]
}
```

**Compute additional metrics:**
- Pearson correlation between riverbank confidence scores and actual accuracy
- Per-property recall gaps (identify weak spots)
- Novel discovery sampling (manually verify 200 unmatched triples)

### 3.5 Step 2.5: Documentation + profile example

**File:** `examples/profiles/wikidata-eval-v1.yaml`

```yaml
name: "wikidata-eval-v1"
description: "Profile for evaluating riverbank against Wikidata benchmark"

run_mode_sequence: ["full"]

# Standard riverbank extraction config
extraction_strategy:
  mode: "permissive"
  # ... standard config

# Evaluation-specific config (for future use)
evaluation:
  wikidata_benchmark: true
  novel_discovery_sampling_rate: 0.10  # Sample 10% for manual review
```

**Phase 2 exit criteria:**
- ✅ 1,000-article dataset curated and validated
- ✅ Full evaluation completes in < 2 hours
- ✅ Precision ≥ 0.85, Recall ≥ 0.60, F1 ≥ 0.70 (targets met)
- ✅ Calibration curve shows Pearson ρ ≥ 0.80
- ✅ JSON schema finalized; documentation published

---

## 4. Phase 3: CI Integration (Week 4)

**Goal:** Automate evaluation; store historical results; integrate with existing CI.

### 4.1 Step 3.1: Create evaluation threshold checker

**File:** `eval/check_thresholds.py`

```python
#!/usr/bin/env python3
"""
Check that evaluation results meet thresholds.
Exit 0 if all metrics pass; exit 1 if any fail.
Used in GitHub Actions workflow.
"""

import json
import sys
from pathlib import Path

# Metrics where HIGHER is better (must be >= threshold)
MIN_THRESHOLDS = {
    "precision": 0.85,
    "recall": 0.60,
    "f1": 0.70,
    "confidence_calibration_pearson_r": 0.80,
    "novel_discovery_rate": 0.50,
}

# Metrics where LOWER is better (must be <= threshold)
MAX_THRESHOLDS = {
    "false_positive_rate": 0.10,
}

def check_thresholds(results_json: Path) -> bool:
    with open(results_json) as f:
        results = json.load(f)
    
    agg = results["aggregate"]
    passed = True
    
    for metric, threshold in MIN_THRESHOLDS.items():
        actual = agg.get(metric)
        if actual is None:
            print(f"❌ Missing metric: {metric}")
            passed = False
        elif actual < threshold:
            print(f"❌ {metric}: {actual:.3f} < {threshold} (FAIL)")
            passed = False
        else:
            print(f"✅ {metric}: {actual:.3f} >= {threshold} (PASS)")
    
    for metric, threshold in MAX_THRESHOLDS.items():
        actual = agg.get(metric)
        if actual is None:
            print(f"❌ Missing metric: {metric}")
            passed = False
        elif actual > threshold:
            # BUG GUARD: lower FPR is better — fail if above threshold
            print(f"❌ {metric}: {actual:.3f} > {threshold} (FAIL)")
            passed = False
        else:
            print(f"✅ {metric}: {actual:.3f} <= {threshold} (PASS)")
    
    return passed

if __name__ == "__main__":
    results_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval/results/latest.json")
    if check_thresholds(results_file):
        sys.exit(0)
    else:
        sys.exit(1)
```

### 4.2 Step 3.2: Create calibration curve plotter

**File:** `eval/plot_calibration.py`

```python
#!/usr/bin/env python3
"""
Generate calibration curve (confidence bucket vs. observed accuracy).
Output as PNG to eval/results/
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

def plot_calibration(results_json: Path, output_path: Path = None):
    with open(results_json) as f:
        results = json.load(f)
    
    calibration = results["calibration_curve"]
    
    buckets = []
    accuracies = []
    
    for bucket_key in sorted(calibration.keys()):
        bucket_data = calibration[bucket_key]
        # Bucket key is "0.0-0.25", extract midpoint
        start, end = map(float, bucket_key.split("-"))
        midpoint = (start + end) / 2
        
        buckets.append(midpoint)
        accuracies.append(bucket_data["observed_accuracy"])
    
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(buckets, accuracies, "o-", linewidth=2, markersize=8, label="Observed accuracy")
    ax.plot([0, 1], [0, 1], "k--", alpha=0.3, label="Perfect calibration")
    ax.set_xlabel("Predicted confidence")
    ax.set_ylabel("Observed accuracy")
    ax.set_title("Calibration Curve")
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    if output_path is None:
        output_path = Path("eval/results/calibration_curve.png")
    
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Calibration curve saved to {output_path}")

if __name__ == "__main__":
    import sys
    results_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval/results/latest.json")
    plot_calibration(results_file)
```

### 4.3 Step 3.3: Create GitHub Actions workflow

**File:** `.github/workflows/wikidata-evaluation.yml`

```yaml
name: Wikidata Evaluation

on:
  schedule:
    - cron: '0 3 * * 0'  # Weekly Sunday 3am UTC
  workflow_dispatch:     # Manual trigger

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Cache Python packages
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/pyproject.toml') }}
      
      - name: Install dependencies
        run: |
          pip install -e .[eval]
      
      - name: Pre-download models
        run: |
          riverbank download-models
      
      - name: Run full evaluation
        run: |
          # Note: shell date expansion works in 'run' blocks (not in 'name:' field)
          RUN_TIMESTAMP=$(date +%Y%m%d-%H%M%S)
          riverbank evaluate-wikidata \
            --dataset eval/wikidata-benchmark-1k.yaml \
            --profile wikidata-eval-v1 \
            --output eval/results/${RUN_TIMESTAMP}.json \
            --parallel 4  # Reduced for GitHub Actions (vs 8 local)
          # Also write to latest.json for threshold check and subsequent steps
          cp eval/results/${RUN_TIMESTAMP}.json eval/results/latest.json
        timeout-minutes: 120  # 2 hours
      
      - name: Check thresholds
        run: |
          python eval/check_thresholds.py eval/results/latest.json
      
      - name: Plot calibration curve
        run: |
          python eval/plot_calibration.py eval/results/latest.json
      
      - name: Upload results artifact
        uses: actions/upload-artifact@v4
        if: always()
        with:
          # GitHub Actions does NOT expand shell commands in 'name:' field.
          # Use env vars set in a prior step, or a static name.
          name: wikidata-eval-results
          path: eval/results/
          retention-days: 30
      
      - name: Comment on PR (if applicable)
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const results = JSON.parse(fs.readFileSync('eval/results/latest.json'));
            const agg = results.aggregate;
            
            const comment = `
            ## Wikidata Evaluation Results
            - **Precision:** ${agg.precision.toFixed(3)}
            - **Recall:** ${agg.recall.toFixed(3)}
            - **F1:** ${agg.f1.toFixed(3)}
            - **Calibration ρ:** ${agg.confidence_calibration_pearson_r.toFixed(3)}
            - **Novel Discovery Rate:** ${agg.novel_discovery_rate.toFixed(3)}
            `;
            
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: comment
            });
```

### 4.4 Step 3.4: Git configuration for result tracking

Add to `.gitignore`:
```
eval/results/*.json
eval/results/*.png
eval/.article_cache/
.riverbank/article_cache/
```

Create `.github/workflows/store-results.yml` (store results in separate branch):
```yaml
name: Store Evaluation Results

on:
  workflow_run:
    workflows: ["Wikidata Evaluation"]
    types: [completed]

jobs:
  store:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: evaluation-results
      
      - name: Download artifacts
        uses: actions/download-artifact@v4
      
      - name: Commit and push results
        run: |
          git config user.email "actions@github.com"
          git config user.name "GitHub Actions"
          
          # Store results with date-based naming
          mkdir -p results/$(date +%Y/%m)
          cp wikidata-eval-results-*/*.json results/$(date +%Y/%m/%d-%H%M%S).json
          
          git add results/
          git commit -m "eval: $(date +%Y-%m-%d) wikidata evaluation results"
          git push
```

**Phase 3 exit criteria:**
- ✅ CI workflow runs weekly; produces JSON + calibration curve
- ✅ Threshold checker integrated
- ✅ Results artifact uploaded to GitHub
- ✅ Evaluation results stored in `evaluation-results` branch
- ✅ Manual evaluation via `riverbank evaluate-wikidata --article "Marie Curie"` works end-to-end

---

## 5. Phase 4: Analysis & Iteration (Ongoing)

**Goal:** Close feedback loop from evaluation to extraction improvement.

### 5.1 Step 4.1: Failure mode analysis

**File:** `eval/analyze_failures.py`

```python
#!/usr/bin/env python3
"""
Analyze false positives and false negatives from evaluation results.
Identify per-property recall gaps for v0.15.1.
"""

import json
from pathlib import Path
from collections import defaultdict

def analyze_failures(results_json: Path):
    with open(results_json) as f:
        results = json.load(f)
    
    by_property: dict[str, dict] = defaultdict(lambda: {"fp": 0, "fn": 0, "tp": 0})
    false_positives: list[dict] = []  # For novel discovery sampling
    false_negatives: list[dict] = []  # For prompt improvement
    
    # article_results contains per-article triple_matches from the scorer
    for article in results["article_results"]:
        for match in article.get("triple_matches", []):
            pid = match.get("wikidata_property_id", "unknown")
            
            if match["match_type"] == "exact":
                by_property[pid]["tp"] += 1
            elif match["match_type"] == "no_match" and match.get("source") == "riverbank":
                # Riverbank extracted it; Wikidata doesn't have it → FP or novel
                by_property[pid]["fp"] += 1
                false_positives.append({"article": article["article_title"], "triple": match["riverbank_triple"]})
            elif match["match_type"] == "no_match" and match.get("source") == "wikidata":
                # Wikidata has it; riverbank missed it → FN
                by_property[pid]["fn"] += 1
                false_negatives.append({"article": article["article_title"], "statement": match["wikidata_statement"]})
    
    # Identify properties with recall < 0.5
    weak_properties = [
        (pid, metrics)
        for pid, metrics in by_property.items()
        if (metrics["tp"] + metrics["fn"]) > 0
        and metrics["tp"] / (metrics["tp"] + metrics["fn"]) < 0.5
    ]
    
    print("Properties with recall < 50%:")
    for pid, metrics in sorted(weak_properties, key=lambda x: x[1]["fn"], reverse=True):
        recall = metrics["tp"] / (metrics["tp"] + metrics["fn"])
        print(f"  {pid}: {recall:.1%} ({metrics['fn']} missed statements)")
    
    # Sample FPs for novel discovery annotation
    import random
    sample_size = min(200, len(false_positives))
    sample = random.sample(false_positives, sample_size)
    sample_path = results_json.parent / "novel_discovery_sample.json"
    with open(sample_path, "w") as f:
        json.dump(sample, f, indent=2)
    print(f"\nNovel discovery sample ({sample_size} triples) → {sample_path}")
    print(f"Total false negatives: {sum(m['fn'] for m in by_property.values())}")
    print(f"Total unmatched riverbank triples: {len(false_positives)}")
```

### 5.2 Step 4.2: Novel discovery validation

Implement sampling workflow:
1. Sample 200 unmatched riverbank triples
2. Create Label Studio task: "Is this triple correct?"
3. Manually annotate (30 min work)
4. Compute true novel discovery rate

### 5.3 Step 4.3: Extraction prompt tuning (v0.15.1)

Based on v0.15.0 results, update extraction prompts for v0.15.1:
- Add few-shot examples from high-recall properties (P31, P106)
- Add anti-examples from low-recall properties (P625, P1082)
- Tune confidence thresholds based on calibration curve

---

## 6. Testing Strategy

### 6.1 Unit tests (Phase 1)

```bash
pytest tests/eval/ -v --cov=src/riverbank/eval
```

Target: ≥ 90% coverage of core modules

### 6.2 Integration tests (Phase 2)

**Mock evaluation pipeline end-to-end:**
- Load 5 sample articles from `examples/golden/`
- Mock Wikipedia and Wikidata clients
- Run full evaluation; verify JSON schema
- Test parallelization with `--parallel 4`

### 6.3 Performance tests (Phase 3)

- Benchmark: 1,000 articles → ≤ 2 hours with `--parallel 8`
- Memory usage: ≤ 4GB peak
- Cache hit rate: ≥ 95% on repeated runs

### 6.4 E2E tests (Phase 4, optional)

Run on staging:
- Live Wikipedia API calls (10 articles)
- Live Wikidata SPARQL queries
- Compare results to golden dataset

---

## 7. Rollout and Handoff

### 7.1 Branch strategy

```
feat/wikidata-eval-poc     →  PR into main after Phase 1 (PoC complete)
feat/wikidata-eval-beta    →  PR into main after Phase 2 (full dataset)
feat/wikidata-eval-ci      →  PR into main after Phase 3 (CI + threshold checks)
```

Each PR requires:
- All unit tests pass (`pytest tests/eval/`)
- Phase exit criteria met (see §7.2)
- Manual sign-off on evaluation output sample

### 7.2 Acceptance criteria

**Phase 1 acceptance:**
- [ ] 7 modules complete + unit tested (wikipedia_client, wikidata_client,
  property_alignment, entity_resolution, scorer, models, cache)
- [ ] 50-article PoC runs end-to-end
- [ ] Manual validation of 10 results
- [ ] PR with full test coverage

**Phase 2:**
- [ ] 1,000-article dataset curated
- [ ] Precision ≥ 0.85, Recall ≥ 0.60, F1 ≥ 0.70
- [ ] Per-domain/per-property breakdowns published
- [ ] Property alignment table with 50+ entries

**Phase 3:**
- [ ] CI workflow integrated and passing
- [ ] Threshold checker functional
- [ ] Results stored in evaluation-results branch

**Phase 4:**
- [ ] Failure mode analysis published
- [ ] v0.15.1 roadmap updated based on learnings
- [ ] Novel discovery sampling complete

### 7.3 Documentation

Create `docs/evaluation/wikidata-framework.md`:
- Overview of benchmark dataset
- How to run single-article vs. batch evaluation
- Interpreting results JSON
- Extending property alignment table
- Contributing novel discoveries back to Wikidata (future)

---

## 8. Dependencies Summary

**New packages (add to `pyproject.toml` under `[eval]` extra):**
```
requests>=2.31.0        # MediaWiki API + Wikidata SPARQL (sync, for simple calls)
aiohttp>=3.9.0          # Async HTTP for parallel Wikipedia/Wikidata batches
html2text>=2024.2.26    # Wikipedia HTML → Markdown conversion
rapidfuzz>=3.0.0        # Fuzzy string matching for entity resolution
numpy>=1.24.0           # Pearson ρ, calibration buckets
matplotlib>=3.7.0       # Calibration curve PNG output
rich>=13.0.0            # Progress bars for batch evaluation
```

**Existing packages (no new deps needed):**
```
rdflib>=7.0.0           # Already in riverbank
pydantic>=2.0.0         # Already in riverbank
```

**NOT required (previously listed by mistake):**
```
scikit-learn            # numpy.corrcoef covers all needed statistics
```

---

## 9. Risk Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Wikipedia API rate limits | PoC stalls | Implement exponential backoff; cache aggressively; batch requests |
| Wikidata SPARQL timeout | Evaluation hangs | Set 60s timeout; retry 3x; fall back to dumps if endpoint down |
| Low initial precision (<0.70) | Project at risk | Phase 1 designed for early detection; abort if P < 0.70 after manual audit |
| Alignment table errors inflate FP/FN | Misleading metrics | Manual audit of top 20 properties; fuzzy fallback for unmapped predicates |
| Memory exhaustion on 1,000 articles | CI failure | Stream results to JSON; clear caches between articles; profile peak memory |
| LLM cost explosion | Budget pressure | Phase 1 uses small 10-article set; sample-based smoke tests in CI |

---

## 10. Success Metrics (Post-Implementation)

✅ **v0.15.0 delivers:**
- Automated extraction quality measurement vs. Wikidata ground truth
- User-friendly CLI for single-article and batch evaluation
- Reproducible benchmark dataset (1,000 articles, 7 domains)
- Detailed per-domain and per-property analytics
- Integration with riverbank's existing extraction pipeline

✅ **v0.15.1 follows with:**
- 5–10% improvement in precision/recall from prompt tuning
- Published evaluation methodology and results in docs
- 200+ validated novel discoveries contributed to project knowledge base

