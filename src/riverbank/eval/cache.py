"""Article cache management for the Wikidata evaluation framework.

Stores Wikipedia articles as Markdown files plus JSON metadata sidecar files
under ``~/.riverbank/article_cache/`` (or a custom directory).

File layout::

    <cache_dir>/
        marie_curie.md           ← article body (Markdown)
        marie_curie.meta.json    ← CacheMetadata serialized as JSON
        albert_einstein.md
        albert_einstein.meta.json
        ...

Title normalization: lowercase, whitespace → underscore, strip non-alnum except
underscores (so "Marie Curie" → "marie_curie").

TTL: articles older than ``cache_ttl_days`` are considered stale.  Stale articles
are returned but flagged; callers decide whether to refresh.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from riverbank.eval.models import CacheMetadata, WikipediaArticle


class ArticleCache:
    """File-based cache for Wikipedia articles.

    Parameters
    ----------
    cache_dir:
        Directory for cached articles.  Created on first write.
    cache_ttl_days:
        Number of days before a cached article is considered stale.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        cache_ttl_days: int = 30,
    ) -> None:
        self.cache_dir = cache_dir or Path.home() / ".riverbank" / "article_cache"
        self.cache_ttl_days = cache_ttl_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, title: str) -> WikipediaArticle | None:
        """Return a cached article or *None* if not found."""
        key = self._normalize(title)
        md_path = self.cache_dir / f"{key}.md"
        meta_path = self.cache_dir / f"{key}.meta.json"

        if not md_path.exists() or not meta_path.exists():
            return None

        meta = self._read_meta(meta_path)
        content = md_path.read_text(encoding="utf-8")

        return WikipediaArticle(
            title=meta.title,
            url=meta.url,
            qid=meta.qid,
            content=content,
            source_wikilinks=[],
            fetch_timestamp=meta.fetch_timestamp,
            cache_path=md_path,
        )

    def put(self, article: WikipediaArticle) -> None:
        """Persist an article to cache."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = self._normalize(article.title)
        md_path = self.cache_dir / f"{key}.md"
        meta_path = self.cache_dir / f"{key}.meta.json"

        md_path.write_text(article.content, encoding="utf-8")

        meta = CacheMetadata(
            title=article.title,
            url=article.url,
            qid=article.qid,
            fetch_timestamp=article.fetch_timestamp,
            cache_ttl_days=self.cache_ttl_days,
            is_stale=False,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "title": meta.title,
                    "url": meta.url,
                    "qid": meta.qid,
                    "fetch_timestamp": meta.fetch_timestamp.isoformat(),
                    "cache_ttl_days": meta.cache_ttl_days,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def invalidate(self, title: str) -> bool:
        """Delete cached article.  Returns True if it existed."""
        key = self._normalize(title)
        removed = False
        for ext in (".md", ".meta.json"):
            path = self.cache_dir / f"{key}{ext}"
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def is_valid(self, title: str) -> bool:
        """Return True if cached and not stale."""
        key = self._normalize(title)
        meta_path = self.cache_dir / f"{key}.meta.json"
        if not meta_path.exists():
            return False
        meta = self._read_meta(meta_path)
        age = datetime.now(tz=timezone.utc) - meta.fetch_timestamp
        return age < timedelta(days=self.cache_ttl_days)

    def list_all(self) -> list[str]:
        """Return titles of all cached articles."""
        if not self.cache_dir.exists():
            return []
        return [
            p.stem
            for p in self.cache_dir.iterdir()
            if p.suffix == ".md"
        ]

    def prune(self, max_age_days: int | None = None) -> int:
        """Delete stale entries.  Returns number of entries removed."""
        ttl = max_age_days if max_age_days is not None else self.cache_ttl_days
        removed = 0
        if not self.cache_dir.exists():
            return 0
        for meta_path in list(self.cache_dir.glob("*.meta.json")):
            try:
                meta = self._read_meta(meta_path)
                age = datetime.now(tz=timezone.utc) - meta.fetch_timestamp
                if age >= timedelta(days=ttl):
                    key = meta_path.stem.replace(".meta", "")
                    for ext in (".md", ".meta.json"):
                        p = self.cache_dir / f"{key}{ext}"
                        if p.exists():
                            p.unlink()
                    removed += 1
            except Exception:  # noqa: BLE001
                continue
        return removed

    def stats(self) -> dict:
        """Return cache statistics."""
        if not self.cache_dir.exists():
            return {"total": 0, "stale": 0, "cache_dir": str(self.cache_dir)}

        entries = list(self.cache_dir.glob("*.meta.json"))
        stale = sum(1 for p in entries if not self.is_valid(p.stem.replace(".meta", "")))
        total_bytes = sum(
            p.stat().st_size
            for p in self.cache_dir.iterdir()
            if p.is_file()
        )
        return {
            "total": len(entries),
            "stale": stale,
            "fresh": len(entries) - stale,
            "total_bytes": total_bytes,
            "cache_dir": str(self.cache_dir),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(title: str) -> str:
        """Normalize a title to a safe filename stem."""
        normalized = title.lower()
        normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "untitled"

    @staticmethod
    def _read_meta(meta_path: Path) -> CacheMetadata:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["fetch_timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return CacheMetadata(
            title=data.get("title", ""),
            url=data.get("url", ""),
            qid=data.get("qid", ""),
            fetch_timestamp=ts,
            cache_ttl_days=data.get("cache_ttl_days", 30),
        )
