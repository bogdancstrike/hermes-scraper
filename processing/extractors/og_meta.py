"""
Open Graph and standard meta tag extractor.
Provides good fallback for title, description, image, and canonical URL.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from shared.logging import get_logger

logger = get_logger("extractor.og")


def extract_og_meta(html: str) -> dict:
    """
    Extract Open Graph and standard meta tags.

    Returns dict with: title, summary, top_image, canonical_url, date, keywords, language.
    """
    result: dict = {
        "title": None, "summary": None, "top_image": None,
        "canonical_url": None, "date": None, "keywords": [], "language": None,
    }
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return result

    def meta(prop_attr: str, val: str) -> str | None:
        tag = soup.find("meta", attrs={prop_attr: val})
        return tag.get("content") if tag else None

    # Title: OG > twitter:title > <title>
    result["title"] = (
        meta("property", "og:title")
        or meta("name", "twitter:title")
        or (soup.title.string.strip() if soup.title else None)
    )

    # Description / summary
    result["summary"] = (
        meta("property", "og:description")
        or meta("name", "description")
        or meta("name", "twitter:description")
    )

    # Image
    result["top_image"] = (
        meta("property", "og:image")
        or meta("name", "twitter:image")
    )

    # Canonical URL
    canonical_tag = soup.find("link", rel="canonical")
    result["canonical_url"] = (
        canonical_tag.get("href") if canonical_tag
        else meta("property", "og:url")
    )

    # Published date
    result["date"] = (
        meta("property", "article:published_time")
        or meta("name", "article:published_time")
        or meta("name", "pubdate")
        or meta("name", "date")
        or meta("itemprop", "datePublished")
    )

    # Keywords
    kw_raw = meta("name", "keywords") or meta("name", "news_keywords")
    if kw_raw:
        result["keywords"] = [k.strip() for k in kw_raw.split(",") if k.strip()]

    # Language
    html_tag = soup.find("html")
    if html_tag:
        result["language"] = html_tag.get("lang", "")

    return result
