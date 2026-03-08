"""
Article quality scoring.

Produces a 0.0–1.0 overall quality score from individual field scores,
plus boolean flags for paywalled/liveblog/gallery content.
"""
from __future__ import annotations

import re

# Paywall detection patterns (Romanian + English)
_PAYWALL_PATTERNS = re.compile(
    r"subscribe to continue|abonează-te|abonati-va|abonează|"
    r"premium content|become a member|subscription required|"
    r"continue reading with|unlock this article|"
    r"acest articol este disponibil|acces premium",
    re.IGNORECASE,
)

# Liveblog detection patterns
_LIVEBLOG_PATTERNS = re.compile(
    r"\blive\b|\blive blog\b|liveblog|live update|breaking live|"
    r"ultima oră|urmărește live|transmisiune live",
    re.IGNORECASE,
)

# Minimum word count for a full-quality content score
_CONTENT_WORDS_FULL = 600


def compute_quality(
    title: str | None,
    content: str,
    date: str | None,
    author: str | None,
) -> dict:
    """
    Compute quality scores for an article.

    Returns dict with:
        title_score, content_score, date_score, author_score,
        overall_score (0.0–1.0),
        likely_paywalled, likely_liveblog (bool flags),
        word_count, reading_time_minutes.
    """
    word_count = len(content.split()) if content else 0

    title_score = 1.0 if title and title.strip() else 0.0
    content_score = min(1.0, word_count / _CONTENT_WORDS_FULL)
    date_score = 1.0 if date else 0.0
    author_score = 1.0 if author and author.strip() else 0.0

    overall_score = (
        title_score * 0.25
        + content_score * 0.45
        + date_score * 0.15
        + author_score * 0.15
    )

    # Content flags
    probe = (title or "") + " " + content[:2000]
    likely_paywalled = bool(_PAYWALL_PATTERNS.search(probe))
    likely_liveblog = bool(_LIVEBLOG_PATTERNS.search(probe))

    reading_time = max(1, round(word_count / 200))

    return {
        "title_score": round(title_score, 4),
        "content_score": round(content_score, 4),
        "date_score": round(date_score, 4),
        "author_score": round(author_score, 4),
        "overall_score": round(overall_score, 4),
        "likely_paywalled": likely_paywalled,
        "likely_liveblog": likely_liveblog,
        "word_count": word_count,
        "reading_time_minutes": reading_time,
    }
