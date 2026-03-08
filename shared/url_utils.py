"""
URL canonicalization utilities.
Strips tracking parameters before deduplication to prevent re-scraping
the same article with different UTM tags or referral parameters.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Query parameters that carry no semantic meaning for content identity
_TRACKING_PARAMS = frozenset({
    # UTM campaign tracking
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name",
    # Facebook / Meta
    "fbclid", "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    # Google
    "gclid", "gclsrc", "dclid",
    # Twitter / X
    "twclid",
    # HubSpot
    "hsa_cam", "hsa_grp", "hsa_mt", "hsa_src", "hsa_ad", "hsa_acc",
    "hsa_net", "hsa_kw", "hsa_tgt", "hsa_ver",
    # Microsoft
    "msclkid",
    # Misc analytics
    "mc_cid", "mc_eid",   # Mailchimp
    "_ga", "_gl",          # Google Analytics cross-domain
    "ref", "referrer",
    "source", "medium",
})


def canonicalize_url(url: str) -> str:
    """
    Return a canonical form of the URL with tracking parameters removed.

    Examples:
        https://example.com/article?utm_source=twitter&id=123
        → https://example.com/article?id=123

        https://example.com/article?fbclid=abc123
        → https://example.com/article
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        cleaned = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(cleaned, doseq=True)
        canonical = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/") or "/",
            parsed.params,
            new_query,
            "",  # strip fragment
        ))
        return canonical
    except Exception:
        return url


def extract_domain(url: str) -> str:
    """Extract bare domain from URL (e.g. 'https://www.adevarul.ro/...' → 'adevarul.ro')."""
    try:
        host = urlparse(url).netloc.lower()
        # Strip www. prefix
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""
