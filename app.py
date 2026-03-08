#!/usr/bin/env python3
"""
app.py — Standalone scraper CLI

Usage:
    python3 app.py --website adevarul.ro
    python3 app.py --website biziday.ro --pages 5 --articles 30
    python3 app.py --website euronews.ro --output results/

Flow:
  1. Load site knowledge from PostgreSQL (strategy, selectors, past stats).
  2. Render listing pages with Playwright (full JavaScript execution).
  3. Get CSS selectors from PostgreSQL cache (L1=Redis, L2=PG).
       If cached selectors fail live validation → retry LLM up to RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS times.
  4. Discover site sections from homepage navigation.
  5. Collect article URLs from all sections (pagination + infinite scroll).
  6. For each article: use known strategy (static/playwright) or probe on first run.
  7. Extract with multi-source extractor (JSON-LD + OG + htmldate + trafilatura).
  8. Save article to PostgreSQL immediately after extraction (idempotent).
  9. Apply enrichments if configured: emails, hashtags, screenshot.
 10. Export final results to JSON + CSV in output/{domain}/.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Bootstrap: load .env before any module-level config reads ─────────────────
_env = Path(__file__).parent / ".env"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)

# Suppress noisy startup logs unless explicitly requested
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("LOG_FORMAT", "console")

# ── Application imports ───────────────────────────────────────────────────────
from scraper.config import config
from scraper.engines.browser_engine import BrowserEngine
from scraper.navigation.paginator import SiteNavigator
from scraper.selector_client import SelectorClient
from scraper.fetchers.static_fetcher import fetch_static
from scraper.detectors.anti_bot import is_blocked
from scraper.knowledge.site_knowledge import SiteKnowledgeRepository, STRATEGY_STATIC, STRATEGY_PLAYWRIGHT
from processing.filters.extractor import extract_main_content
from shared.article_store import ArticleStore
from shared.db import (
    init_pool, close_pool, run_schema,
    upsert_site, filter_unscraped_urls, mark_urls_scraped,
    get_site_strategy, upsert_site_strategy,
)
from shared.logging import get_logger
from shared.url_utils import canonicalize_url, extract_domain

logger = get_logger("app")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))


# ── LLM client (lazy — only instantiated when a selector cache miss occurs) ───

def _build_llm_client():
    """
    Build a direct LLMClient if any API key is configured.
    Returns None if no LLM is configured (selectors will only use cached values).
    """
    has_key = (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("LLM_BASE_URL")
    )
    if not has_key:
        logger.warning(
            "no_llm_configured",
            hint="Set ANTHROPIC_API_KEY (or OPENAI_API_KEY / LLM_BASE_URL) in .env "
                 "to enable automatic selector discovery when cache misses occur.",
        )
        return None
    try:
        from llm_api.llm_client import LLMClient
        return LLMClient()
    except Exception as exc:
        logger.warning("llm_client_init_failed", error=str(exc))
        return None


# ── Database (optional — graceful degradation if unavailable) ─────────────────

async def _init_db() -> bool:
    """Try to connect to PostgreSQL. Returns True if successful."""
    try:
        await init_pool()
        await run_schema()
        logger.info("db_connected")
        return True
    except Exception as exc:
        logger.warning(
            "db_unavailable",
            error=str(exc),
            hint="Selector cache disabled. Start PostgreSQL or set POSTGRES_DSN.",
        )
        return False


# ── Enrichment helpers ────────────────────────────────────────────────────────

def _enrich_article(article: dict, html: str) -> dict:
    """Apply optional enrichments (emails, hashtags) based on config flags."""
    text = article.get("content", "")

    if config.extract_emails:
        from processing.enrichers.email_extractor import extract_emails
        article["emails"] = extract_emails(text, html)

    if config.extract_hashtags:
        from processing.enrichers.hashtag_extractor import extract_hashtags
        article["hashtags"] = extract_hashtags(text, html)

    return article


# ── Core scrape function ───────────────────────────────────────────────────────

async def scrape_website(
    domain: str,
    max_pages: int,
    max_articles: int,
    output_dir: Path,
) -> list[dict]:
    """
    Full scrape pipeline for one website:
      knowledge load → selector probe/discovery → article collection → extract → persist.
    """
    # Normalise domain: strip protocol and trailing slashes
    domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
    start_url = f"https://{domain}"

    logger.info("scrape_start", domain=domain, start_url=start_url,
                max_pages=max_pages, max_articles=max_articles)

    db_ok = await _init_db()

    if db_ok:
        await upsert_site(domain, start_url)

    # Per-domain knowledge repository
    knowledge = SiteKnowledgeRepository(db_ok=db_ok)
    site_profile = await knowledge.load(domain)

    logger.info(
        "site_knowledge_loaded",
        domain=domain,
        known=site_profile.is_known,
        total_scraped=site_profile.total_scraped,
        preferred_method=site_profile.preferred_fetch_method,
    )

    # Direct LLM client — only instantiated once, shared across all selector lookups
    llm_client = _build_llm_client()

    # SelectorClient: PG cache (L1=Redis, L2=PG) → probe → LLM fallback
    selector_client = SelectorClient(llm_client=llm_client)

    # Article store — saves to DB + optional NDJSON file
    ndjson_dir = output_dir / domain
    ndjson_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ndjson_path = ndjson_dir / f"{ts}.ndjson"
    article_store = ArticleStore(db_ok=db_ok, ndjson_path=ndjson_path)

    articles: list[dict] = []

    async with BrowserEngine() as browser:
        # ── Phase 1: Discover section URLs + collect article URLs ──────────────
        navigator = SiteNavigator(
            engine=browser,
            selector_client=selector_client,
            max_sections=config.max_sections,
            max_pages_per_section=max_pages,
        )

        logger.info("collecting_article_urls", domain=domain)
        article_urls = await navigator.collect_all_article_urls(start_url, domain)

        if not article_urls:
            logger.warning("no_article_urls_found", domain=domain)
            article_store.close()
            if db_ok:
                await close_pool()
            return []

        # Canonicalize URLs to strip tracking params before dedup
        article_urls = [canonicalize_url(u) for u in article_urls]
        article_urls = list(dict.fromkeys(article_urls))  # deduplicate

        if db_ok:
            article_urls = await filter_unscraped_urls(article_urls)
            if not article_urls:
                logger.info("all_urls_already_scraped", domain=domain)
                article_store.close()
                await close_pool()
                return []

        article_urls = article_urls[:max_articles]
        logger.info("article_urls_collected", domain=domain, count=len(article_urls))

        # ── Phase 2: Fetch each article + extract + persist immediately ────────
        sem = asyncio.Semaphore(config.concurrency)

        async def fetch_and_extract(url: str) -> dict | None:
            async with sem:
                canonical = canonicalize_url(url)
                html = ""
                fetch_method = STRATEGY_PLAYWRIGHT
                fetch_latency_ms = 0
                screenshot_path: str | None = None

                # Determine strategy from knowledge (static vs playwright)
                recommended = site_profile.recommend_fetch_method()

                start_t = time.monotonic()

                # Try static fetch if recommended or unknown
                if recommended == STRATEGY_STATIC or not site_profile.is_known:
                    try:
                        static_result = await fetch_static(canonical)
                        if not is_blocked(static_result["block_signals"]) and len(static_result["html"]) > 500:
                            html = static_result["html"]
                            fetch_method = STRATEGY_STATIC
                            fetch_latency_ms = static_result["latency_ms"]
                            logger.debug("article_fetched_static", url=url)
                            # Learn: static works for this domain
                            await knowledge.record_static_success(domain)
                    except Exception as exc:
                        logger.debug("static_fetch_skipped", url=url, error=str(exc))

                # Fall back to Playwright if static failed or was blocked
                if not html:
                    try:
                        start_t = time.monotonic()
                        if config.capture_screenshot:
                            slug = re.sub(r'[^a-zA-Z0-9\-_]', '_', canonical.split("/")[-1] or "article")[:80]
                            date_str = datetime.utcnow().strftime("%Y%m%d")
                            ext = "jpg" if config.screenshot_type == "jpeg" else "png"
                            s_path = str(output_dir / domain / "screenshots" / date_str / f"{slug}.{ext}")
                            html = await browser.get_with_screenshot(
                                url, s_path,
                                wait_for=config.navigation_strategy,
                                screenshot_type=config.screenshot_type,
                            )
                            screenshot_path = s_path
                        else:
                            html = await browser.get(url, wait_for=config.navigation_strategy)
                        fetch_latency_ms = int((time.monotonic() - start_t) * 1000)
                        fetch_method = STRATEGY_PLAYWRIGHT
                        logger.debug("article_fetched_playwright", url=url)
                    except Exception as exc:
                        logger.warning("article_fetch_failed", url=url, error=str(exc))
                        await knowledge.record_article_fetched(
                            domain, STRATEGY_PLAYWRIGHT, 0, 0, success=False
                        )
                        return None

                result = extract_main_content(html, url)
                if not result:
                    logger.debug("article_no_content", url=url)
                    await knowledge.record_article_fetched(
                        domain, fetch_method, fetch_latency_ms, 0, success=False
                    )
                    return None

                # Quality gate: skip articles below min title length
                title = result.get("title") or ""
                if len(title) < config.min_title_length:
                    logger.debug("article_title_too_short", url=url, title=title)
                    return None

                word_count = result.get("word_count", 0)

                article: dict = {
                    "url": url,
                    "canonical_url": result.get("canonical_url") or canonical,
                    "domain": domain,
                    "title": title,
                    "author": result.get("author"),
                    "authors": result.get("authors", []),
                    "published_date": result.get("date"),
                    "updated_date": result.get("updated_date"),
                    "language": result.get("language"),
                    "content": result.get("text", ""),
                    "summary": result.get("summary"),
                    "top_image": result.get("top_image"),
                    "tags": result.get("tags", []),
                    "keywords": result.get("keywords", []),
                    "publisher": result.get("publisher"),
                    "article_type": result.get("article_type"),
                    "word_count": word_count,
                    "reading_time_minutes": result.get("reading_time_minutes", 1),
                    "scraped_at": datetime.utcnow().isoformat(),
                    "fetch_method": fetch_method,
                    "fetch_latency_ms": fetch_latency_ms,
                    "overall_score": result.get("overall_score", 0.0),
                    "title_score": result.get("title_score", 0.0),
                    "content_score": result.get("content_score", 0.0),
                    "date_score": result.get("date_score", 0.0),
                    "author_score": result.get("author_score", 0.0),
                    "likely_paywalled": result.get("likely_paywalled", False),
                    "likely_liveblog": result.get("likely_liveblog", False),
                    "field_sources": result.get("field_sources", {}),
                    "field_confidence": result.get("field_confidence", {}),
                }

                if screenshot_path:
                    article["screenshot_path"] = screenshot_path

                # Optional enrichments
                article = _enrich_article(article, html)

                # Update site knowledge with metadata signals
                await knowledge.record_metadata_signals(
                    domain,
                    has_jsonld="jsonld" in result.get("field_sources", {}).values(),
                    has_og_meta="og" in result.get("field_sources", {}).values(),
                )
                await knowledge.record_article_fetched(
                    domain, fetch_method, fetch_latency_ms, word_count,
                    success=True,
                    block_signals=result.get("block_signals", []),
                )

                # ── Persist immediately ────────────────────────────────────────
                await article_store.save(article)

                return article

        tasks = [fetch_and_extract(url) for url in article_urls]
        results = await asyncio.gather(*tasks)
        articles = [r for r in results if r is not None]

        if db_ok and articles:
            scraped = [a["url"] for a in articles]
            await mark_urls_scraped(domain, scraped)

    logger.info("scrape_done", domain=domain, total_articles=len(articles))

    article_store.close()
    await selector_client.close()

    if db_ok:
        await close_pool()

    return articles


# ── Export ────────────────────────────────────────────────────────────────────

def export_results(articles: list[dict], domain: str, output_dir: Path) -> dict[str, Path]:
    """Write JSON + CSV output files into output/{domain}/ subdirectory."""
    domain_dir = output_dir / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base = domain_dir / ts
    exported = {}

    # JSON — full data
    json_path = Path(str(base) + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"domain": domain, "scraped_at": datetime.utcnow().isoformat(),
             "total": len(articles), "articles": articles},
            f, ensure_ascii=False, indent=2,
        )
    exported["json"] = json_path

    # CSV — summary
    csv_path = Path(str(base) + ".csv")
    fields = ["url", "domain", "title", "author", "published_date", "language",
              "word_count", "overall_score", "fetch_method", "scraped_at"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(articles)
    exported["csv"] = csv_path

    return exported


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape a website: Playwright render → selector cache/probe → trafilatura extract",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 app.py --website adevarul.ro
  python3 app.py --website biziday.ro --pages 5 --articles 50
  python3 app.py --website euronews.ro --output results/

Environment:
  ANTHROPIC_API_KEY   Enable Claude for automatic selector discovery
  POSTGRES_DSN        PostgreSQL for selector cache (default: local)
  REDIS_URL           Redis for L1 selector cache (optional)
  SCRAPE_LIMIT        Max articles per run (default: 100)
  CAPTURE_SCREENSHOT  Save full-page screenshots (True/False)
  EXTRACT_EMAILS      Extract emails from articles (True/False)
  EXTRACT_HASHTAGS    Extract hashtags from articles (True/False)
        """,
    )
    parser.add_argument(
        "--website", "-w",
        required=True,
        metavar="DOMAIN",
        help="Domain to scrape (e.g. adevarul.ro)",
    )
    parser.add_argument(
        "--pages", "-p",
        type=int,
        default=int(os.getenv("SCRAPER_MAX_PAGES", "5")),
        metavar="N",
        help="Max listing pages to traverse per section (default: 5)",
    )
    parser.add_argument(
        "--articles", "-a",
        type=int,
        default=config.scrape_limit,
        metavar="N",
        help=f"Max articles to scrape in total (default: {config.scrape_limit})",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(OUTPUT_DIR),
        metavar="DIR",
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    output_dir = Path(args.output)

    print(f"\n  Website : {args.website}")
    print(f"  Pages   : {args.pages} per section")
    print(f"  Articles: {args.articles} max")
    print(f"  Output  : {output_dir.resolve()}")
    if config.capture_screenshot:
        print(f"  Screenshots: enabled ({config.screenshot_type})")
    if config.extract_emails:
        print(f"  Email extraction: enabled")
    if config.extract_hashtags:
        print(f"  Hashtag extraction: enabled")
    print()

    articles = await scrape_website(
        domain=args.website,
        max_pages=args.pages,
        max_articles=args.articles,
        output_dir=output_dir,
    )

    if not articles:
        print("\n  No articles scraped. Check logs for details.\n")
        return 1

    exported = export_results(articles, args.website, output_dir)

    print(f"\n  Scraped {len(articles)} articles from {args.website}")
    for fmt, path in exported.items():
        print(f"  [{fmt.upper()}] {path}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
