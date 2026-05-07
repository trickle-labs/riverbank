"""Shared dataclasses for the Wikidata evaluation framework (v0.15.0).

All dataclasses live here to avoid circular imports between sub-modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Wikipedia / caching
# ---------------------------------------------------------------------------


@dataclass
class WikipediaArticle:
    """A Wikipedia article fetched via the MediaWiki API."""

    title: str
    url: str
    qid: str  # Wikidata Q-id resolved from sitelinks
    content: str  # Article body as Markdown
    source_wikilinks: list[str]  # [[Wikilinks]] found in the article
    fetch_timestamp: datetime
    cache_path: Path | None = None


@dataclass
class CacheMetadata:
    """Metadata stored alongside cached article Markdown."""

    title: str
    url: str
    qid: str
    fetch_timestamp: datetime
    cache_ttl_days: int
    is_stale: bool = False


# ---------------------------------------------------------------------------
# Wikidata entities & statements
# ---------------------------------------------------------------------------


@dataclass
class WikidataStatement:
    """A single Wikidata statement (subject is always the item being described)."""

    property_id: str  # P31, P106, P569, ...
    property_label: str  # "instance of", "occupation", "date of birth"
    value: str  # Stringified value (Q-id, ISO 8601 date, plain string, etc.)
    value_type: str  # "wikibase-item" | "string" | "quantity" | "time" | "monolingualtext"
    value_label: str | None = None  # Human-readable label when value is a Q-id
    qualifiers: dict[str, list[str]] = field(default_factory=dict)
    rank: str = "normal"  # "normal" | "preferred" | "deprecated"
    references: list[dict] = field(default_factory=list)


@dataclass
class WikidataItem:
    """A Wikidata entity with all its non-excluded statements."""

    qid: str
    label: str
    description: str
    aliases: list[str]
    statements: list[WikidataStatement]


# ---------------------------------------------------------------------------
# Property alignment
# ---------------------------------------------------------------------------


@dataclass
class PropertyAlignment:
    """Mapping from a Wikidata P-id to equivalent riverbank predicate patterns."""

    wikidata_pid: str  # "P31"
    wikidata_label: str  # "instance of"
    riverbank_predicates: list[str]  # ["rdf:type", "pgc:isA"]
    value_mapping: dict[str, str] = field(default_factory=dict)  # Q-id → riverbank IRI
    alignment_confidence: float = 1.0  # 0.0–1.0
    notes: str = ""


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------


@dataclass
class EntityMatch:
    """Result of resolving a riverbank IRI to a Wikidata Q-id."""

    riverbank_iri: str
    wikidata_qid: str
    match_type: str  # "sitelink" | "label" | "fuzzy_label" | "context_disambig" | "none"
    confidence: float  # 0.0–1.0
    explanation: str = ""


@dataclass
class ResolutionCache:
    """In-memory cache of IRI → EntityMatch to avoid redundant Wikidata lookups."""

    _cache: dict[str, EntityMatch] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, iri: str) -> EntityMatch | None:
        result = self._cache.get(iri)
        if result is not None:
            self.hits += 1
        else:
            self.misses += 1
        return result

    def put(self, iri: str, match: EntityMatch) -> None:
        self._cache[iri] = match

    def __len__(self) -> int:
        return len(self._cache)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class TripleMatch:
    """Result of matching a single riverbank triple against Wikidata statements."""

    riverbank_triple: tuple[str, str, str]  # (subject, predicate, object)
    riverbank_confidence: float
    wikidata_statement: WikidataStatement | None
    match_type: str  # "exact" | "partial" | "no_match"
    match_score: float  # 0.0–1.0
    evidence: str = ""


@dataclass
class ArticleScore:
    """Precision/recall/F1 score for a single Wikipedia article evaluation."""

    article_title: str
    wikidata_qid: str
    riverbank_triples: int
    wikidata_statements: int
    triple_matches: list[TripleMatch]

    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    novel_discoveries: int = 0  # Unmatched riverbank triples (potentially correct)

    # Confidence calibration: bucket → (count, observed_accuracy)
    confidence_buckets: dict[str, tuple[int, float]] = field(default_factory=dict)

    domain: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "article_title": self.article_title,
            "wikidata_qid": self.wikidata_qid,
            "domain": self.domain,
            "riverbank_triples": self.riverbank_triples,
            "wikidata_statements": self.wikidata_statements,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "novel_discoveries": self.novel_discoveries,
        }


# ---------------------------------------------------------------------------
# Dataset evaluation
# ---------------------------------------------------------------------------


@dataclass
class RunMetadata:
    """Metadata about a full dataset evaluation run."""

    date: str
    riverbank_version: str
    dataset: str
    profile: str
    articles_evaluated: int = 0
    duration_seconds: float = 0.0
    llm_model: str = ""
    total_llm_cost_usd: float = 0.0


@dataclass
class DatasetResult:
    """Aggregated results for a full benchmark dataset evaluation."""

    run_metadata: RunMetadata
    article_scores: list[ArticleScore] = field(default_factory=list)

    # Aggregate metrics (populated by DatasetEvaluator.aggregate())
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    confidence_calibration_pearson_r: float = 0.0
    novel_discovery_rate: float = 0.0
    false_positive_rate: float = 0.0
    total_riverbank_triples: int = 0
    total_wikidata_statements: int = 0

    by_domain: dict[str, dict] = field(default_factory=dict)
    by_property: dict[str, dict] = field(default_factory=dict)
    calibration_curve: dict[str, dict] = field(default_factory=dict)
