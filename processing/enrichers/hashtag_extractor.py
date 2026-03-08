"""
Hashtag extractor — finds #hashtags in article content and HTML.
Enabled via EXTRACT_HASHTAGS=True.
"""
from __future__ import annotations

import re

# Match #word (Unicode-aware), minimum 2 chars after #
_HASHTAG_RE = re.compile(r'(?<!\w)#([a-zA-Z\u00C0-\u017E][a-zA-Z0-9\u00C0-\u017E_]{1,})')

# Ignore common false positives (CSS IDs, hex colours, numeric IDs)
_NUMERIC_RE = re.compile(r'^\d+$')
_HEX_RE = re.compile(r'^[0-9a-fA-F]{3,8}$')


def extract_hashtags(text: str, html: str = "") -> list[str]:
    """
    Return unique hashtags found in text and/or HTML, normalised to lowercase.

    Args:
        text: Plain article content.
        html: Raw page HTML (optional).

    Returns:
        Sorted list of unique hashtags (without the # prefix).
    """
    combined = text + "\n" + html
    found = _HASHTAG_RE.findall(combined)
    seen: set[str] = set()
    result: list[str] = []
    for tag in found:
        tag_lower = tag.lower()
        # Skip pure numbers and CSS hex colours
        if _NUMERIC_RE.match(tag_lower) or _HEX_RE.match(tag_lower):
            continue
        if tag_lower not in seen:
            seen.add(tag_lower)
            result.append(tag_lower)
    return sorted(result)
