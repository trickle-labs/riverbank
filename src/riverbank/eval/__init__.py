"""Wikidata Evaluation Framework for riverbank (v0.15.0).

Provides tools to evaluate riverbank's knowledge-graph extraction quality by
comparing compiled triples against Wikidata's curated statements, sourced from
the same Wikipedia articles.

Pipeline
--------
1. **WikipediaClient** — fetches Wikipedia articles as Markdown via MediaWiki
   REST API with local hybrid caching (``.riverbank/article_cache/``).
2. **WikidataClient** — fetches Wikidata statements for an entity via SPARQL,
   excluding external identifiers, media, and interwiki links.
3. **PropertyAlignmentTable** — maps 50+ Wikidata P-ids to riverbank predicate
   patterns (P31 instance-of → rdf:type / pgc:isA, etc.).
4. **EntityResolver** — links riverbank IRIs to Wikidata Q-ids via sitelink
   lookup, label matching, and context disambiguation.
5. **Scorer** — computes precision, recall, F1, confidence calibration (Pearson ρ),
   novel discovery rate, and false positive rate per article.
6. **DatasetEvaluator** — orchestrates batch evaluation over the full 1,000-article
   benchmark dataset and writes per-domain / per-property JSON reports to
   ``eval/results/``.

Usage
-----
::

    from riverbank.eval import WikipediaClient, WikidataClient, Scorer
    from riverbank.eval.property_alignment import PropertyAlignmentTable
    from riverbank.eval.entity_resolution import EntityResolver

    wp = WikipediaClient()
    wd = WikidataClient()
    resolver = EntityResolver(wd)
    scorer = Scorer(PropertyAlignmentTable(), resolver)

    article = wp.fetch_article("Marie Curie")
    wikidata_item = wd.get_item_by_wikipedia_title("Marie Curie")
    score = scorer.score_article("Marie Curie", [], wikidata_item)
    print(f"F1={score.f1:.3f}")

CLI
---
::

    # Single article
    riverbank evaluate-wikidata --article "Marie Curie"

    # Batch over benchmark dataset
    riverbank evaluate-wikidata --dataset eval/wikidata-benchmark-1k.yaml \\
        --profile wikidata-eval-v1 \\
        --output eval/results/latest.json

Results are stored in ``eval/results/`` and never committed to the repository.
"""
from __future__ import annotations

from riverbank.eval.cache import ArticleCache
from riverbank.eval.entity_resolution import EntityResolver
from riverbank.eval.models import (
    ArticleScore,
    CacheMetadata,
    DatasetResult,
    EntityMatch,
    PropertyAlignment,
    ResolutionCache,
    RunMetadata,
    TripleMatch,
    WikidataItem,
    WikidataStatement,
    WikipediaArticle,
)
from riverbank.eval.property_alignment import PropertyAlignmentTable
from riverbank.eval.scorer import DatasetEvaluator, Scorer
from riverbank.eval.wikidata_client import WikidataClient, WikidataUnavailableError
from riverbank.eval.wikipedia_client import WikipediaClient

__all__ = [
    "ArticleCache",
    "ArticleScore",
    "CacheMetadata",
    "DatasetEvaluator",
    "DatasetResult",
    "EntityMatch",
    "EntityResolver",
    "PropertyAlignment",
    "PropertyAlignmentTable",
    "ResolutionCache",
    "RunMetadata",
    "Scorer",
    "TripleMatch",
    "WikidataClient",
    "WikidataItem",
    "WikidataStatement",
    "WikidataUnavailableError",
    "WikipediaArticle",
    "WikipediaClient",
]
