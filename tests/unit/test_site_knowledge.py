"""
Unit tests for scraper/knowledge/site_knowledge.py

All DB calls are mocked — tests run without a real database.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from scraper.knowledge.site_knowledge import (
    SiteKnowledgeRepository,
    SiteProfile,
    STRATEGY_STATIC,
    STRATEGY_PLAYWRIGHT,
    _row_to_profile,
)


def _get_loop():
    return asyncio.get_event_loop()


# ── SiteProfile ────────────────────────────────────────────────────────────────

class TestSiteProfile:
    def test_default_is_not_known(self):
        p = SiteProfile(domain="example.com")
        assert not p.is_known

    def test_known_after_total_scraped(self):
        p = SiteProfile(domain="example.com", total_scraped=5)
        assert p.is_known

    def test_recommend_playwright_for_spa(self):
        p = SiteProfile(domain="example.com", is_spa=True, preferred_fetch_method=STRATEGY_STATIC)
        assert p.recommend_fetch_method() == STRATEGY_PLAYWRIGHT

    def test_recommend_playwright_when_requires_js(self):
        p = SiteProfile(domain="example.com", requires_js=True, preferred_fetch_method=STRATEGY_STATIC)
        assert p.recommend_fetch_method() == STRATEGY_PLAYWRIGHT

    def test_recommend_static_when_known_low_block_rate(self):
        p = SiteProfile(
            domain="example.com",
            preferred_fetch_method=STRATEGY_STATIC,
            requires_js=False,
            is_spa=False,
            block_rate=0.1,
        )
        assert p.recommend_fetch_method() == STRATEGY_STATIC

    def test_recommend_playwright_when_high_block_rate(self):
        p = SiteProfile(
            domain="example.com",
            preferred_fetch_method=STRATEGY_STATIC,
            requires_js=False,
            block_rate=0.5,  # above 0.3 threshold
        )
        assert p.recommend_fetch_method() == STRATEGY_PLAYWRIGHT

    def test_default_recommendation_is_playwright(self):
        p = SiteProfile(domain="unknown.com")
        assert p.recommend_fetch_method() == STRATEGY_PLAYWRIGHT


# ── _row_to_profile ────────────────────────────────────────────────────────────

class TestRowToProfile:
    def test_full_row_converted(self):
        row = {
            "preferred_fetch_method": "static",
            "is_spa": False,
            "use_infinite_scroll": True,
            "navigation_strategy": "networkidle",
            "requires_js": False,
            "has_cloudflare": True,
            "has_datadome": False,
            "has_recaptcha": False,
            "block_rate": 0.05,
            "has_paywall": False,
            "has_comments": True,
            "comment_selector": "#comments",
            "has_jsonld": True,
            "has_og_meta": True,
            "selector_failure_count": 2,
            "total_scraped": 100,
            "success_rate": 0.98,
            "avg_article_word_count": 450,
            "avg_fetch_latency_ms": 230,
        }
        p = _row_to_profile("example.com", row)
        assert p.domain == "example.com"
        assert p.preferred_fetch_method == STRATEGY_STATIC
        assert p.has_cloudflare is True
        assert p.navigation_strategy == "networkidle"
        assert p.total_scraped == 100
        assert p.avg_fetch_latency_ms == 230

    def test_partial_row_uses_defaults(self):
        p = _row_to_profile("partial.com", {"total_scraped": 5})
        assert p.preferred_fetch_method == STRATEGY_PLAYWRIGHT
        assert p.is_spa is False
        assert p.block_rate == 0.0


# ── SiteKnowledgeRepository ────────────────────────────────────────────────────

class TestSiteKnowledgeRepository:
    def test_load_returns_default_when_no_db(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        profile = _get_loop().run_until_complete(repo.load("newsite.com"))
        assert profile.domain == "newsite.com"
        assert not profile.is_known

    def test_load_caches_result(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        p1 = loop.run_until_complete(repo.load("cached.com"))
        p2 = loop.run_until_complete(repo.load("cached.com"))
        assert p1 is p2  # same object in cache

    def test_load_from_db(self):
        repo = SiteKnowledgeRepository(db_ok=True)

        async def run():
            with patch("shared.db.get_site_knowledge", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {"total_scraped": 42, "preferred_fetch_method": "static"}
                profile = await repo.load("known.com")
                assert profile.total_scraped == 42
                assert profile.preferred_fetch_method == STRATEGY_STATIC

        _get_loop().run_until_complete(run())

    def test_load_returns_default_when_db_empty(self):
        repo = SiteKnowledgeRepository(db_ok=True)

        async def run():
            with patch("shared.db.get_site_knowledge", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = None
                profile = await repo.load("new.com")
                assert not profile.is_known

        _get_loop().run_until_complete(run())

    def test_update_patches_in_memory_cache(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        loop.run_until_complete(repo.load("patch.com"))
        loop.run_until_complete(repo.update("patch.com", has_cloudflare=True))
        assert repo._cache["patch.com"].has_cloudflare is True

    def test_record_static_success_updates_method(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        loop.run_until_complete(repo.load("static.com"))
        loop.run_until_complete(repo.record_static_success("static.com"))
        assert repo._cache["static.com"].preferred_fetch_method == STRATEGY_STATIC

    def test_record_selector_failure_increments_count(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        loop.run_until_complete(repo.load("failsite.com"))
        count = loop.run_until_complete(repo.record_selector_failure("failsite.com"))
        assert count == 1
        count2 = loop.run_until_complete(repo.record_selector_failure("failsite.com"))
        assert count2 == 2

    def test_record_cloudflare_signal(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        loop.run_until_complete(repo.load("cf.com"))
        loop.run_until_complete(repo.record_article_fetched(
            "cf.com", STRATEGY_PLAYWRIGHT, 2000, 500,
            success=False, block_signals=["cloudflare_ray_id"]
        ))
        assert repo._cache["cf.com"].has_cloudflare is True

    def test_record_article_fetched_updates_stats(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        loop.run_until_complete(repo.load("stats.com"))
        loop.run_until_complete(repo.record_article_fetched(
            "stats.com", STRATEGY_STATIC, 300, 800, success=True
        ))
        p = repo._cache["stats.com"]
        assert p.total_scraped == 1
        assert p.avg_fetch_latency_ms == 300
        assert p.avg_article_word_count == 800

    def test_record_metadata_signals(self):
        repo = SiteKnowledgeRepository(db_ok=False)
        loop = _get_loop()
        loop.run_until_complete(repo.load("meta.com"))
        loop.run_until_complete(repo.record_metadata_signals(
            "meta.com", has_jsonld=True, has_og_meta=True
        ))
        p = repo._cache["meta.com"]
        assert p.has_jsonld is True
        assert p.has_og_meta is True
