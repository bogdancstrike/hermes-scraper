"""
Date extraction using the htmldate library.
htmldate is highly accurate at mining dates from URLs, meta tags, and visible text.
"""
from __future__ import annotations

from shared.logging import get_logger

logger = get_logger("extractor.htmldate")


def extract_date(html: str, url: str = "") -> str | None:
    """
    Extract publication date using htmldate's comprehensive date mining.
    Falls back gracefully if the library is unavailable.
    """
    try:
        from htmldate import find_date
        date = find_date(
            html,
            url=url,
            original_date=True,       # Prefer original publish date over update date
            outputformat="%Y-%m-%dT%H:%M:%S",
        )
        return date
    except ImportError:
        logger.debug("htmldate_not_available")
    except Exception as exc:
        logger.debug("htmldate_extraction_failed", error=str(exc))
    return None
