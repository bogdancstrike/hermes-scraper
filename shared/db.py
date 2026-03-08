"""
PostgreSQL async connection pool using asyncpg.
All services use get_db() as an async context manager.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

_pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Sites registry
CREATE TABLE IF NOT EXISTS sites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain      TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    start_url   TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    schedule    TEXT DEFAULT '0 */6 * * *',
    max_pages   INT DEFAULT 100,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- CSS selector cache (core cost optimization)
CREATE TABLE IF NOT EXISTS site_selectors (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain                    TEXT UNIQUE NOT NULL,
    article_links_selector    TEXT DEFAULT '',
    pagination_next_selector  TEXT DEFAULT '',
    article_body_selector     TEXT DEFAULT '',
    article_title_selector    TEXT DEFAULT '',
    article_date_selector     TEXT DEFAULT '',
    author_selector           TEXT DEFAULT '',
    confidence                FLOAT DEFAULT 0.0,
    llm_model                 TEXT DEFAULT '',
    created_at                TIMESTAMPTZ DEFAULT NOW(),
    updated_at                TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_selectors_domain ON site_selectors(domain);
CREATE INDEX IF NOT EXISTS idx_selectors_updated ON site_selectors(updated_at);

-- Scrape job audit trail
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id      UUID REFERENCES sites(id) ON DELETE CASCADE,
    node_id      TEXT,
    status       TEXT CHECK(status IN ('queued','running','done','failed')) DEFAULT 'queued',
    pages_found  INT DEFAULT 0,
    pages_ok     INT DEFAULT 0,
    pages_failed INT DEFAULT 0,
    llm_calls    INT DEFAULT 0,
    selector_cache_hits INT DEFAULT 0,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    error_msg    TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_jobs_site ON scrape_jobs(site_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON scrape_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON scrape_jobs(created_at);

-- Scraper node registry
CREATE TABLE IF NOT EXISTS scraper_nodes (
    node_id     TEXT PRIMARY KEY,
    hostname    TEXT,
    ip_address  TEXT,
    status      TEXT DEFAULT 'idle',
    jobs_done   INT DEFAULT 0,
    last_seen   TIMESTAMPTZ DEFAULT NOW()
);

-- robots.txt cache (legal compliance)
CREATE TABLE IF NOT EXISTS robots_cache (
    domain      TEXT PRIMARY KEY,
    content     TEXT,
    fetched_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Deduplication: tracks every URL already scraped to avoid re-scraping on restart
CREATE TABLE IF NOT EXISTS scraped_urls (
    url         TEXT PRIMARY KEY,
    domain      TEXT NOT NULL,
    scraped_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scraped_domain ON scraped_urls(domain);

-- Per-domain fetch strategy — stores best discovered method to avoid re-detection
CREATE TABLE IF NOT EXISTS site_strategies (
    domain                TEXT PRIMARY KEY,
    fetch_method          TEXT NOT NULL DEFAULT 'playwright',
    is_spa                BOOLEAN DEFAULT FALSE,
    use_infinite_scroll   BOOLEAN DEFAULT TRUE,
    scroll_rounds         INT DEFAULT 8,
    discovered_at         TIMESTAMPTZ DEFAULT NOW(),
    last_used_at          TIMESTAMPTZ DEFAULT NOW(),
    notes                 TEXT DEFAULT ''
);

-- Comprehensive per-domain knowledge base (self-learning, grows with each run)
CREATE TABLE IF NOT EXISTS site_knowledge (
    domain                      TEXT PRIMARY KEY,
    -- Fetch strategy (learned from probing)
    preferred_fetch_method      TEXT DEFAULT 'playwright',
    is_spa                      BOOLEAN DEFAULT FALSE,
    use_infinite_scroll         BOOLEAN DEFAULT TRUE,
    navigation_strategy         TEXT DEFAULT 'domcontentloaded',
    requires_js                 BOOLEAN DEFAULT TRUE,
    -- WAF / anti-bot signals
    has_cloudflare              BOOLEAN DEFAULT FALSE,
    has_datadome                BOOLEAN DEFAULT FALSE,
    has_recaptcha               BOOLEAN DEFAULT FALSE,
    block_rate                  FLOAT DEFAULT 0.0,
    -- Content structure
    has_paywall                 BOOLEAN DEFAULT FALSE,
    has_comments                BOOLEAN DEFAULT FALSE,
    comment_selector            TEXT DEFAULT '',
    -- Metadata signals (present on first success, guides fast-path extraction)
    has_jsonld                  BOOLEAN DEFAULT FALSE,
    has_og_meta                 BOOLEAN DEFAULT FALSE,
    -- Selector reliability
    selector_failure_count      INT DEFAULT 0,
    last_selector_rediscovery   TIMESTAMPTZ,
    -- Performance statistics
    total_scraped               INT DEFAULT 0,
    success_rate                FLOAT DEFAULT 1.0,
    avg_article_word_count      INT DEFAULT 0,
    avg_fetch_latency_ms        INT DEFAULT 0,
    -- Timestamps
    first_scraped_at            TIMESTAMPTZ DEFAULT NOW(),
    last_scraped_at             TIMESTAMPTZ DEFAULT NOW(),
    notes                       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_knowledge_last_scraped ON site_knowledge(last_scraped_at);

-- Persistent article storage — every successfully extracted article is saved here
CREATE TABLE IF NOT EXISTS scraped_articles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url             TEXT UNIQUE NOT NULL,
    canonical_url   TEXT,
    domain          TEXT NOT NULL,
    title           TEXT,
    author          TEXT,
    published_date  TEXT,
    language        TEXT,
    content         TEXT,
    summary         TEXT,
    word_count      INT DEFAULT 0,
    overall_score   FLOAT DEFAULT 0.0,
    fetch_method    TEXT DEFAULT 'playwright',
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    raw             JSONB
);
CREATE INDEX IF NOT EXISTS idx_articles_domain ON scraped_articles(domain);
CREATE INDEX IF NOT EXISTS idx_articles_published ON scraped_articles(published_date);
CREATE INDEX IF NOT EXISTS idx_articles_scraped ON scraped_articles(scraped_at);
"""


