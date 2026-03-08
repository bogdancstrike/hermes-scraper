"""
Redis-backed cookie jar for session persistence per domain.
Reusing cookies reduces bot detection significantly.
"""
from __future__ import annotations

import json

import redis.asyncio as aioredis

from shared.logging import get_logger

logger = get_logger("cookie_jar")


class CookieJar:
    """Persist cookies per domain in Redis."""

    def __init__(self, redis_client: aioredis.Redis, ttl_seconds: int = 3600):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _key(self, domain: str) -> str:
        return f"cookies:{domain}"

    async def load(self, domain: str) -> dict:
        """Load cookies for a domain."""
        raw = await self._redis.get(self._key(domain))
        if raw:
            return json.loads(raw)
        return {}

    async def save(self, domain: str, cookies: dict) -> None:
        """Save cookies for a domain."""
        await self._redis.setex(
            self._key(domain),
            self._ttl,
            json.dumps(cookies),
        )

    async def clear(self, domain: str) -> None:
        """Clear cookies for a domain."""
        await self._redis.delete(self._key(domain))


async def get_cookie_jar(redis_url: str) -> CookieJar:
    """Create a CookieJar backed by the given Redis URL."""
    client = aioredis.from_url(redis_url, decode_responses=True)
    return CookieJar(client)
