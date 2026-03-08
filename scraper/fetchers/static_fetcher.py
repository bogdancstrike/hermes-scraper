"""
Static HTTP fetcher using curl-cffi for TLS fingerprint spoofing.

Tries to fetch pages as a real Chrome browser at the HTTP/2 + TLS level,
bypassing basic bot detection without launching a full browser.

Falls back gracefully to the requests library if curl-cffi is not installed.
"""
from __future__ import annotations

import asyncio
import random
import time

from shared.logging import get_logger
from scraper.detectors.anti_bot import detect_block_signals

logger = get_logger("static_fetcher")

# Stealth headers that mimic a real browser
_STEALTH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

# Jitter range in seconds (150–750ms)
_JITTER_MIN = 0.15
_JITTER_MAX = 0.75


async def fetch_static(
    url: str,
    timeout: int = 25,
    retries: int = 2,
) -> dict:
    """
    Fetch a URL using static HTTP (no JavaScript execution).

    Uses curl-cffi with Chrome 124 TLS impersonation if available,
    falls back to requests library otherwise.

    Returns:
        dict with keys: html, final_url, status_code, headers,
                        latency_ms, method ("static"), block_signals, error.
    """
    # Anti-bot jitter
    jitter = random.uniform(_JITTER_MIN, _JITTER_MAX)
    await asyncio.sleep(jitter)

    result = {
        "html": "",
        "final_url": url,
        "status_code": 0,
        "headers": {},
        "latency_ms": 0,
        "method": "static",
        "block_signals": [],
        "error": None,
    }

    for attempt in range(retries + 1):
        start = time.monotonic()
        try:
            html, final_url, status_code, headers = await _do_fetch(url, timeout)
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            result["html"] = html
            result["final_url"] = final_url
            result["status_code"] = status_code
            result["headers"] = dict(headers) if headers else {}
            result["block_signals"] = detect_block_signals(html, status_code, result["headers"])
            logger.debug(
                "static_fetch_success",
                url=url,
                status=status_code,
                latency_ms=result["latency_ms"],
                attempt=attempt,
            )
            return result
        except Exception as exc:
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            result["error"] = str(exc)
            logger.warning("static_fetch_error", url=url, attempt=attempt, error=str(exc))
            if attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))

    return result


async def _do_fetch(url: str, timeout: int) -> tuple[str, str, int, dict]:
    """Internal: attempt fetch using curl-cffi, fall back to requests."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_fetch, url, timeout)


def _sync_fetch(url: str, timeout: int) -> tuple[str, str, int, dict]:
    """Synchronous fetch — run in thread pool to avoid blocking event loop."""
    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(
            url,
            headers=_STEALTH_HEADERS,
            impersonate="chrome124",
            timeout=timeout,
            allow_redirects=True,
        )
        return resp.text, str(resp.url), resp.status_code, dict(resp.headers)
    except ImportError:
        pass  # Fall back to requests

    import requests
    resp = requests.get(
        url,
        headers=_STEALTH_HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )
    return resp.text, resp.url, resp.status_code, dict(resp.headers)