async def init_pool() -> None:
    """Initialize the connection pool. Call once at service startup."""
    global _pool
    dsn = os.getenv("POSTGRES_DSN", "postgresql://scraper:scraper@localhost:5432/scraperdb")
    pool_size = int(os.getenv("POSTGRES_POOL_SIZE", "10"))
    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=2,
        max_size=pool_size,
        command_timeout=30,
    )


async def close_pool() -> None:
    """Close pool on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Async context manager yielding a connection from the pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    async with _pool.acquire() as conn:
        yield conn


async def run_schema() -> None:
    """Create all tables (idempotent)."""
    async with get_db() as conn:
        await conn.execute(SCHEMA_SQL)


async def get_pool() -> asyncpg.Pool:
    """Return the raw pool (for bulk operations)."""
    if _pool is None:
        raise RuntimeError("Pool not initialized.")
    return _pool


async def upsert_site(domain: str, start_url: str) -> None:
    """Register a site in the sites table on first scrape (idempotent)."""
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO sites (domain, name, start_url)
            VALUES ($1, $2, $3)
            ON CONFLICT (domain) DO NOTHING
            """,
            domain,
            domain,  # use domain as name initially
            start_url,
        )


async def filter_unscraped_urls(urls: list[str]) -> list[str]:
    """Return only URLs not yet present in scraped_urls."""
    if not urls:
        return []
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT url FROM scraped_urls WHERE url = ANY($1::text[])",
            urls,
        )
    already = {r["url"] for r in rows}
    return [u for u in urls if u not in already]


async def mark_urls_scraped(domain: str, urls: list[str]) -> None:
    """Insert scraped URLs into the dedup table (ignore conflicts)."""
    if not urls:
        return
    async with get_db() as conn:
        await conn.executemany(
            "INSERT INTO scraped_urls (url, domain) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            [(u, domain) for u in urls],
        )


async def get_site_strategy(domain: str) -> dict | None:
    """Load stored fetch strategy for a domain. Returns None if not yet discovered."""
    try:
        async with get_db() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM site_strategies WHERE domain = $1", domain
            )
        return dict(row) if row else None
    except Exception:
        return None


