"""Wikipedia article fetcher for the Wikidata evaluation framework.

Fetches Wikipedia articles as Markdown via the MediaWiki REST API with hybrid
local caching::

    cache hit (not stale)  → return immediately (no network)
    cache miss / stale     → fetch from Wikipedia API → cache → return
    --no-cache             → always fetch fresh (but still update cache)
    --cache-only           → raise CacheOnlyError if not in cache

Article content is fetched as HTML via the MediaWiki REST API
(``/api/rest_v1/page/html/{title}``) and converted to Markdown using
``html2text``.  Falls back to the action API (``action=parse``) if the REST
endpoint returns 404.

User-Agent requirement
~~~~~~~~~~~~~~~~~~~~~~
Both Wikipedia and Wikidata reject requests without a descriptive User-Agent.
This module sends::

    User-Agent: riverbank-eval/0.15.0 (trickle-labs/riverbank; github.com/trickle-labs/riverbank)

Query resolution
~~~~~~~~~~~~~~~~
The ``fetch_article`` method accepts:
- Plain title: ``"Marie Curie"``
- Wikipedia URL: ``"https://en.wikipedia.org/wiki/Marie_Curie"``
- Wikidata Q-id: ``"Q7186"``
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from riverbank.eval.cache import ArticleCache
from riverbank.eval.models import WikipediaArticle

_USER_AGENT = (
    "riverbank-eval/0.15.0 "
    "(trickle-labs/riverbank; github.com/trickle-labs/riverbank)"
)
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_WIKIPEDIA_REST = "https://en.wikipedia.org/api/rest_v1/page/html"


class CacheOnlyError(RuntimeError):
    """Raised when --cache-only is set but the article is not in cache."""


class WikipediaClient:
    """Fetch Wikipedia articles as Markdown with hybrid local caching.

    Parameters
    ----------
    cache_dir:
        Cache directory (default: ``~/.riverbank/article_cache``).
    cache_ttl_days:
        Seconds before a cached entry is considered stale.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        cache_ttl_days: int = 30,
    ) -> None:
        self._cache = ArticleCache(cache_dir=cache_dir, cache_ttl_days=cache_ttl_days)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_article(
        self,
        query: str,
        force_fresh: bool = False,
        cache_only: bool = False,
    ) -> WikipediaArticle:
        """Resolve *query* and return the article as Markdown.

        Parameters
        ----------
        query:
            Wikipedia title, URL, or Wikidata Q-id.
        force_fresh:
            Bypass cache; always fetch from the Wikipedia API.
        cache_only:
            Never hit the network; raise ``CacheOnlyError`` if not cached.
        """
        title = self._normalize_query(query)

        if not force_fresh and self._cache.is_valid(title):
            cached = self._cache.get(title)
            if cached is not None:
                return cached

        if cache_only:
            cached = self._cache.get(title)
            if cached is not None:
                return cached
            raise CacheOnlyError(
                f"Article '{title}' is not in the local cache. "
                "Remove --cache-only or run without it to fetch from Wikipedia."
            )

        # Fetch from Wikipedia
        markdown_content = self._fetch_markdown(title)
        qid = self._get_qid_from_article(title)
        wikilinks = self._extract_wikilinks(markdown_content)

        article = WikipediaArticle(
            title=title,
            url=f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            qid=qid,
            content=markdown_content,
            source_wikilinks=wikilinks,
            fetch_timestamp=datetime.now(tz=timezone.utc),
        )
        self._cache.put(article)
        return article

    def get_qid_from_article(self, article_title: str) -> str:
        """Query Wikipedia API for the article's Wikidata Q-id sitelink."""
        return self._get_qid_from_article(article_title)

    @property
    def cache(self) -> ArticleCache:
        """Expose the underlying ArticleCache."""
        return self._cache

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_query(self, query: str) -> str:
        """Extract article title from various query formats."""
        query = query.strip()

        # Wikipedia URL
        if "wikipedia.org/wiki/" in query:
            path = query.split("/wiki/")[-1]
            return urllib.parse.unquote(path.replace("_", " ")).split("#")[0]

        # Wikidata Q-id  → resolve to Wikipedia title
        if re.match(r"^Q\d+$", query, re.IGNORECASE):
            return self._title_from_qid(query)

        return query

    def _title_from_qid(self, qid: str) -> str:
        """Resolve a Wikidata Q-id to an English Wikipedia article title."""
        try:
            import requests  # noqa: PLC0415
        except ImportError:
            return qid

        params = {
            "action": "wbgetentities",
            "ids": qid,
            "props": "sitelinks",
            "sitefilter": "enwiki",
            "format": "json",
        }
        try:
            resp = requests.get(
                "https://www.wikidata.org/w/api.php",
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            data = resp.json()
            entity = data.get("entities", {}).get(qid, {})
            sitelinks = entity.get("sitelinks", {})
            enwiki = sitelinks.get("enwiki", {})
            return enwiki.get("title", qid)
        except Exception:  # noqa: BLE001
            return qid

    def _fetch_markdown(self, title: str) -> str:
        """Fetch article as Markdown; falls back to empty string on error."""
        try:
            return self._fetch_via_rest_api(title)
        except Exception:  # noqa: BLE001
            try:
                return self._fetch_via_action_api(title)
            except Exception:  # noqa: BLE001
                return f"# {title}\n\n[Article content unavailable]\n"

    def _fetch_via_rest_api(self, title: str) -> str:
        """Fetch HTML via the MediaWiki REST API and convert to Markdown."""
        import requests  # noqa: PLC0415

        url = f"{_WIKIPEDIA_REST}/{urllib.parse.quote(title.replace(' ', '_'))}"
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            timeout=30,
        )
        resp.raise_for_status()
        return self._html_to_markdown(resp.text, title)

    def _fetch_via_action_api(self, title: str) -> str:
        """Fallback: fetch parsed HTML via MediaWiki action API."""
        import requests  # noqa: PLC0415

        params = {
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
            "disabletoc": "1",
        }
        resp = requests.get(
            _WIKIPEDIA_API,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        html = data.get("parse", {}).get("text", {}).get("*", "")
        return self._html_to_markdown(html, title)

    @staticmethod
    def _html_to_markdown(html: str, title: str) -> str:
        """Convert HTML to Markdown using html2text (if available)."""
        try:
            import html2text  # noqa: PLC0415

            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.body_width = 0  # no line wrapping
            converter.ignore_images = True
            converter.ignore_tables = False
            md = converter.handle(html)
            # Strip common Wikipedia boilerplate footer patterns
            md = re.sub(r"\n## (Retrieved from|Categories|Navigation menu).*", "", md, flags=re.DOTALL)
            return md.strip()
        except ImportError:
            # Strip HTML tags as minimal fallback
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return f"# {title}\n\n{text}"

    def _get_qid_from_article(self, title: str) -> str:
        """Query Wikipedia API for the article's Wikidata Q-id."""
        try:
            import requests  # noqa: PLC0415
        except ImportError:
            return ""

        params = {
            "action": "query",
            "titles": title,
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "format": "json",
        }
        try:
            resp = requests.get(
                _WIKIPEDIA_API,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                qid = page.get("pageprops", {}).get("wikibase_item", "")
                if qid:
                    return qid
            return ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _extract_wikilinks(markdown: str) -> list[str]:
        """Extract [[wikilinks]] from Markdown text."""
        return re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", markdown)
