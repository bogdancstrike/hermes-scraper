"""
SiteKnowledge — per-domain learning repository.

Loads what we already know about a site from PostgreSQL, exposes helpers
to update it after each scrape run, and provides a strategy recommendation
based on accumulated data.

Strategy selection priority:
  1. static  — curl-cffi (fastest, stealth TLS, no JS)
  2. playwright — full browser render (JS, overlays, infinite scroll)
  3. api_intercept — not yet implemented (XHR capture for SPA)

Stored in `site_knowledge` table; gracefully returns defaults when DB unavailable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.logging import get_logger

logger = get_logger("site_knowledge")

# Default fetch strategy constants
STRATEGY_STATIC = "static"
STRATEGY_PLAYWRIGHT = "playwright"
STRATEGY_API_INTERCEPT = "api_intercept"


@dataclass
class SiteProfile:
    """In-memory view of everything we know about a domain."""
    domain: str

    # Strategy
    preferred_fetch_method: str = STRATEGY_PLAYWRIGHT
    is_spa: bool = False
    use_infinite_scroll: bool = True
    navigation_strategy: str = "domcontentloaded"
    requires_js: bool = True

    # WAF / anti-bot
    has_cloudflare: bool = False
    has_datadome: bool = False
    has_recaptcha: bool = False
    block_rate: float = 0.0

    # Content signals
    has_paywall: bool = False
    has_comments: bool = False
    comment_selector: str = ""
    has_jsonld: bool = False
    has_og_meta: bool = False

    # Selector reliability
    selector_failure_count: int = 0

    # Stats
    total_scraped: int = 0
    success_rate: float = 1.0
    avg_article_word_count: int = 0
    avg_fetch_latency_ms: int = 0

    # Raw DB row extras
    _extra: dict = field(default_factory=dict, repr=False)

    @property
    def is_known(self) -> bool:
        return self.total_scraped > 0

    def recommend_fetch_method(self) -> str:
        """
        Pick the best fetch method for an article URL based on accumulated knowledge.

        Rules:
          - If the site requires JS or is an SPA → playwright
          - If static has historically worked and block_rate is low → static
          - Default → playwright (safe)
        """
        if self.is_spa or self.requires_js:
            return STRATEGY_PLAYWRIGHT
        if self.preferred_fetch_method == STRATEGY_STATIC and self.block_rate < 0.3:
            return STRATEGY_STATIC
        return STRATEGY_PLAYWRIGHT


class SiteKnowledgeRepository:
    """
    Repository pattern for site_knowledge table.
    All DB errors are swallowed — callers receive defaults instead of exceptions.
    """

    def __init__(self, db_ok: bool = True):
        self._db_ok = db_ok
        self._cache: dict[str, SiteProfile] = {}

    async def load(self, domain: str) -> SiteProfile:
        """Return a SiteProfile for the domain, loading from DB if needed."""
        if domain in self._cache:
            return self._cache[domain]

        profile = SiteProfile(domain=domain)

        if self._db_ok:
            try:
                from shared.db import get_site_knowledge
                row = await get_site_knowledge(domain)
                if row:
                    profile = _row_to_profile(domain, row)
                    logger.debug("site_knowledge_loaded", domain=domain,
                                 total_scraped=profile.total_scraped,
                                 preferred_method=profile.preferred_fetch_method)
            except Exception as exc:
                logger.warning("site_knowledge_load_failed", domain=domain, error=str(exc))

        self._cache[domain] = profile
        return profile

    async def update(self, domain: str, **fields: Any) -> None:
        """Persist partial updates to the knowledge base."""
        # Update in-memory cache immediately
        if domain in self._cache:
            for k, v in fields.items():
                if hasattr(self._cache[domain], k):
                    setattr(self._cache[domain], k, v)

        if not self._db_ok:
            return
        try:
            from shared.db import upsert_site_knowledge
            await upsert_site_knowledge(domain, **fields)
        except Exception as exc:
            logger.warning("site_knowledge_update_failed", domain=domain, error=str(exc))

    async def record_article_fetched(
        self,
        domain: str,
        fetch_method: str,
        latency_ms: int,
        word_count: int,
        success: bool,
        block_signals: list[str] | None = None,
    ) -> None:
        """Update rolling statistics after an article is fetched."""
        profile = await self.load(domain)

        # Update in-memory stats optimistically
        total = profile.total_scraped + 1
        profile.total_scraped = total
        if success:
            profile.avg_fetch_latency_ms = int(
                (profile.avg_fetch_latency_ms * (total - 1) + latency_ms) / total
            )
            if word_count > 0:
                profile.avg_article_word_count = int(
                    (profile.avg_article_word_count * (total - 1) + word_count) / total
                )

        # Detect WAF signals
        if block_signals:
            updates: dict[str, Any] = {}
            if any("cloudflare" in s for s in block_signals):
                profile.has_cloudflare = True
                updates["has_cloudflare"] = True
            if any("datadome" in s for s in block_signals):
                profile.has_datadome = True
                updates["has_datadome"] = True
            if any("recaptcha" in s or "captcha" in s for s in block_signals):
                profile.has_recaptcha = True
                updates["has_recaptcha"] = True
            if updates:
                await self.update(domain, **updates)

        if self._db_ok:
            try:
                from shared.db import increment_scraped_count
                await increment_scraped_count(domain, success=success)
            except Exception:
                pass

    async def record_selector_failure(self, domain: str) -> int:
        """Increment selector failure count. Returns the new count."""
        profile = await self.load(domain)
        profile.selector_failure_count += 1
        await self.update(domain, selector_failure_count=profile.selector_failure_count)
        return profile.selector_failure_count

    async def record_static_success(self, domain: str) -> None:
        """Mark that static fetch works for this domain."""
        profile = await self.load(domain)
        if profile.preferred_fetch_method != STRATEGY_STATIC:
            profile.preferred_fetch_method = STRATEGY_STATIC
            await self.update(domain, preferred_fetch_method=STRATEGY_STATIC, requires_js=False)
            logger.info("site_knowledge_strategy_updated",
                        domain=domain, method=STRATEGY_STATIC)

    async def record_metadata_signals(
        self,
        domain: str,
        has_jsonld: bool,
        has_og_meta: bool,
    ) -> None:
        """Store which metadata formats the site uses (guides fast-path extraction)."""
        profile = await self.load(domain)
        if has_jsonld != profile.has_jsonld or has_og_meta != profile.has_og_meta:
            profile.has_jsonld = has_jsonld
            profile.has_og_meta = has_og_meta
            await self.update(domain, has_jsonld=has_jsonld, has_og_meta=has_og_meta)


def _row_to_profile(domain: str, row: dict) -> SiteProfile:
    """Convert a DB row dict to a SiteProfile dataclass."""
    return SiteProfile(
        domain=domain,
        preferred_fetch_method=row.get("preferred_fetch_method", STRATEGY_PLAYWRIGHT),
        is_spa=row.get("is_spa", False),
        use_infinite_scroll=row.get("use_infinite_scroll", True),
        navigation_strategy=row.get("navigation_strategy", "domcontentloaded"),
        requires_js=row.get("requires_js", True),
        has_cloudflare=row.get("has_cloudflare", False),
        has_datadome=row.get("has_datadome", False),
        has_recaptcha=row.get("has_recaptcha", False),
        block_rate=row.get("block_rate", 0.0),
        has_paywall=row.get("has_paywall", False),
        has_comments=row.get("has_comments", False),
        comment_selector=row.get("comment_selector", ""),
        has_jsonld=row.get("has_jsonld", False),
        has_og_meta=row.get("has_og_meta", False),
        selector_failure_count=row.get("selector_failure_count", 0),
        total_scraped=row.get("total_scraped", 0),
        success_rate=row.get("success_rate", 1.0),
        avg_article_word_count=row.get("avg_article_word_count", 0),
        avg_fetch_latency_ms=row.get("avg_fetch_latency_ms", 0),
    )
