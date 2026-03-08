"""Unit tests for shared data models."""
import pytest
from shared.models import (
    ScrapeJob, RawHtmlPage, ScrapedArticle,
    SiteSelectors, SelectorRequest,
)


class TestSiteSelectors:
    def test_valid_with_article_links(self):
        s = SiteSelectors(domain="example.com", article_links_selector="a.post")
        assert s.is_valid()

    def test_valid_with_body_selector(self):
        s = SiteSelectors(domain="example.com", article_body_selector="div.content")
        assert s.is_valid()

    def test_invalid_when_empty(self):
        s = SiteSelectors(domain="example.com")
        assert not s.is_valid()

    def test_domain_required(self):
        with pytest.raises(Exception):
            SiteSelectors()


class TestScrapeJob:
    def test_auto_job_id(self):
        job = ScrapeJob(site_id="abc", domain="example.com", start_url="https://example.com")
        assert job.job_id
        assert len(job.job_id) == 36  # UUID

    def test_default_priority(self):
        job = ScrapeJob(site_id="abc", domain="example.com", start_url="https://example.com")
        assert job.priority == 5

    def test_serialization(self):
        job = ScrapeJob(site_id="abc", domain="example.com", start_url="https://example.com")
        d = job.model_dump()
        assert d["domain"] == "example.com"
        assert "job_id" in d


class TestRawHtmlPage:
    def test_creation(self):
        page = RawHtmlPage(
            job_id="job1",
            domain="example.com",
            url="https://example.com/article",
            html="<html><body>Hello</body></html>",
        )
        assert page.page_id  # auto-generated
        assert page.domain == "example.com"

    def test_serialization_roundtrip(self):
        page = RawHtmlPage(
            job_id="job1", domain="example.com",
            url="https://example.com", html="<html/>",
        )
        d = page.model_dump()
        page2 = RawHtmlPage(**d)
        assert page2.url == page.url


class TestScrapedArticle:
    def test_defaults(self):
        article = ScrapedArticle(
            job_id="j1", page_id="p1",
            source="example.com", url="https://example.com",
        )
        assert article.title is None
        assert article.author is None
        assert article.content == ""

    def test_with_metadata(self):
        article = ScrapedArticle(
            job_id="j1", page_id="p1",
            source="example.com", url="https://example.com",
            title="Test Article",
            author="Jane Smith",
            published_date="2024-01-01",
            language="en",
            content="Article body text here.",
        )
        assert article.title == "Test Article"
        assert article.language == "en"
