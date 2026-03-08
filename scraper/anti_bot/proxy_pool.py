"""
Proxy pool with rotation.
Supports: static list, remote URL (newline-delimited), or none.
"""
from __future__ import annotations

import asyncio
import itertools
import os
from typing import Iterator

import httpx

from shared.logging import get_logger

logger = get_logger("proxy_pool")


class ProxyPool:
    """Thread-safe proxy rotation pool."""

    def __init__(self, proxies: list[str]):
        self._proxies = proxies
        self._cycle: Iterator[str] = itertools.cycle(proxies) if proxies else iter([])
        self._current: str | None = None

    @classmethod
    async def from_url(cls, url: str) -> "ProxyPool":
        """Load proxies from a remote URL."""
        if not url:
            return cls([])
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                proxies = [
                    line.strip()
                    for line in resp.text.splitlines()
                    if line.strip() and not line.startswith("#")
                ]
            logger.info("proxies_loaded", count=len(proxies))
            return cls(proxies)
        except Exception as exc:
            logger.warning("proxy_load_failed", url=url, error=str(exc))
            return cls([])

    @classmethod
    def from_env(cls) -> "ProxyPool":
        """Load proxies from PROXY_LIST env var (comma-separated)."""
        raw = os.getenv("PROXY_LIST", "")
        proxies = [p.strip() for p in raw.split(",") if p.strip()]
        return cls(proxies)

    def next(self) -> str | None:
        """Return next proxy in rotation."""
        try:
            self._current = next(self._cycle)
            return self._current
        except StopIteration:
            return None

    def mark_bad(self, proxy: str) -> None:
        """Remove a bad proxy from rotation."""
        if proxy in self._proxies:
            self._proxies.remove(proxy)
            self._cycle = itertools.cycle(self._proxies) if self._proxies else iter([])
            logger.info("proxy_removed", proxy=proxy, remaining=len(self._proxies))

    def __len__(self) -> int:
        return len(self._proxies)

    def is_empty(self) -> bool:
        return len(self._proxies) == 0
