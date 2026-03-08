"""
Near-duplicate detection using SimHash.
Prevents sending duplicate content to the expensive LLM layer.
"""
from __future__ import annotations

import hashlib
import os
from typing import Iterable

import redis.asyncio as aioredis

from shared.logging import get_logger
from shared.metrics import dedup_rejections_total

logger = get_logger("deduplicator")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DEDUP_TTL = int(os.getenv("REDIS_DEDUP_TTL", "604800"))  # 7 days
SIMHASH_DISTANCE_THRESHOLD = 3  # Hamming distance for "near duplicate"


def _simhash(text: str) -> int:
    """Simple 64-bit SimHash implementation."""
    tokens = text.lower().split()
    v = [0] * 64

    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        for i in range(64):
            bit = 1 if (h >> i) & 1 else -1
            v[i] += bit

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def _hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two integers."""
    x = a ^ b
    count = 0
    while x:
        count += x & 1
        x >>= 1
    return count


class Deduplicator:
    """Redis-backed near-duplicate detector using SimHash."""

    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client

    @classmethod
    async def create(cls, redis_url: str = REDIS_URL) -> "Deduplicator":
        client = aioredis.from_url(redis_url, decode_responses=True)
        return cls(client)

    async def is_duplicate(self, text: str, url: str = "") -> bool:
        """
        Check if text is a near-duplicate of previously seen content.
        Also stores the hash for future comparison.
        """
        # Exact URL dedup first (faster)
        url_key = f"url:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
        if await self._redis.exists(url_key):
            dedup_rejections_total.inc()
            return True

        # SimHash near-dedup
        h = _simhash(text[:10000])  # Use first 10k chars
        is_dup = await self._check_simhash(h)

        if not is_dup:
            await self._store_hash(h)
            await self._redis.setex(url_key, DEDUP_TTL, "1")
        else:
            dedup_rejections_total.inc()

        return is_dup

    async def _check_simhash(self, h: int) -> bool:
        """Check against stored SimHashes using Redis ZRANGEBYSCORE approximation."""
        # Simple approach: store hash as string, scan recent ones
        # For production, use a proper SimHash index (e.g., band technique)
        key = "simhashes"
        stored = await self._redis.lrange(key, 0, 999)  # Check last 1000
        for stored_h_str in stored:
            try:
                stored_h = int(stored_h_str)
                if _hamming_distance(h, stored_h) <= SIMHASH_DISTANCE_THRESHOLD:
                    return True
            except ValueError:
                continue
        return False

    async def _store_hash(self, h: int) -> None:
        """Store hash, keeping last 10,000."""
        key = "simhashes"
        pipe = self._redis.pipeline()
        pipe.lpush(key, str(h))
        pipe.ltrim(key, 0, 9999)
        pipe.expire(key, DEDUP_TTL)
        await pipe.execute()
