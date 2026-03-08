"""Unit tests for paginator URL filtering and next-page detection."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from scraper.navigation.paginator import Paginator
from shared.models import SiteSelectors


def make_paginator(selectors: dict = None) -> Paginator:
    engine = AsyncMock()
    sel = SiteSelectors(domain="example.com", **(selectors or {}))
    return Paginator(engine, sel, max_pages=10)


class TestIsArticleUrl:
    def setup_method(self):
        self.pag = make_paginator()

    def test_valid_article_url(self):
        assert self.pag._is_article_url("https://example.com/article/hello-world", "example.com")

    def test_rejects_different_domain(self):
        assert not self.pag._is_article_url("https://other.com/article", "example.com")

    def test_rejects_category_url(self):
        assert not self.pag._is_article_url("https://example.com/category/tech", "example.com")

    def test_rejects_tag_url(self):
        assert not self.pag._is_article_url("https://example.com/tag/python", "example.com")

    def test_rejects_author_url(self):
        assert not self.pag._is_article_url("https://example.com/author/alice", "example.com")

    def test_rejects_feed(self):
        assert not self.pag._is_article_url("https://example.com/feed.xml", "example.com")

    def test_accepts_deep_path(self):
        assert self.pag._is_article_url("https://example.com/2024/01/my-post", "example.com")


class TestFindNextPage:
    def test_with_configured_selector(self):
        from bs4 import BeautifulSoup
        pag = make_paginator({"pagination_next_selector": "a.next"})
        html = '<html><body><a class="next" href="/page/2">Next</a></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = pag._find_next_page(soup, "https://example.com/page/1")
        assert result == "https://example.com/page/2"

    def test_returns_none_when_no_next(self):
        from bs4 import BeautifulSoup
        pag = make_paginator()
        html = '<html><body><p>Last page</p></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = pag._find_next_page(soup, "https://example.com/page/3")
        assert result is None
