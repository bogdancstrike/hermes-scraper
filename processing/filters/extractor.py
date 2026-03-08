"""
Multi-source article content extractor.

Extraction priority (highest confidence first):
  1. JSON-LD structured data  (0.95–0.98)
  2. Trafilatura               (0.86–0.95)
  3. Open Graph / meta tags    (0.70–0.90)
  4. htmldate                  (0.90 — date only)
  5. Readability fallback      (0.65)

All sources are merged by field confidence; the final ArticleData dict
contains the best available value for each field plus provenance tracking.
"""
from __future__ import annotations

import json

import trafilatura

from processing.extractors.jsonld import extract_jsonld
from processing.extractors.og_meta import extract_og_meta
from processing.extractors.htmldate_extractor import extract_date
from processing.extractors.readability_extractor import extract_readability
from processing.scoring.merge import merge_fields
from processing.scoring.quality import compute_quality
from shared.logging import get_logger

logger = get_logger("extractor")

MIN_TEXT_LENGTH = 100  # characters


def extract_main_content(html: str, url: str = "") -> dict | None:
    """
    Extract article content using all available sources and merge by confidence.

    Returns a rich dict with keys:
        text, title, author, authors, date, updated_date, summary, language,
        canonical_url, top_image, publisher, tags, keywords, article_type,
        word_count, reading_time_minutes, overall_score,
        title_score, content_score, date_score, author_score,
        likely_paywalled, likely_liveblog,
        field_sources, field_confidence.

    Returns None if no meaningful content is found.
    """
    sources: dict[str, dict] = {}

    # ── Source 1: JSON-LD ─────────────────────────────────────────────────────
    try:
        jld = extract_jsonld(html)
        sources["jsonld"] = jld
    except Exception as exc:
        logger.debug("jsonld_extraction_error", error=str(exc))

    # ── Source 2: Trafilatura ─────────────────────────────────────────────────
    try:
        result_json = trafilatura.extract(
            html, url=url, output_format="json",
            with_metadata=True, include_comments=False,
            include_tables=True, no_fallback=False, favor_recall=True,
        )
        if result_json:
            data = json.loads(result_json)
            sources["trafilatura"] = {
                "title": data.get("title"),
                "author": data.get("author"),
                "date": data.get("date"),
                "content": data.get("text", ""),
                "summary": data.get("description"),
                "language": data.get("language"),
                "canonical_url": data.get("url"),
            }
    except Exception as exc:
        logger.debug("trafilatura_extraction_error", error=str(exc))

    # ── Source 3: Open Graph / meta ───────────────────────────────────────────
    try:
        og = extract_og_meta(html)
        sources["og"] = og
    except Exception as exc:
        logger.debug("og_extraction_error", error=str(exc))

    # ── Source 4: htmldate (date only) ────────────────────────────────────────
    try:
        hdate = extract_date(html, url)
        if hdate:
            sources["htmldate"] = {"date": hdate}
    except Exception as exc:
        logger.debug("htmldate_extraction_error", error=str(exc))

    # ── Source 5: Readability fallback ────────────────────────────────────────
    # Only run if trafilatura content is thin
    traf_content = (sources.get("trafilatura") or {}).get("content", "")
    if len(traf_content) < MIN_TEXT_LENGTH:
        try:
            read = extract_readability(html)
            sources["readability"] = read
        except Exception as exc:
            logger.debug("readability_extraction_error", error=str(exc))

    # ── Merge by confidence ───────────────────────────────────────────────────
    merged, field_sources, field_confidence = merge_fields(sources)

    content = merged.get("content") or ""
    if len(content) < MIN_TEXT_LENGTH:
        logger.debug("content_too_short", url=url, length=len(content))
        return None

    # ── Quality scoring ───────────────────────────────────────────────────────
    quality = compute_quality(
        title=merged.get("title"),
        content=content,
        date=merged.get("date"),
        author=merged.get("author"),
    )

    # ── Authors list ──────────────────────────────────────────────────────────
    authors = sources.get("jsonld", {}).get("authors", [])
    if not authors and merged.get("author"):
        authors = [merged["author"]]

    # ── Tags / keywords ───────────────────────────────────────────────────────
    tags = sources.get("jsonld", {}).get("tags", [])
    keywords = sources.get("og", {}).get("keywords", [])

    return {
        # Content
        "text": content,
        "title": merged.get("title"),
        "author": merged.get("author"),
        "authors": authors,
        "date": merged.get("date"),
        "updated_date": merged.get("updated_date"),
        "summary": merged.get("summary"),
        "language": merged.get("language"),
        # URLs & media
        "canonical_url": merged.get("canonical_url"),
        "top_image": merged.get("top_image"),
        "publisher": merged.get("publisher"),
        # Taxonomy
        "tags": tags,
        "keywords": keywords,
        "article_type": sources.get("jsonld", {}).get("article_type"),
        # Quality
        **quality,
        # Provenance
        "field_sources": field_sources,
        "field_confidence": field_confidence,
    }
