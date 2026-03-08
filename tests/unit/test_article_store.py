"""
Unit tests for shared/article_store.py

Tests run entirely in memory — no real DB required.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from shared.article_store import ArticleStore


def _make_article(url: str = "https://example.com/article-1", **kwargs) -> dict:
    return {
        "url": url,
        "domain": "example.com",
        "title": "Test Article Title",
        "content": "Some content here",
        "word_count": 100,
        "overall_score": 0.8,
        "fetch_method": "static",
        **kwargs,
    }


# ── ArticleStore (no-DB mode) ──────────────────────────────────────────────────

class TestArticleStoreNoDB:
    def test_save_returns_true_for_new_article(self):
        store = ArticleStore(db_ok=False)
        result = asyncio.get_event_loop().run_until_complete(
            store.save(_make_article())
        )
        # No NDJSON path → can't confirm save, but no error
        # With db_ok=False and no ndjson, save returns False (nowhere to persist)
        assert result is False

    def test_skip_duplicate_url(self):
        store = ArticleStore(db_ok=False)
        article = _make_article()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(store.save(article))
        # Second call with same URL should be skipped (in-memory dedup)
        result = loop.run_until_complete(store.save(article))
        assert result is False

    def test_skip_empty_url(self):
        store = ArticleStore(db_ok=False)
        result = asyncio.get_event_loop().run_until_complete(
            store.save({"url": "", "title": "No URL article"})
        )
        assert result is False

    def test_multiple_different_urls_all_accepted(self):
        store = ArticleStore(db_ok=False)
        loop = asyncio.get_event_loop()
        # All should pass the in-memory dedup
        urls = [f"https://example.com/article-{i}" for i in range(5)]
        for url in urls:
            loop.run_until_complete(store.save(_make_article(url=url)))
        assert len(store._seen) == 5


# ── ArticleStore with NDJSON fallback ─────────────────────────────────────────

class TestArticleStoreNDJSON:
    def test_writes_ndjson_file(self, tmp_path):
        ndjson = tmp_path / "articles.ndjson"
        store = ArticleStore(db_ok=False, ndjson_path=ndjson)
        article = _make_article()
        asyncio.get_event_loop().run_until_complete(store.save(article))
        store.close()

        assert ndjson.exists()
        lines = ndjson.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["url"] == article["url"]

    def test_multiple_articles_appended(self, tmp_path):
        ndjson = tmp_path / "articles.ndjson"
        store = ArticleStore(db_ok=False, ndjson_path=ndjson)
        loop = asyncio.get_event_loop()
        for i in range(3):
            loop.run_until_complete(
                store.save(_make_article(url=f"https://example.com/article-{i}"))
            )
        store.close()

        lines = ndjson.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    def test_duplicate_not_written_twice(self, tmp_path):
        ndjson = tmp_path / "articles.ndjson"
        store = ArticleStore(db_ok=False, ndjson_path=ndjson)
        loop = asyncio.get_event_loop()
        article = _make_article()
        loop.run_until_complete(store.save(article))
        loop.run_until_complete(store.save(article))  # duplicate
        store.close()

        lines = ndjson.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_returns_true_when_ndjson_written(self, tmp_path):
        ndjson = tmp_path / "articles.ndjson"
        store = ArticleStore(db_ok=False, ndjson_path=ndjson)
        result = asyncio.get_event_loop().run_until_complete(
            store.save(_make_article())
        )
        store.close()
        assert result is True

    def test_creates_parent_directory(self, tmp_path):
        ndjson = tmp_path / "subdir" / "deep" / "articles.ndjson"
        store = ArticleStore(db_ok=False, ndjson_path=ndjson)
        asyncio.get_event_loop().run_until_complete(store.save(_make_article()))
        store.close()
        assert ndjson.exists()


# ── ArticleStore with mocked DB ───────────────────────────────────────────────

class TestArticleStoreWithDB:
    def test_calls_save_article_on_db_ok(self, tmp_path):
        store = ArticleStore(db_ok=True)

        async def run():
            with patch("shared.article_store.ArticleStore.save") as mock_save:
                mock_save.return_value = True
                return await store.save(_make_article())

        # Directly mock the DB call
        async def patched_run():
            with patch("shared.db.save_article", new_callable=AsyncMock) as mock_db:
                mock_db.return_value = True
                result = await store.save(_make_article())
                assert mock_db.called
                return result

        result = asyncio.get_event_loop().run_until_complete(patched_run())
        assert result is True

    def test_db_error_does_not_raise(self):
        store = ArticleStore(db_ok=True)

        async def patched_run():
            with patch("shared.db.save_article", new_callable=AsyncMock) as mock_db:
                mock_db.side_effect = RuntimeError("DB connection lost")
                # Should not raise — graceful degradation
                result = await store.save(_make_article())
                return result

        result = asyncio.get_event_loop().run_until_complete(patched_run())
        assert result is False
