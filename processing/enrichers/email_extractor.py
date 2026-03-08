"""
Email extractor — finds email addresses in article content and HTML.
Enabled via EXTRACT_EMAILS=True.
"""
from __future__ import annotations

import re

# RFC-5321 simplified; covers the vast majority of real-world emails
_EMAIL_RE = re.compile(
    r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'
)

# Domains that are clearly not real emails (image filenames, CSS, etc.)
_NOISE_DOMAINS = frozenset({
    "example.com", "domain.com", "email.com", "test.com",
    "png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js",
    "sentry.io",
})


def extract_emails(text: str, html: str = "") -> list[str]:
    """
    Return unique, deduplicated email addresses found in text and/or HTML.

    Args:
        text: Plain article content (already extracted).
        html: Raw page HTML (optional, scanned in addition to text).

    Returns:
        Sorted list of unique emails, noise-filtered.
    """
    combined = text + "\n" + html
    found = _EMAIL_RE.findall(combined)
    seen: set[str] = set()
    result: list[str] = []
    for email in found:
        email_lower = email.lower()
        domain = email_lower.split("@", 1)[1] if "@" in email_lower else ""
        if domain in _NOISE_DOMAINS:
            continue
        if email_lower not in seen:
            seen.add(email_lower)
            result.append(email_lower)
    return sorted(result)
