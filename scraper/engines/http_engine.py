"""
Async HTTP engine with retry logic, proxy rotation, and block detection.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from scraper.anti_bot.proxy_pool import ProxyPool
from scraper.anti_bot.ua_rotator import next_ua
from scraper.config import config
from shared.logging import get_logger
from shared.metrics import fetch_duration_seconds, pages_blocked_total, pages_fetched_total

if TYPE_CHECKING:
    pass

logger = get_logger("http_engine")

# Signals that we've been blocked
BLOCK_SIGNALS = [
    lambda r: r.status_code in (403, 429, 503),
    lambda r: "captcha" in r.text.lower()[:2000],
    lambda r: "access denied" in r.text.lower()[:500],
    lambda r: "cloudflare" in r.text.lower()[:1000] and r.status_code == 403,
    lambda r: len(r.text) < 300 and r.status_code == 200,
]


def is_blocked(response: httpx.Response) -> bool:
    return any(signal(response) for signal in BLOCK_SIGNALS)


class HttpEngine:
    """
    Async HTTP client with:
    - Configurable delays between requests
    - Proxy rotation
    - User-agent rotation
    - Automatic retry with exponential backoff
    - Block detection
    """

    def __init__(self, proxy_pool: ProxyPool | None = None):
        self.proxy_pool = proxy_pool
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HttpEngine":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    def _build_client(self) -> httpx.AsyncClient:
        proxy = None
        if config.use_proxies and self.proxy_pool:
            proxy = self.proxy_pool.next()

        return httpx.AsyncClient(
            headers={
                "User-Agent": next_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            },
            proxies={"http://": proxy, "https://": proxy} if proxy else None,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            http2=True,
        )

    async def get(self, url: str, domain: str = "") -> str:
        """
        Fetch a URL with human-like delays, retry on failure.
        Returns HTML text or raises on unrecoverable error.
        """
        # Human-like delay
        delay = random.uniform(config.delay_min, config.delay_max)
        await asyncio.sleep(delay)

        start = time.monotonic()
        try:
            response = await self._get_with_retry(url)
        except Exception as exc:
            pages_fetched_total.labels(domain=domain or "unknown", status="error").inc()
            logger.warning("fetch_error", url=url, error=str(exc))
            raise

        duration = time.monotonic() - start
        fetch_duration_seconds.labels(domain=domain or "unknown").observe(duration)

        if is_blocked(response):
            pages_blocked_total.labels(domain=domain or "unknown").inc()
            pages_fetched_total.labels(domain=domain or "unknown", status="blocked").inc()
            logger.warning("block_detected", url=url, status_code=response.status_code)
            raise BlockedError(f"Blocked at {url} (status={response.status_code})")

        pages_fetched_total.labels(domain=domain or "unknown", status="success").inc()
        logger.debug("page_fetched", url=url, status=response.status_code, duration_ms=int(duration * 1000))
        return response.text

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _get_with_retry(self, url: str) -> httpx.Response:
        if not self._client:
            raise RuntimeError("HttpEngine not started. Use as async context manager.")
        response = await self._client.get(url)
        if response.status_code in (500, 502, 504):
            response.raise_for_status()
        return response

    async def rotate_proxy(self) -> None:
        """Swap proxy and rebuild client (call after block detection)."""
        if self._client:
            await self._client.aclose()
        self._client = self._build_client()
        logger.info("proxy_rotated")


class BlockedError(Exception):
    """Raised when a page fetch is blocked by anti-bot measures."""
    pass
