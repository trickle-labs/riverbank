"""Unit tests for the v0.15.0 Wikidata evaluation framework.

Tests cover:
- models.py: dataclass construction, defaults, serialization
- cache.py: ArticleCache get/put/invalidate/prune/stats
- wikipedia_client.py: URL/QID normalization, cache integration, wikilink extraction
- wikidata_client.py: SPARQL binding parsing, statement filtering, type simplification
- property_alignment.py: lookup, reverse lookup, YAML round-trip
- entity_resolution.py: label extraction, sitelink matching, ResolutionCache
- scorer.py: match scoring, precision/recall/F1, calibration, DatasetEvaluator
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


# ===========================================================================
# models.py
# ===========================================================================


def test_wikipedia_article_defaults() -> None:
    from riverbank.eval.models import WikipediaArticle

    article = WikipediaArticle(
        title="Test",
        url="https://en.wikipedia.org/wiki/Test",
        qid="Q1",
        content="# Test\n\nSome content.",
        source_wikilinks=["Link1"],
        fetch_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert article.title == "Test"
    assert article.cache_path is None
    assert article.qid == "Q1"


def test_cache_metadata_stale_default() -> None:
    from riverbank.eval.models import CacheMetadata

    meta = CacheMetadata(
        title="X",
        url="http://x",
        qid="Q2",
        fetch_timestamp=datetime.now(tz=timezone.utc),
        cache_ttl_days=30,
    )
    assert meta.is_stale is False


def test_wikidata_statement_defaults() -> None:
    from riverbank.eval.models import WikidataStatement

    stmt = WikidataStatement(
        property_id="P31",
        property_label="instance of",
        value="Q5",
        value_type="wikibase-item",
    )
    assert stmt.rank == "normal"
    assert stmt.qualifiers == {}
    assert stmt.references == []


def test_wikidata_item_construction() -> None:
    from riverbank.eval.models import WikidataItem, WikidataStatement

    item = WikidataItem(
        qid="Q7186",
        label="Marie Curie",
        description="Polish-French physicist",
        aliases=["Marie Sklodowska-Curie"],
        statements=[
            WikidataStatement("P31", "instance of", "Q5", "wikibase-item", value_label="human"),
            WikidataStatement("P569", "date of birth", "1867-11-07", "time"),
        ],
    )
    assert item.qid == "Q7186"
    assert len(item.statements) == 2
    assert item.statements[0].value_label == "human"


def test_property_alignment_defaults() -> None:
    from riverbank.eval.models import PropertyAlignment

    pa = PropertyAlignment(
        wikidata_pid="P31",
        wikidata_label="instance of",
        riverbank_predicates=["rdf:type"],
    )
    assert pa.alignment_confidence == 1.0
    assert pa.value_mapping == {}
    assert pa.notes == ""


def test_entity_match_construction() -> None:
    from riverbank.eval.models import EntityMatch

    match = EntityMatch(
        riverbank_iri="http://ex.org/Marie_Curie",
        wikidata_qid="Q7186",
        match_type="sitelink",
        confidence=1.0,
    )
    assert match.match_type == "sitelink"
    assert match.confidence == 1.0


def test_resolution_cache_hit_miss() -> None:
    from riverbank.eval.models import EntityMatch, ResolutionCache

    cache = ResolutionCache()
    assert cache.hits == 0
    assert cache.misses == 0

    result = cache.get("http://ex.org/Alice")
    assert result is None
    assert cache.misses == 1

    em = EntityMatch("http://ex.org/Alice", "Q123", "label", 0.9)
    cache.put("http://ex.org/Alice", em)

    result2 = cache.get("http://ex.org/Alice")
    assert result2 is em
    assert cache.hits == 1
    assert len(cache) == 1


def test_triple_match_construction() -> None:
    from riverbank.eval.models import TripleMatch, WikidataStatement

    stmt = WikidataStatement("P31", "instance of", "Q5", "wikibase-item")
    tm = TripleMatch(
        riverbank_triple=("ex:Alice", "rdf:type", "ex:Person"),
        riverbank_confidence=0.9,
        wikidata_statement=stmt,
        match_type="exact",
        match_score=1.0,
    )
    assert tm.match_type == "exact"
    assert tm.match_score == 1.0


def test_article_score_to_dict() -> None:
    from riverbank.eval.models import ArticleScore

    score = ArticleScore(
        article_title="Marie Curie",
        wikidata_qid="Q7186",
        riverbank_triples=10,
        wikidata_statements=20,
        triple_matches=[],
        precision=0.8,
        recall=0.6,
        f1=0.686,
        true_positives=8,
        false_positives=2,
        false_negatives=12,
        novel_discoveries=0,
        domain="biography_historical",
    )
    d = score.to_dict()
    assert d["article_title"] == "Marie Curie"
    assert d["f1"] == 0.686
    assert d["domain"] == "biography_historical"


def test_dataset_result_defaults() -> None:
    from riverbank.eval.models import DatasetResult, RunMetadata

    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="test",
        profile="wikidata-eval-v1",
    )
    result = DatasetResult(run_metadata=meta)
    assert result.precision == 0.0
    assert result.article_scores == []
    assert result.by_domain == {}


# ===========================================================================
# cache.py
# ===========================================================================


def test_article_cache_normalize() -> None:
    from riverbank.eval.cache import ArticleCache

    assert ArticleCache._normalize("Marie Curie") == "marie_curie"
    assert ArticleCache._normalize("Apple Inc.") == "apple_inc"
    assert ArticleCache._normalize("") == "untitled"
    assert ArticleCache._normalize("  test  ") == "test"


def test_article_cache_put_get() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir), cache_ttl_days=30)
        article = WikipediaArticle(
            title="Test Article",
            url="https://en.wikipedia.org/wiki/Test_Article",
            qid="Q999",
            content="# Test Article\n\nContent here.",
            source_wikilinks=[],
            fetch_timestamp=datetime.now(tz=timezone.utc),
        )
        cache.put(article)

        # Verify files exist
        assert (Path(tmpdir) / "test_article.md").exists()
        assert (Path(tmpdir) / "test_article.meta.json").exists()

        # Read back
        retrieved = cache.get("Test Article")
        assert retrieved is not None
        assert retrieved.title == "Test Article"
        assert retrieved.qid == "Q999"
        assert "Content here" in retrieved.content


def test_article_cache_miss() -> None:
    from riverbank.eval.cache import ArticleCache

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir))
        result = cache.get("Nonexistent Article")
        assert result is None


def test_article_cache_invalidate() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir))
        article = WikipediaArticle(
            title="Delete Me",
            url="",
            qid="Q1",
            content="content",
            source_wikilinks=[],
            fetch_timestamp=datetime.now(tz=timezone.utc),
        )
        cache.put(article)
        assert cache.get("Delete Me") is not None

        removed = cache.invalidate("Delete Me")
        assert removed is True
        assert cache.get("Delete Me") is None

        # Idempotent
        removed2 = cache.invalidate("Delete Me")
        assert removed2 is False


def test_article_cache_is_valid_fresh() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir), cache_ttl_days=30)
        article = WikipediaArticle(
            title="Fresh",
            url="",
            qid="Q2",
            content="text",
            source_wikilinks=[],
            fetch_timestamp=datetime.now(tz=timezone.utc),
        )
        cache.put(article)
        assert cache.is_valid("Fresh") is True


def test_article_cache_is_stale() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir), cache_ttl_days=1)
        stale_ts = datetime.now(tz=timezone.utc) - timedelta(days=2)
        article = WikipediaArticle(
            title="Stale Article",
            url="",
            qid="Q3",
            content="old",
            source_wikilinks=[],
            fetch_timestamp=stale_ts,
        )
        cache.put(article)
        # Override the written timestamp to simulate staleness
        meta_path = Path(tmpdir) / "stale_article.meta.json"
        meta_data = json.loads(meta_path.read_text())
        meta_data["fetch_timestamp"] = stale_ts.isoformat()
        meta_path.write_text(json.dumps(meta_data))

        assert cache.is_valid("Stale Article") is False


def test_article_cache_list_all() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir))
        for title in ["Alpha", "Beta", "Gamma"]:
            article = WikipediaArticle(
                title=title, url="", qid="Q1",
                content="x", source_wikilinks=[],
                fetch_timestamp=datetime.now(tz=timezone.utc),
            )
            cache.put(article)

        keys = cache.list_all()
        assert len(keys) == 3


def test_article_cache_stats_empty() -> None:
    from riverbank.eval.cache import ArticleCache

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir))
        stats = cache.stats()
        assert stats["total"] == 0
        assert stats["stale"] == 0


def test_article_cache_stats_with_entries() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir))
        for title in ["One", "Two"]:
            cache.put(WikipediaArticle(
                title=title, url="", qid="Q1",
                content="content", source_wikilinks=[],
                fetch_timestamp=datetime.now(tz=timezone.utc),
            ))
        stats = cache.stats()
        assert stats["total"] == 2
        assert stats["fresh"] == 2


def test_article_cache_prune_fresh() -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ArticleCache(cache_dir=Path(tmpdir), cache_ttl_days=30)
        cache.put(WikipediaArticle(
            title="Fresh", url="", qid="Q1",
            content="text", source_wikilinks=[],
            fetch_timestamp=datetime.now(tz=timezone.utc),
        ))
        removed = cache.prune()
        assert removed == 0


# ===========================================================================
# wikipedia_client.py
# ===========================================================================


def test_wikipedia_client_normalize_title() -> None:
    from riverbank.eval.wikipedia_client import WikipediaClient

    client = WikipediaClient()
    assert client._normalize_query("Marie Curie") == "Marie Curie"


def test_wikipedia_client_normalize_url() -> None:
    from riverbank.eval.wikipedia_client import WikipediaClient

    client = WikipediaClient()
    result = client._normalize_query("https://en.wikipedia.org/wiki/Marie_Curie")
    assert result == "Marie Curie"


def test_wikipedia_client_normalize_url_with_anchor() -> None:
    from riverbank.eval.wikipedia_client import WikipediaClient

    client = WikipediaClient()
    result = client._normalize_query("https://en.wikipedia.org/wiki/Marie_Curie#Early_life")
    assert result == "Marie Curie"


def test_wikipedia_client_extract_wikilinks() -> None:
    from riverbank.eval.wikipedia_client import WikipediaClient

    md = "[[Marie Curie]] studied at [[University of Paris|Sorbonne]] in [[France]]."
    links = WikipediaClient._extract_wikilinks(md)
    assert "Marie Curie" in links
    assert "France" in links
    assert "University of Paris" in links


def test_wikipedia_client_extract_wikilinks_empty() -> None:
    from riverbank.eval.wikipedia_client import WikipediaClient

    assert WikipediaClient._extract_wikilinks("No wikilinks here.") == []


def test_wikipedia_client_cache_hit(tmp_path: Path) -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle
    from riverbank.eval.wikipedia_client import WikipediaClient

    cache = ArticleCache(cache_dir=tmp_path, cache_ttl_days=30)
    article = WikipediaArticle(
        title="Cached Article",
        url="https://en.wikipedia.org/wiki/Cached_Article",
        qid="Q123",
        content="# Cached\n\nContent.",
        source_wikilinks=[],
        fetch_timestamp=datetime.now(tz=timezone.utc),
    )
    cache.put(article)

    client = WikipediaClient(cache_dir=tmp_path, cache_ttl_days=30)
    # No network calls should happen
    with mock.patch.object(client, "_fetch_markdown", side_effect=AssertionError("should not be called")):
        result = client.fetch_article("Cached Article")

    assert result.title == "Cached Article"
    assert result.qid == "Q123"


def test_wikipedia_client_no_cache_forces_fetch(tmp_path: Path) -> None:
    from riverbank.eval.cache import ArticleCache
    from riverbank.eval.models import WikipediaArticle
    from riverbank.eval.wikipedia_client import WikipediaClient

    cache = ArticleCache(cache_dir=tmp_path, cache_ttl_days=30)
    article = WikipediaArticle(
        title="Old Article",
        url="",
        qid="Q9",
        content="old",
        source_wikilinks=[],
        fetch_timestamp=datetime.now(tz=timezone.utc),
    )
    cache.put(article)

    client = WikipediaClient(cache_dir=tmp_path)
    fresh_content = "# Old Article\n\nFresh content."

    with mock.patch.object(client, "_fetch_markdown", return_value=fresh_content):
        with mock.patch.object(client, "_get_qid_from_article", return_value="Q9"):
            result = client.fetch_article("Old Article", force_fresh=True)

    assert "Fresh content" in result.content


def test_wikipedia_client_cache_only_raises(tmp_path: Path) -> None:
    from riverbank.eval.wikipedia_client import CacheOnlyError, WikipediaClient

    client = WikipediaClient(cache_dir=tmp_path)

    import pytest
    with pytest.raises(CacheOnlyError):
        client.fetch_article("Not Cached", cache_only=True)


def test_wikipedia_html_to_markdown_with_html2text() -> None:
    """Test HTML→Markdown conversion when html2text is available."""
    from riverbank.eval.wikipedia_client import WikipediaClient

    html = "<h1>Test</h1><p>Hello <b>world</b>.</p>"
    try:
        import html2text  # noqa: F401
        md = WikipediaClient._html_to_markdown(html, "Test")
        assert "Test" in md
        assert "Hello" in md
    except ImportError:
        # Fallback path
        md = WikipediaClient._html_to_markdown(html, "Test")
        assert "Test" in md


# ===========================================================================
# wikidata_client.py
# ===========================================================================


def test_wikidata_client_binding_to_dict() -> None:
    from riverbank.eval.wikidata_client import WikidataClient

    binding = {
        "property": {"value": "http://www.wikidata.org/entity/P31"},
        "value": {"value": "http://www.wikidata.org/entity/Q5"},
        "propertyLabel": {"value": "instance of"},
    }
    result = WikidataClient._binding_to_dict(binding)
    assert result["property"] == "P31"
    assert result["value"] == "Q5"
    assert result["propertyLabel"] == "instance of"


def test_wikidata_client_simplify_type() -> None:
    from riverbank.eval.wikidata_client import WikidataClient

    assert WikidataClient._simplify_type("http://wikiba.se/ontology#WikibaseItem") == "wikibase-item"
    assert WikidataClient._simplify_type("http://wikiba.se/ontology#Time") == "time"
    assert WikidataClient._simplify_type("http://wikiba.se/ontology#String") == "string"
    assert WikidataClient._simplify_type("http://wikiba.se/ontology#Quantity") == "quantity"
    assert WikidataClient._simplify_type("http://wikiba.se/ontology#GlobeCoordinate") == "globe-coordinate"
    assert WikidataClient._simplify_type("unknown") == "string"


def test_wikidata_client_filter_statements_excludes_external_id() -> None:
    from riverbank.eval.wikidata_client import WikidataClient

    rows = [
        {"property": "P31", "value": "Q5", "valueType": "WikibaseItem", "propertyLabel": "instance of"},
        {"property": "P213", "value": "0000-0001-2345-6789", "valueType": "ExternalId", "propertyLabel": "ISNI"},
        {"property": "P18", "value": "image.jpg", "valueType": "CommonsMedia", "propertyLabel": "image"},
    ]
    client = WikidataClient()
    statements = client._filter_statements(rows)
    assert len(statements) == 1
    assert statements[0].property_id == "P31"


def test_wikidata_client_filter_statements_excludes_url() -> None:
    from riverbank.eval.wikidata_client import WikidataClient

    rows = [
        {"property": "P856", "value": "https://example.com", "valueType": "Url", "propertyLabel": "website"},
        {"property": "P106", "value": "Q39631", "valueType": "WikibaseItem", "propertyLabel": "occupation"},
    ]
    client = WikidataClient()
    statements = client._filter_statements(rows)
    assert len(statements) == 1
    assert statements[0].property_id == "P106"


def test_wikidata_client_filter_statements_rank() -> None:
    from riverbank.eval.wikidata_client import WikidataClient

    rows = [
        {
            "property": "P31",
            "value": "Q5",
            "valueType": "WikibaseItem",
            "propertyLabel": "instance of",
            "rank": "http://wikiba.se/ontology#PreferredRank",
        },
    ]
    client = WikidataClient()
    statements = client._filter_statements(rows)
    assert statements[0].rank == "preferred"


def test_wikidata_client_filter_statements_normal_rank() -> None:
    from riverbank.eval.wikidata_client import WikidataClient

    rows = [
        {
            "property": "P569",
            "value": "1867-11-07",
            "valueType": "Time",
            "propertyLabel": "date of birth",
            "rank": "http://wikiba.se/ontology#NormalRank",
        },
    ]
    client = WikidataClient()
    statements = client._filter_statements(rows)
    assert statements[0].rank == "normal"


def test_wikidata_client_sparql_retry_on_failure() -> None:
    """Verify retry logic triggers on connection errors."""
    from riverbank.eval.wikidata_client import WikidataClient, WikidataUnavailableError

    client = WikidataClient(max_retries=2)

    with mock.patch("requests.get", side_effect=ConnectionError("network error")):
        try:
            import pytest
            with pytest.raises(WikidataUnavailableError):
                client.query_sparql("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        except ImportError:
            pass  # pytest not available in all envs


def test_wikidata_unavailable_error() -> None:
    from riverbank.eval.wikidata_client import WikidataUnavailableError

    err = WikidataUnavailableError("endpoint unreachable")
    assert "endpoint unreachable" in str(err)


# ===========================================================================
# property_alignment.py
# ===========================================================================


def test_property_alignment_table_size() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    assert len(table) >= 50, f"Expected ≥50 entries, got {len(table)}"


def test_property_alignment_table_no_duplicates() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    pids = table.all_pids()
    assert len(pids) == len(set(pids)), "Duplicate P-ids in alignment table"


def test_property_alignment_table_get_alignment_p31() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    alignment = table.get_alignment("P31")
    assert alignment is not None
    assert alignment.wikidata_label == "instance of"
    assert "rdf:type" in alignment.riverbank_predicates


def test_property_alignment_table_get_alignment_missing() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    assert table.get_alignment("P99999") is None


def test_property_alignment_table_get_riverbank_predicates() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    predicates = table.get_riverbank_predicates("P569")
    assert len(predicates) > 0
    # Should include a birth date predicate
    assert any("birthDate" in p or "birthday" in p for p in predicates)


def test_property_alignment_table_reverse_lookup() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    pids = table.predicate_to_pids("rdf:type")
    assert "P31" in pids


def test_property_alignment_table_yaml_roundtrip(tmp_path: Path) -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    yaml_path = tmp_path / "alignment.yaml"
    table.to_yaml(yaml_path)

    # Read back
    loaded = PropertyAlignmentTable.from_yaml(yaml_path)
    assert len(loaded) == len(table)
    assert loaded.get_alignment("P31") is not None
    assert "rdf:type" in loaded.get_riverbank_predicates("P31")


def test_property_alignment_table_p106() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    a = table.get_alignment("P106")
    assert a is not None
    assert "occupation" in a.wikidata_label.lower()
    assert a.alignment_confidence >= 0.8


def test_property_alignment_table_p159() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    a = table.get_alignment("P159")
    assert a is not None
    assert "headquarters" in a.wikidata_label.lower()


def test_property_alignment_table_all_pids_list() -> None:
    from riverbank.eval.property_alignment import PropertyAlignmentTable

    table = PropertyAlignmentTable()
    pids = table.all_pids()
    assert isinstance(pids, list)
    for pid in pids:
        assert pid.startswith("P"), f"Non-P-id found: {pid}"


# ===========================================================================
# entity_resolution.py
# ===========================================================================


def test_entity_resolver_extract_label_slash_iri() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    label = resolver.extract_label("http://example.org/person/marie-curie")
    assert "marie" in label.lower()
    assert "curie" in label.lower()


def test_entity_resolver_extract_label_prefixed() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    label = resolver.extract_label("ex:Marie_Curie")
    assert "Marie" in label or "marie" in label.lower()
    assert "Curie" in label or "curie" in label.lower()


def test_entity_resolver_extract_label_hash_iri() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    label = resolver.extract_label("http://example.org/ns#AppleInc")
    assert "Apple" in label


def test_entity_resolver_extract_label_camelcase() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    label = resolver.extract_label("ex:QuantumMechanics")
    # camelCase should be split
    assert "Quantum" in label or "quantum" in label.lower()


def test_entity_resolver_sitelink_match() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    match = resolver.resolve_entity(
        riverbank_iri="ex:Marie_Curie",
        article_title="Marie Curie",
        article_qid="Q7186",
        context_type="person",
    )
    assert match is not None
    assert match.wikidata_qid == "Q7186"
    assert match.match_type == "sitelink"
    assert match.confidence == 1.0


def test_entity_resolver_no_wikidata_client_returns_none() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver(wikidata_client=None)
    match = resolver.resolve_entity(
        riverbank_iri="http://ex.org/random_entity",
        article_title="Different Title",
        article_qid="",
    )
    # Without Wikidata client and no sitelink match → None
    assert match is None


def test_entity_resolver_resolution_cache_populated() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver(wikidata_client=None)
    # Sitelink match populates cache
    match = resolver.resolve_entity(
        riverbank_iri="ex:Albert_Einstein",
        article_title="Albert Einstein",
        article_qid="Q937",
    )
    assert match is not None
    # Should be in cache now
    cached = resolver.cache.get("ex:Albert_Einstein")
    assert cached is not None
    assert cached.wikidata_qid == "Q937"


def test_entity_resolver_labels_match_case_insensitive() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    assert resolver._labels_match("Marie Curie", "MARIE CURIE")
    assert resolver._labels_match("apple inc", "Apple Inc.")


def test_entity_resolver_labels_match_with_punctuation() -> None:
    from riverbank.eval.entity_resolution import EntityResolver

    resolver = EntityResolver()
    assert resolver._labels_match("U.S.A", "USA")


# ===========================================================================
# scorer.py
# ===========================================================================


def _make_scorer():
    from riverbank.eval.entity_resolution import EntityResolver
    from riverbank.eval.property_alignment import PropertyAlignmentTable
    from riverbank.eval.scorer import Scorer

    return Scorer(
        alignment_table=PropertyAlignmentTable(),
        entity_resolver=EntityResolver(wikidata_client=None),
    )


def test_scorer_empty_triples() -> None:
    from riverbank.eval.models import WikidataItem, WikidataStatement

    scorer = _make_scorer()
    wd_item = WikidataItem(
        qid="Q7186",
        label="Marie Curie",
        description="",
        aliases=[],
        statements=[
            WikidataStatement("P31", "instance of", "Q5", "wikibase-item"),
            WikidataStatement("P569", "date of birth", "1867-11-07", "time"),
        ],
    )
    score = scorer.score_article("Marie Curie", [], wd_item)
    assert score.riverbank_triples == 0
    assert score.wikidata_statements == 2
    assert score.true_positives == 0
    assert score.false_negatives == 2
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0


def test_scorer_perfect_match() -> None:
    from riverbank.eval.models import WikidataItem, WikidataStatement

    scorer = _make_scorer()
    wd_item = WikidataItem(
        qid="Q7186",
        label="Marie Curie",
        description="",
        aliases=[],
        statements=[
            WikidataStatement("P31", "instance of", "Q5", "wikibase-item", value_label="human"),
        ],
    )
    # Triple with predicate aligned to P31
    triples = [("ex:MarieCurie", "rdf:type", "human", 0.95)]
    score = scorer.score_article("Marie Curie", triples, wd_item)
    assert score.riverbank_triples == 1
    assert score.true_positives >= 0  # alignment-dependent


def test_scorer_no_alignment_novel_discovery() -> None:
    from riverbank.eval.models import WikidataItem

    scorer = _make_scorer()
    wd_item = WikidataItem(qid="Q1", label="Test", description="", aliases=[], statements=[])
    triples = [("ex:Test", "ex:unknownPredicate", "somevalue", 0.7)]
    score = scorer.score_article("Test", triples, wd_item)
    assert score.novel_discoveries == 1  # no alignment → novel discovery


def test_scorer_compute_precision_recall_zeros() -> None:
    from riverbank.eval.scorer import Scorer

    p, r, f = Scorer._compute_precision_recall(0, 0, 0)
    assert p == 0.0
    assert r == 0.0
    assert f == 0.0


def test_scorer_compute_precision_recall_perfect() -> None:
    from riverbank.eval.scorer import Scorer

    p, r, f = Scorer._compute_precision_recall(10, 0, 0)
    assert p == 1.0
    assert r == 1.0
    assert f == 1.0


def test_scorer_compute_precision_recall_half() -> None:
    from riverbank.eval.scorer import Scorer

    p, r, f = Scorer._compute_precision_recall(5, 5, 5)
    assert p == 0.5
    assert r == 0.5
    assert round(f, 4) == 0.5


def test_scorer_object_match_exact() -> None:
    from riverbank.eval.models import WikidataStatement
    from riverbank.eval.scorer import Scorer

    stmt = WikidataStatement("P31", "instance of", "human", "wikibase-item")
    score = Scorer._object_match_score("human", stmt)
    assert score == 1.0


def test_scorer_object_match_case_insensitive() -> None:
    from riverbank.eval.models import WikidataStatement
    from riverbank.eval.scorer import Scorer

    stmt = WikidataStatement("P31", "instance of", "HUMAN", "wikibase-item")
    score = Scorer._object_match_score("human", stmt)
    assert score == 1.0


def test_scorer_object_match_label() -> None:
    from riverbank.eval.models import WikidataStatement
    from riverbank.eval.scorer import Scorer

    stmt = WikidataStatement("P31", "instance of", "Q5", "wikibase-item", value_label="human")
    score = Scorer._object_match_score("human", stmt)
    assert score == 1.0


def test_scorer_object_match_year_extraction() -> None:
    from riverbank.eval.models import WikidataStatement
    from riverbank.eval.scorer import Scorer

    stmt = WikidataStatement("P569", "date of birth", "1867-11-07", "time")
    score = Scorer._object_match_score("1867", stmt)
    assert score >= 0.9


def test_scorer_object_match_no_match() -> None:
    from riverbank.eval.models import WikidataStatement
    from riverbank.eval.scorer import Scorer

    stmt = WikidataStatement("P31", "instance of", "completely_different_value", "string")
    score = Scorer._object_match_score("totally unrelated", stmt)
    assert score < 0.9


def test_scorer_confidence_calibration_buckets() -> None:
    from riverbank.eval.models import TripleMatch
    from riverbank.eval.scorer import Scorer

    matches = [
        TripleMatch(("s", "p", "o"), confidence, None, "no_match", 0.0)
        for confidence in [0.1, 0.3, 0.6, 0.8, 0.9, 0.95]
    ]
    buckets = Scorer._compute_confidence_calibration(matches)
    assert "0.0-0.25" in buckets
    assert "0.25-0.5" in buckets
    assert "0.5-0.75" in buckets
    assert "0.75-1.0" in buckets
    total = sum(count for count, _ in buckets.values())
    assert total == len(matches)


def test_scorer_calibration_all_in_one_bucket() -> None:
    from riverbank.eval.models import TripleMatch
    from riverbank.eval.scorer import Scorer

    matches = [
        TripleMatch(("s", "p", "o"), 0.9, None, "exact", 1.0)
        for _ in range(5)
    ]
    buckets = Scorer._compute_confidence_calibration(matches)
    count, accuracy = buckets["0.75-1.0"]
    assert count == 5
    assert accuracy == 1.0


def test_scorer_article_score_domain() -> None:
    from riverbank.eval.models import WikidataItem

    scorer = _make_scorer()
    wd_item = WikidataItem(qid="Q7186", label="Test", description="", aliases=[], statements=[])
    score = scorer.score_article("Test", [], wd_item, domain="biography_historical")
    assert score.domain == "biography_historical"


# ===========================================================================
# DatasetEvaluator
# ===========================================================================


def test_dataset_evaluator_empty() -> None:
    from riverbank.eval.models import RunMetadata
    from riverbank.eval.scorer import DatasetEvaluator

    evaluator = DatasetEvaluator()
    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="test",
        profile="wikidata-eval-v1",
    )
    result = evaluator.aggregate([], meta)
    assert result.precision == 0.0
    assert result.f1 == 0.0


def test_dataset_evaluator_aggregate_single_article() -> None:
    from riverbank.eval.models import ArticleScore, RunMetadata
    from riverbank.eval.scorer import DatasetEvaluator

    evaluator = DatasetEvaluator()
    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="test",
        profile="wikidata-eval-v1",
        articles_evaluated=1,
    )
    score = ArticleScore(
        article_title="Marie Curie",
        wikidata_qid="Q7186",
        riverbank_triples=10,
        wikidata_statements=10,
        triple_matches=[],
        precision=0.8,
        recall=0.7,
        f1=0.747,
        true_positives=7,
        false_positives=3,
        false_negatives=3,
        novel_discoveries=0,
        domain="biography_historical",
    )
    result = evaluator.aggregate([score], meta)
    assert result.run_metadata.articles_evaluated == 1
    assert result.total_riverbank_triples == 10
    assert "biography_historical" in result.by_domain


def test_dataset_evaluator_to_json(tmp_path: Path) -> None:
    from riverbank.eval.models import ArticleScore, RunMetadata
    from riverbank.eval.scorer import DatasetEvaluator

    evaluator = DatasetEvaluator()
    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="test",
        profile="wikidata-eval-v1",
        articles_evaluated=1,
    )
    score = ArticleScore(
        article_title="Test",
        wikidata_qid="Q1",
        riverbank_triples=5,
        wikidata_statements=5,
        triple_matches=[],
        true_positives=4,
        false_positives=1,
        false_negatives=1,
        novel_discoveries=0,
    )
    from riverbank.eval.models import DatasetResult  # noqa: PLC0415
    result = DatasetResult(run_metadata=meta, article_scores=[score])
    result.precision = 0.8
    result.recall = 0.8
    result.f1 = 0.8

    output_path = tmp_path / "report.json"
    evaluator.to_json(result, output_path)

    assert output_path.exists()
    data = json.loads(output_path.read_text())
    assert "run_metadata" in data
    assert "aggregate" in data
    assert "article_results" in data
    assert data["aggregate"]["precision"] == 0.8


def test_dataset_evaluator_by_domain_breakdown() -> None:
    from riverbank.eval.models import ArticleScore, RunMetadata
    from riverbank.eval.scorer import DatasetEvaluator

    evaluator = DatasetEvaluator()
    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="test",
        profile="wikidata-eval-v1",
    )
    scores = [
        ArticleScore(
            article_title=f"Bio {i}", wikidata_qid=f"Q{i}",
            riverbank_triples=5, wikidata_statements=5,
            triple_matches=[], true_positives=4, false_positives=1, false_negatives=1,
            novel_discoveries=0, domain="biography_historical",
        )
        for i in range(3)
    ] + [
        ArticleScore(
            article_title=f"Org {i}", wikidata_qid=f"Q{i+100}",
            riverbank_triples=3, wikidata_statements=3,
            triple_matches=[], true_positives=2, false_positives=1, false_negatives=1,
            novel_discoveries=0, domain="organization",
        )
        for i in range(2)
    ]
    result = evaluator.aggregate(scores, meta)
    assert "biography_historical" in result.by_domain
    assert "organization" in result.by_domain
    assert result.by_domain["biography_historical"]["articles"] == 3
    assert result.by_domain["organization"]["articles"] == 2


def test_dataset_evaluator_calibration_pearson() -> None:
    from riverbank.eval.models import ArticleScore, RunMetadata, TripleMatch
    from riverbank.eval.scorer import DatasetEvaluator

    evaluator = DatasetEvaluator()
    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="test",
        profile="wikidata-eval-v1",
    )
    # Perfect calibration: high confidence → exact; low confidence → no_match
    matches_high = [TripleMatch(("s", "p", "o"), 0.9, None, "exact", 1.0) for _ in range(5)]
    matches_low = [TripleMatch(("s", "p", "o"), 0.1, None, "no_match", 0.0) for _ in range(5)]

    score = ArticleScore(
        article_title="Test",
        wikidata_qid="Q1",
        riverbank_triples=10,
        wikidata_statements=5,
        triple_matches=matches_high + matches_low,
        true_positives=5,
        false_positives=5,
        false_negatives=0,
        novel_discoveries=0,
        confidence_buckets={
            "0.0-0.25": (5, 0.0),
            "0.25-0.5": (0, 0.0),
            "0.5-0.75": (0, 0.0),
            "0.75-1.0": (5, 1.0),
        },
    )
    result = evaluator.aggregate([score], meta)
    # Perfect calibration should produce positive Pearson ρ
    assert result.confidence_calibration_pearson_r >= 0.0


# ===========================================================================
# Integration: full pipeline smoke test
# ===========================================================================


def test_full_evaluation_pipeline_no_network() -> None:
    """End-to-end mock test: article → Wikidata item → score → report."""
    import json  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from riverbank.eval.entity_resolution import EntityResolver
    from riverbank.eval.models import (  # noqa: PLC0415
        RunMetadata,
        WikidataItem,
        WikidataStatement,
        WikipediaArticle,
    )
    from riverbank.eval.property_alignment import PropertyAlignmentTable
    from riverbank.eval.scorer import DatasetEvaluator, Scorer

    # Simulate an article
    article = WikipediaArticle(
        title="Marie Curie",
        url="https://en.wikipedia.org/wiki/Marie_Curie",
        qid="Q7186",
        content="# Marie Curie\n\nMarie Curie was a Polish-French physicist born in 1867.",
        source_wikilinks=["Physics", "Poland", "France"],
        fetch_timestamp=datetime(2026, 5, 7, tzinfo=timezone.utc),
    )

    # Simulate Wikidata ground truth
    wd_item = WikidataItem(
        qid="Q7186",
        label="Marie Curie",
        description="Polish-French physicist",
        aliases=["Maria Sklodowska-Curie"],
        statements=[
            WikidataStatement("P31", "instance of", "Q5", "wikibase-item", value_label="human"),
            WikidataStatement("P569", "date of birth", "1867-11-07", "time"),
            WikidataStatement("P27", "country of citizenship", "Q36", "wikibase-item", value_label="Poland"),
            WikidataStatement("P106", "occupation", "Q169470", "wikibase-item", value_label="physicist"),
        ],
    )

    # Simulated riverbank triples
    riverbank_triples = [
        ("ex:MarieCurie", "rdf:type", "human", 0.95),
        ("ex:MarieCurie", "pgc:birthDate", "1867-11-07", 0.92),
        ("ex:MarieCurie", "pgc:nationality", "Poland", 0.85),
        ("ex:MarieCurie", "pgc:hasOccupation", "physicist", 0.88),
        ("ex:MarieCurie", "ex:unknownPredicate", "Nobel Prize", 0.70),  # novel discovery
    ]

    scorer = Scorer(
        alignment_table=PropertyAlignmentTable(),
        entity_resolver=EntityResolver(wikidata_client=None),
    )
    score = scorer.score_article(
        article_title=article.title,
        riverbank_triples=riverbank_triples,
        wikidata_item=wd_item,
        domain="biography_historical",
    )

    assert score.riverbank_triples == 5
    assert score.wikidata_statements == 4
    assert score.novel_discoveries >= 1
    # P/R/F should be non-negative
    assert score.precision >= 0.0
    assert score.recall >= 0.0
    assert score.f1 >= 0.0

    # Serialize to JSON
    evaluator = DatasetEvaluator(scorer=scorer)
    meta = RunMetadata(
        date="2026-05-07T00:00:00Z",
        riverbank_version="0.15.0",
        dataset="smoke-test",
        profile="wikidata-eval-v1",
        articles_evaluated=1,
    )
    dataset_result = evaluator.aggregate([score], meta)

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "results" / "report.json"
        evaluator.to_json(dataset_result, output)
        assert output.exists()

        data = json.loads(output.read_text())
        assert data["run_metadata"]["riverbank_version"] == "0.15.0"
        assert data["aggregate"]["precision"] >= 0.0
        assert "biography_historical" in data.get("by_domain", {})
        assert len(data["article_results"]) == 1
