"""
Selector client: multi-layer cache with live validity checking.

Cache hierarchy:
  L1 — Redis      (hot, 1-hour TTL, invalidated immediately on failure)
  L2 — PostgreSQL (persistent, 30-day TTL)
  L3 — LLM API   (source of truth, called only on full miss or failed validation)

Validity check:
  Before accepting cached selectors, they are tested against the actual rendered
  HTML of the page being scraped. If the expected selector matches zero elements,
  both caches are invalidated and the LLM is called to re-discover selectors.
  This detects silent site redesigns without waiting for the cache TTL to expire.
"""
from __future__ import annotations

import json
import os
import time

import httpx
import redis.asyncio as aioredis
from bs4 import BeautifulSoup

from shared.db import get_db
from shared.logging import get_logger
from shared.metrics import selector_cache_hits, selector_cache_misses
from shared.models import SiteSelectors

logger = get_logger("selector_client")

LLM_ENDPOINT = os.getenv("LLM_BASE_URL", "http://localhost:8000")
PG_CACHE_TTL_DAYS = int(os.getenv("LLM_SELECTOR_CACHE_TTL", "30"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_SELECTOR_TTL = int(os.getenv("REDIS_SELECTOR_TTL", "3600"))  # 1 hour

# A valid article_links_selector must match at least this many elements on a listing page
MIN_ARTICLE_LINKS = 1


class SelectorClient:
    """
    Manages CSS selector discovery and two-layer caching.

    Flow for get_or_discover(domain, url, html, page_type):
      1. Check Redis (L1). If hit → validate against html → return if valid,
         else invalidate Redis and fall through.
      2. Check PostgreSQL (L2). If hit → validate → write-back to Redis → return,
         else invalidate both and fall through.
      3. Call LLM for fresh discovery → store in Redis + PostgreSQL → return.

    LLM discovery modes:
      - llm_client=None (default): calls the llm_api HTTP service at LLM_ENDPOINT.
      - llm_client=<LLMClient>:   calls the LLM directly (standalone mode, no HTTP server).
    """

    def __init__(self, llm_client=None):
        self._redis: aioredis.Redis | None = None
        self._llm_client = llm_client  # optional direct LLMClient (bypasses HTTP endpoint)

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    @staticmethod
    def _redis_key(domain: str) -> str:
        return f"selectors:{domain}"

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_or_discover(
        self,
        domain: str,
        sample_url: str,
        html: str = "",
        page_type: str = "listing",
    ) -> SiteSelectors:
        """
        Return selectors for the domain, discovering via LLM only when necessary.

        Args:
            domain:      Site domain (e.g. "biziday.ro").
            sample_url:  URL of the page being scraped (context for LLM).
            html:        Rendered HTML of the page (used for validity check).
            page_type:   "listing" checks article_links_selector;
                         "article" checks article_body_selector.
        """
        # L1: Redis
        cached = await self._load_from_redis(domain)
        if cached and cached.is_valid():
            if self._validate_selectors(cached, html, page_type):
                selector_cache_hits.labels(domain=domain).inc()
                logger.debug("selector_cache_hit", layer="redis", domain=domain)
                return cached
            logger.info(
                "selector_cache_invalid",
                layer="redis",
                domain=domain,
                page_type=page_type,
            )
            await self._invalidate_redis(domain)

        # L2: PostgreSQL (only queried when Redis had nothing)
        if cached is None:
            pg_cached = await self._load_from_pg(domain)
            if pg_cached and pg_cached.is_valid():
                if self._validate_selectors(pg_cached, html, page_type):
                    selector_cache_hits.labels(domain=domain).inc()
                    logger.debug("selector_cache_hit", layer="postgres", domain=domain)
                    await self._save_to_redis(pg_cached)
                    return pg_cached
                logger.info(
                    "selector_cache_invalid",
                    layer="postgres",
                    domain=domain,
                    page_type=page_type,
                )
                await self._invalidate_redis(domain)
                await self._invalidate_pg(domain)

        # L3: LLM discovery
        selector_cache_misses.labels(domain=domain).inc()
        logger.info("selector_llm_discovery", domain=domain, sample_url=sample_url)
        return await self._discover_via_llm(domain, sample_url, html)

    def _validate_selectors(
        self,
        selectors: SiteSelectors,
        html: str,
        page_type: str,
    ) -> bool:
        """
        Test selectors against actual rendered HTML.

        Returns True  → selectors appear functional, use the cache.
        Returns False → selectors are broken, trigger re-discovery.

        Short or empty HTML skips validation (trust the cache) to avoid
        false invalidity during startup or transient fetch errors.
        """
        if not html or len(html) < 500:
            return True

        try:
            soup = BeautifulSoup(html, "lxml")

            if page_type == "listing" and selectors.article_links_selector:
                matched = len(soup.select(selectors.article_links_selector))
                if matched < MIN_ARTICLE_LINKS:
                    logger.warning(
                        "selector_validation_failed",
                        domain=selectors.domain,
                        page_type=page_type,
                        selector=selectors.article_links_selector,
                        matched=matched,
                    )
                    return False

            elif page_type == "article" and selectors.article_body_selector:
                matched = len(soup.select(selectors.article_body_selector))
                if matched < 1:
                    logger.warning(
                        "selector_validation_failed",
                        domain=selectors.domain,
                        page_type=page_type,
                        selector=selectors.article_body_selector,
                        matched=matched,
                    )
                    return False

        except Exception as exc:
            # Validation error → assume valid to avoid thrashing
            logger.warning(
                "selector_validation_error",
                domain=selectors.domain,
                error=str(exc),
            )

        return True

    async def close(self) -> None:
        """Close Redis connection cleanly."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def invalidate(self, domain: str) -> None:
        """Force LLM re-discovery on the next access. Clears Redis and PostgreSQL."""
        await self._invalidate_redis(domain)
        await self._invalidate_pg(domain)
        logger.info("selector_cache_invalidated", domain=domain)

    # ── Redis ──────────────────────────────────────────────────────────────────

    async def _load_from_redis(self, domain: str) -> SiteSelectors | None:
        try:
            r = await self._get_redis()
            raw = await r.get(self._redis_key(domain))
            if raw:
                return SiteSelectors(**json.loads(raw))
        except Exception as exc:
            logger.warning("selector_redis_read_failed", domain=domain, error=str(exc))
        return None

    async def _save_to_redis(self, selectors: SiteSelectors) -> None:
        try:
            r = await self._get_redis()
            await r.setex(
                self._redis_key(selectors.domain),
                REDIS_SELECTOR_TTL,
                json.dumps(selectors.model_dump(), default=str),
            )
        except Exception as exc:
            logger.warning("selector_redis_write_failed", domain=selectors.domain, error=str(exc))

    async def _invalidate_redis(self, domain: str) -> None:
        try:
            r = await self._get_redis()
            await r.delete(self._redis_key(domain))
        except Exception as exc:
            logger.warning("selector_redis_invalidate_failed", domain=domain, error=str(exc))

    # ── PostgreSQL ─────────────────────────────────────────────────────────────

    async def _load_from_pg(self, domain: str) -> SiteSelectors | None:
        try:
            async with get_db() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM site_selectors
                    WHERE domain = $1
                      AND updated_at > NOW() - INTERVAL '30 days'
                    """,
                    domain,
                )
            if row:
                return SiteSelectors(**dict(row))
        except Exception as exc:
            logger.warning("selector_pg_read_failed", domain=domain, error=str(exc))
        return None

    async def _save_to_pg(self, selectors: SiteSelectors) -> None:
        try:
            async with get_db() as conn:
                await conn.execute(
                    """
                    INSERT INTO site_selectors (
                        domain, article_links_selector, pagination_next_selector,
                        article_body_selector, article_title_selector,
                        article_date_selector, author_selector,
                        confidence, llm_model, updated_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
                    ON CONFLICT (domain) DO UPDATE SET
                        article_links_selector   = EXCLUDED.article_links_selector,
                        pagination_next_selector = EXCLUDED.pagination_next_selector,
                        article_body_selector    = EXCLUDED.article_body_selector,
                        article_title_selector   = EXCLUDED.article_title_selector,
                        article_date_selector    = EXCLUDED.article_date_selector,
                        author_selector          = EXCLUDED.author_selector,
                        confidence               = EXCLUDED.confidence,
                        llm_model                = EXCLUDED.llm_model,
                        updated_at               = NOW()
                    """,
                    selectors.domain,
                    selectors.article_links_selector,
                    selectors.pagination_next_selector,
                    selectors.article_body_selector,
                    selectors.article_title_selector,
                    selectors.article_date_selector,
                    selectors.author_selector,
                    selectors.confidence,
                    selectors.llm_model,
                )
        except Exception as exc:
            logger.error("selector_pg_write_failed", domain=selectors.domain, error=str(exc))

    async def _invalidate_pg(self, domain: str) -> None:
        try:
            async with get_db() as conn:
                await conn.execute(
                    "UPDATE site_selectors SET updated_at = '2000-01-01' WHERE domain = $1",
                    domain,
                )
        except Exception as exc:
            logger.warning("selector_pg_invalidate_failed", domain=domain, error=str(exc))

    # ── LLM discovery ──────────────────────────────────────────────────────────

    async def _discover_via_llm(
        self, domain: str, sample_url: str, html: str = ""
    ) -> SiteSelectors:
        """
        Discover selectors via LLM, then write-through to both caches.

        Routes to direct LLM client (standalone mode) or HTTP endpoint (distributed mode)
        depending on whether a direct LLMClient was injected at construction.
        """
        compact_dom = self._compact_dom(html) if html else ""

        if self._llm_client is not None:
            data, model_used = await self._discover_direct(domain, sample_url, compact_dom)
        else:
            data, model_used = await self._discover_http(domain, sample_url, compact_dom)

        selectors = SiteSelectors(
            domain=domain,
            article_links_selector=data.get("article_links_selector", ""),
            pagination_next_selector=data.get("pagination_next_selector", ""),
            article_body_selector=data.get("article_body_selector", ""),
            article_title_selector=data.get("article_title_selector", ""),
            article_date_selector=data.get("article_date_selector", ""),
            author_selector=data.get("author_selector", ""),
            confidence=data.get("confidence", 0.8),
            llm_model=model_used,
        )

        # Write-through to both caches
        await self._save_to_redis(selectors)
        await self._save_to_pg(selectors)
        return selectors

    async def _discover_direct(
        self, domain: str, sample_url: str, compact_dom: str
    ) -> tuple[dict, str]:
        """Call the injected LLMClient directly — no HTTP server needed."""
        from llm_api.prompts import SELECTOR_DISCOVERY_SYSTEM, SELECTOR_DISCOVERY_USER

        start = time.monotonic()
        user_prompt = SELECTOR_DISCOVERY_USER.format(
            domain=domain,
            sample_url=sample_url,
            dom=compact_dom,
        )
        try:
            text, model_used = await self._llm_client.complete(
                system_prompt=SELECTOR_DISCOVERY_SYSTEM,
                user_prompt=user_prompt,
                endpoint_label="analyze-selectors",
            )
            data = self._llm_client.parse_json_response(text)
        except Exception as exc:
            logger.error("llm_direct_discovery_failed", domain=domain, error=str(exc))
            return {}, ""

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "llm_selector_discovered_direct",
            domain=domain,
            duration_ms=duration_ms,
            confidence=data.get("confidence", 0),
            model=model_used,
        )
        return data, model_used

    async def _discover_http(
        self, domain: str, sample_url: str, compact_dom: str
    ) -> tuple[dict, str]:
        """Call the llm_api HTTP service — used in distributed (Kafka) mode."""
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{LLM_ENDPOINT}/v1/analyze-selectors",
                    json={"domain": domain, "dom": compact_dom, "sample_url": sample_url},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("llm_http_discovery_failed", domain=domain, error=str(exc))
            return {}, ""

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "llm_selector_discovered_http",
            domain=domain,
            duration_ms=duration_ms,
            confidence=data.get("confidence", 0),
            model=data.get("model_used", ""),
        )
        return data, data.get("model_used", "")

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compact_dom(html: str, max_chars: int = 4000) -> str:
        """Strip noise from HTML; return compact DOM for LLM prompt."""
        import re as _re
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "noscript", "svg", "iframe", "picture", "video"]):
                tag.decompose()
            # Strip Tailwind/utility class noise — keep only short semantic class names
            _tailwind = _re.compile(r'[:\[\]\/]|^(flex|grid|block|inline|hidden|relative|absolute|'
                                    r'overflow|items-|justify-|self-|text-|font-|leading-|tracking-|'
                                    r'p[xylrtb]?-|m[xylrtb]?-|w-|h-|min-|max-|gap-|space-|'
                                    r'bg-|border|rounded|shadow|opacity|z-|cursor-|select-|'
                                    r'transition|duration|ease|delay-|animate-|fill-|stroke-)')
            for tag in soup.find_all(True):
                if tag.get("class"):
                    kept = [c for c in tag["class"] if not _tailwind.search(c)]
                    if kept:
                        tag["class"] = kept
                    else:
                        del tag["class"]
                # Remove noisy attributes, keep id/href/data-*/type/name/rel
                for attr in list(tag.attrs):
                    if attr not in {"id", "href", "class", "type", "name", "rel",
                                    "data-testid", "data-id", "data-type", "data-category"}:
                        if not attr.startswith("data-"):
                            del tag.attrs[attr]
            body = soup.body or soup
            return str(body)[:max_chars]
        except Exception:
            return html[:max_chars]