async def upsert_site_strategy(
    domain: str,
    fetch_method: str,
    is_spa: bool = False,
    use_infinite_scroll: bool = True,
    scroll_rounds: int = 8,
    notes: str = "",
) -> None:
    """Store or update the fetch strategy for a domain."""
    try:
        async with get_db() as conn:
            await conn.execute(
                """
                INSERT INTO site_strategies
                    (domain, fetch_method, is_spa, use_infinite_scroll, scroll_rounds, notes, last_used_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (domain) DO UPDATE SET
                    fetch_method        = EXCLUDED.fetch_method,
                    is_spa              = EXCLUDED.is_spa,
                    use_infinite_scroll = EXCLUDED.use_infinite_scroll,
                    scroll_rounds       = EXCLUDED.scroll_rounds,
                    notes               = EXCLUDED.notes,
                    last_used_at        = NOW()
                """,
                domain, fetch_method, is_spa, use_infinite_scroll, scroll_rounds, notes,
            )
    except Exception as exc:
        from shared.logging import get_logger
        get_logger("db").warning("site_strategy_upsert_failed", domain=domain, error=str(exc))


# ── site_knowledge helpers ─────────────────────────────────────────────────────

async def get_site_knowledge(domain: str) -> dict | None:
    """Load all stored knowledge about a domain. Returns None if unknown."""
    try:
        async with get_db() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM site_knowledge WHERE domain = $1", domain
            )
        return dict(row) if row else None
    except Exception:
        return None


async def upsert_site_knowledge(domain: str, **fields) -> None:
    """
    Create or partially update site knowledge for a domain.
    Only the provided keyword arguments are updated (others retain existing values).
    """
    if not fields:
        return
    try:
        async with get_db() as conn:
            # Build SET clause from provided fields
            set_parts = [f"{k} = ${i+2}" for i, k in enumerate(fields)]
            values = list(fields.values())
            await conn.execute(
                f"""
                INSERT INTO site_knowledge (domain, {', '.join(fields.keys())})
                VALUES ($1, {', '.join(f'${i+2}' for i in range(len(fields)))})
                ON CONFLICT (domain) DO UPDATE SET
                    {', '.join(set_parts)},
                    last_scraped_at = NOW()
                """,
                domain, *values,
            )
    except Exception as exc:
        from shared.logging import get_logger
        get_logger("db").warning("site_knowledge_upsert_failed", domain=domain, error=str(exc))


async def increment_scraped_count(domain: str, success: bool = True) -> None:
    """Atomically increment total_scraped and update success_rate for a domain."""
    try:
        async with get_db() as conn:
            if success:
                await conn.execute(
                    """
                    INSERT INTO site_knowledge (domain, total_scraped, success_rate, last_scraped_at)
                    VALUES ($1, 1, 1.0, NOW())
                    ON CONFLICT (domain) DO UPDATE SET
                        total_scraped   = site_knowledge.total_scraped + 1,
                        last_scraped_at = NOW()
                    """,
                    domain,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO site_knowledge (domain, total_scraped, success_rate, last_scraped_at)
                    VALUES ($1, 1, 0.0, NOW())
                    ON CONFLICT (domain) DO UPDATE SET
                        total_scraped   = site_knowledge.total_scraped + 1,
                        success_rate    = (
                            site_knowledge.success_rate * site_knowledge.total_scraped
                        ) / (site_knowledge.total_scraped + 1),
                        last_scraped_at = NOW()
                    """,
                    domain,
                )
    except Exception:
        pass


# ── scraped_articles helpers ───────────────────────────────────────────────────

async def save_article(article: dict) -> bool:
    """
    Persist a single article to scraped_articles (idempotent — ON CONFLICT DO NOTHING).
    Returns True if the article was newly inserted, False if it already existed.
    """
    import json as _json
    try:
        async with get_db() as conn:
            result = await conn.execute(
                """
                INSERT INTO scraped_articles (
                    url, canonical_url, domain, title, author,
                    published_date, language, content, summary,
                    word_count, overall_score, fetch_method, scraped_at, raw
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW(),$13)
                ON CONFLICT (url) DO NOTHING
                """,
                article.get("url", ""),
                article.get("canonical_url"),
                article.get("domain", ""),
                article.get("title"),
                article.get("author"),
                article.get("published_date"),
                article.get("language"),
                article.get("content", ""),
                article.get("summary"),
                article.get("word_count", 0),
                article.get("overall_score", 0.0),
                article.get("fetch_method", "playwright"),
                _json.dumps(article, ensure_ascii=False, default=str),
            )
        return result == "INSERT 0 1"
    except Exception as exc:
        from shared.logging import get_logger
        get_logger("db").warning("article_save_failed", url=article.get("url"), error=str(exc))
        return False
