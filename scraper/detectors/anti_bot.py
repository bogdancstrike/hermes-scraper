"""
Anti-bot / WAF block detection.

Scans HTTP responses for known WAF and bot-protection markers.
Block signals are informational — the scraper logs them and continues,
but callers can decide to retry with a different fetch strategy.
"""
from __future__ import annotations

from shared.logging import get_logger

logger = get_logger("anti_bot")

# Mapping of signal name → list of HTML/header substrings that indicate blocking
_BLOCK_MARKERS: dict[str, list[str]] = {
    "cloudflare": [
        "cloudflare", "attention required", "checking your browser",
        "cf-browser-verification", "cf_clearance", "just a moment",
        "enable cookies", "ray id:",
    ],
    "akamai": [
        "akamai", "access denied", "reference #",
        "akamai ghost", "akamaierror",
    ],
    "datadome": ["datadome", "__ddg", "dd_cookie"],
    "captcha": [
        "captcha", "recaptcha", "hcaptcha",
        "verify you are human", "are you a robot",
        "i'm not a robot",
    ],
    "js_challenge": [
        "enable javascript", "javascript is required",
        "javascript must be enabled", "requires javascript",
    ],
    "bot_protection": [
        "bot protection", "security check", "ddos protection",
        "please wait while we", "automated access",
    ],
    "paywall_block": [
        "subscribe to continue", "abonează-te", "subscription required",
        "premium content", "become a member to",
    ],
}

# HTTP status codes that indicate blocking or rate limiting
_BLOCK_STATUS_CODES: frozenset[int] = frozenset({403, 429, 503, 520, 521, 522, 523, 524})


def detect_block_signals(
    html: str,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> list[str]:
    """
    Scan response for WAF / bot-protection markers.

    Args:
        html:        Page HTML content.
        status_code: HTTP response status code.
        headers:     Response headers dict.

    Returns:
        List of detected signal names (empty = no blocking detected).
    """
    signals: list[str] = []

    # HTTP status check
    if status_code in _BLOCK_STATUS_CODES:
        signals.append(f"http_{status_code}")

    # HTML content scan (case-insensitive, check first 8KB — block pages are small)
    probe = html[:8000].lower() if html else ""
    for signal_name, markers in _BLOCK_MARKERS.items():
        if any(marker in probe for marker in markers):
            signals.append(signal_name)

    # Header scan
    if headers:
        header_text = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
        if "cf-ray" in header_text or "cf-cache-status" in header_text:
            if "cloudflare" not in signals:
                signals.append("cloudflare")
        if "x-datadome" in header_text:
            if "datadome" not in signals:
                signals.append("datadome")

    if signals:
        logger.warning("block_signals_detected", signals=signals, status_code=status_code)

    return signals


def is_blocked(signals: list[str]) -> bool:
    """
    Return True if the block signals indicate the page content is unusable
    (i.e. we got a WAF challenge page rather than real content).

    Paywall blocks are NOT considered hard blocks — content may still be partial.
    """
    hard_blocks = {"cloudflare", "akamai", "datadome", "captcha", "js_challenge", "bot_protection"}
    hard_blocks.update({f"http_{c}" for c in _BLOCK_STATUS_CODES})
    return bool(set(signals) & hard_blocks)
