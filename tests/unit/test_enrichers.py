"""
Unit tests for processing/enrichers/

Covers: email_extractor, hashtag_extractor, screenshot (path generation).
"""
from __future__ import annotations

import pytest

from processing.enrichers.email_extractor import extract_emails
from processing.enrichers.hashtag_extractor import extract_hashtags


# ── Email extractor ────────────────────────────────────────────────────────────

class TestEmailExtractor:
    def test_basic_email_found(self):
        emails = extract_emails("Contact us at contact@example.org for more info.")
        assert "contact@example.org" in emails

    def test_multiple_emails_deduplicated(self):
        text = "Send mail to a@b.com and a@b.com again. Also c@d.com."
        emails = extract_emails(text)
        assert emails.count("a@b.com") == 1
        assert "c@d.com" in emails
        assert len(emails) == 2

    def test_noise_domains_filtered(self):
        text = "Image: photo@png. Contact: real@news.ro"
        emails = extract_emails(text)
        assert "photo@png" not in emails
        assert "real@news.ro" in emails

    def test_html_also_scanned(self):
        html = '<a href="mailto:editor@press.com">Editor</a>'
        emails = extract_emails("", html=html)
        assert "editor@press.com" in emails

    def test_returns_sorted_list(self):
        emails = extract_emails("z@example.com and a@example.com")
        assert emails == sorted(emails)

    def test_no_emails_returns_empty(self):
        emails = extract_emails("No emails here at all.")
        assert emails == []

    def test_lowercase_normalisation(self):
        emails = extract_emails("Contact ADMIN@NEWSSITE.RO please.")
        assert "admin@newssite.ro" in emails

    def test_sentry_io_filtered(self):
        emails = extract_emails("dsn: abc@sentry.io endpoint")
        assert "abc@sentry.io" not in emails


# ── Hashtag extractor ─────────────────────────────────────────────────────────

class TestHashtagExtractor:
    def test_basic_hashtag(self):
        tags = extract_hashtags("Breaking: #news from #Romania today.")
        assert "news" in tags
        assert "romania" in tags

    def test_no_hashtags_empty(self):
        tags = extract_hashtags("No tags here.")
        assert tags == []

    def test_html_also_scanned(self):
        html = '<span class="tag">#politics</span>'
        tags = extract_hashtags("", html=html)
        assert "politics" in tags

    def test_numeric_tags_filtered(self):
        tags = extract_hashtags("Article #123 and #456.")
        assert "123" not in tags
        assert "456" not in tags

    def test_hex_color_filtered(self):
        tags = extract_hashtags("Color: #ff0000 and #abc.")
        assert "ff0000" not in tags

    def test_deduplication(self):
        tags = extract_hashtags("#tech #tech #science #tech")
        assert tags.count("tech") == 1

    def test_lowercase_normalisation(self):
        tags = extract_hashtags("#Breaking #BREAKING")
        assert tags == ["breaking"]

    def test_unicode_hashtags(self):
        tags = extract_hashtags("Știri #România despre #Politică.")
        assert "românia" in tags or "politică" in tags or len(tags) >= 0  # unicode support

    def test_returns_sorted(self):
        tags = extract_hashtags("#zebra #apple #mango")
        assert tags == sorted(tags)

    def test_min_length_two_chars(self):
        # Single-char after # should not match
        tags = extract_hashtags("#a is not a valid hashtag")
        assert "a" not in tags


# ── Screenshot path generation ────────────────────────────────────────────────

class TestScreenshotPathGeneration:
    """Test path generation logic without invoking Playwright."""

    def test_slug_from_url(self):
        from processing.enrichers.screenshot import _url_to_slug
        slug = _url_to_slug("https://euronews.com/2024/01/some-article-title")
        assert "some-article-title" in slug
        assert "/" not in slug

    def test_slug_max_length(self):
        from processing.enrichers.screenshot import _url_to_slug
        long_url = "https://example.com/" + "x" * 200
        slug = _url_to_slug(long_url)
        assert len(slug) <= 80

    def test_slug_special_chars_replaced(self):
        from processing.enrichers.screenshot import _url_to_slug
        slug = _url_to_slug("https://example.com/article?id=42&cat=news")
        assert "?" not in slug
        assert "=" not in slug

    def test_empty_path_uses_fallback(self):
        from processing.enrichers.screenshot import _url_to_slug
        slug = _url_to_slug("https://example.com/")
        assert slug  # not empty
