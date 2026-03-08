"""
Readability-based content extraction fallback.
Uses Mozilla's readability algorithm (readability-lxml) as a last resort
when trafilatura extracts too little content.
"""
from __future__ import annotations

from shared.logging import get_logger

logger = get_logger("extractor.readability")

MIN_READABILITY_WORDS = 50


def extract_readability(html: str) -> dict:
    """
    Extract article content and title using the readability algorithm.

    Returns dict with: title, content. Empty strings if extraction fails.
    """
    result = {"title": None, "content": ""}
    try:
        from readability import Document
        doc = Document(html)
        title = doc.title() or ""
        # Get plain text from readability summary HTML
        from bs4 import BeautifulSoup
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        content = soup.get_text(separator=" ", strip=True)

        if len(content.split()) >= MIN_READABILITY_WORDS:
            result["title"] = title.strip() or None
            result["content"] = content
    except ImportError:
        logger.debug("readability_not_available")
    except Exception as exc:
        logger.debug("readability_extraction_failed", error=str(exc))
    return result
