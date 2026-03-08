"""
JSON-LD structured data extractor.
JSON-LD is the highest-confidence source for article metadata on news sites.
Most Romanian news sites embed NewsArticle schema with full author/date/publisher info.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from shared.logging import get_logger

logger = get_logger("extractor.jsonld")

# JSON-LD types we care about
_ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "liveblogposting",
    "reportage", "scholarlyarticle", "technicalarticle",
}


def extract_jsonld(html: str) -> dict:
    """
    Extract article metadata from JSON-LD <script> blocks.

    Returns a flat dict with keys: title, author, authors, date, updated_date,
    summary, canonical_url, top_image, publisher, tags, article_type.
    All values default to None / empty list if not found.
    """
    result: dict = {
        "title": None, "author": None, "authors": [],
        "date": None, "updated_date": None,
        "summary": None, "canonical_url": None,
        "top_image": None, "publisher": None,
        "tags": [], "article_type": None,
    }

    try:
        soup = BeautifulSoup(html, "lxml")
        scripts = soup.find_all("script", type="application/ld+json")
    except Exception:
        return result

    for script in scripts:
        try:
            text = script.string or ""
            # Some sites have invalid JSON with trailing commas — try to clean
            text = re.sub(r",\s*([}\]])", r"\1", text)
            data = json.loads(text)
        except Exception:
            continue

        # Handle @graph arrays
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = [items]

        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("@type", "")).lower()
            if not any(t in item_type for t in _ARTICLE_TYPES):
                continue

            # Title
            if not result["title"]:
                result["title"] = item.get("headline") or item.get("name")

            # Author
            raw_author = item.get("author")
            if raw_author and not result["authors"]:
                if isinstance(raw_author, str):
                    result["authors"] = [raw_author]
                elif isinstance(raw_author, dict):
                    result["authors"] = [raw_author.get("name", "")]
                elif isinstance(raw_author, list):
                    result["authors"] = [
                        (a.get("name", "") if isinstance(a, dict) else str(a))
                        for a in raw_author
                    ]
                result["authors"] = [a for a in result["authors"] if a]
                result["author"] = result["authors"][0] if result["authors"] else None

            # Dates
            if not result["date"]:
                result["date"] = item.get("datePublished") or item.get("dateCreated")
            if not result["updated_date"]:
                result["updated_date"] = item.get("dateModified")

            # Description / summary
            if not result["summary"]:
                result["summary"] = item.get("description") or item.get("abstract")

            # Canonical URL
            if not result["canonical_url"]:
                result["canonical_url"] = item.get("url") or item.get("mainEntityOfPage")
                if isinstance(result["canonical_url"], dict):
                    result["canonical_url"] = result["canonical_url"].get("@id")

            # Image
            if not result["top_image"]:
                img = item.get("image")
                if isinstance(img, str):
                    result["top_image"] = img
                elif isinstance(img, dict):
                    result["top_image"] = img.get("url")
                elif isinstance(img, list) and img:
                    first = img[0]
                    result["top_image"] = first.get("url") if isinstance(first, dict) else first

            # Publisher
            if not result["publisher"]:
                pub = item.get("publisher")
                if isinstance(pub, dict):
                    result["publisher"] = {
                        "name": pub.get("name"),
                        "url": pub.get("url"),
                        "logo": (pub.get("logo") or {}).get("url") if isinstance(pub.get("logo"), dict) else pub.get("logo"),
                    }

            # Tags / keywords
            if not result["tags"]:
                kw = item.get("keywords")
                if isinstance(kw, str):
                    result["tags"] = [k.strip() for k in kw.split(",") if k.strip()]
                elif isinstance(kw, list):
                    result["tags"] = [str(k) for k in kw if k]

            # Article type
            if not result["article_type"]:
                result["article_type"] = item.get("@type")

    return result
