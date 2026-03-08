"""
Scraper node entry point.

Consumes ScrapeJob messages from Kafka and for each job:
  1. Renders the site's base URL with a headless browser (Playwright by default).
  2. Discovers all section / category URLs from homepage navigation.
  3. For each section: scrolls / paginates to collect article URLs.
     CSS selectors are fetched from Redis → PostgreSQL → LLM (in that order).
     Selectors are validated against real page HTML; broken ones trigger LLM
     re-discovery automatically.
  4. Fetches every article page and stores raw HTML to MinIO.
  5. Emits RawHtmlPage messages to the processing layer via Kafka.

Each node joins a unique Kafka consumer group (scraper-nodes-{node_id}) so
every active node independently processes all available jobs.

Run with:  python -m scraper.main
"""
from __future__ import annotations

import asyncio
import signal
import time
import uuid

from scraper.config import config
from scraper.engines.browser_engine import BrowserEngine
from scraper.engines.http_engine import BlockedError, HttpEngine
from scraper.navigation.paginator import SiteNavigator
from scraper.selector_client import SelectorClient
from scraper.storage.kafka_producer import ScraperProducer
from scraper.storage.raw_store import RawStore
from shared.db import close_pool, get_db, init_pool
from shared.kafka import (
    TOPIC_JOBS,
    KafkaProducerClient,
    consume_loop,
    create_consumer,
)
from shared.logging import configure_logging, get_logger
from shared.metrics import active_jobs, jobs_completed_total, start_metrics_server
from shared.models import RawHtmlPage, ScrapeJob

configure_logging("scraper")
logger = get_logger("scraper.main", node_id=config.node_id)

_stop_event = asyncio.Event()


async def process_job(
    job: ScrapeJob,
    selector_client: SelectorClient,
    producer: ScraperProducer,
    raw_store: RawStore,
) -> None:
    """
    Execute a single scrape job end-to-end:
      1. Open a browser context (or HTTP engine if headless disabled).
      2. Use SiteNavigator to discover sections and collect all article URLs.
      3. Fetch each article, archive HTML to MinIO, emit to Kafka.
    """
    active_jobs.inc()
    start = time.monotonic()
    pages_ok = 0
    pages_failed = 0

    logger.info("job_started", job_id=job.job_id, domain=job.domain)

    try:
        # Build the appropriate engine
        if config.use_headless:
            engine_ctx = BrowserEngine()
        else:
            engine_ctx = HttpEngine()

        async with engine_ctx as engine:
            navigator = SiteNavigator(
                engine=engine,
                selector_client=selector_client,
                max_sections=config.max_sections,
                max_pages_per_section=min(job.max_pages, 10),
                scroll_max=config.scroll_max,
                scroll_wait_ms=config.scroll_wait_ms,
            )

            # Discover sections + collect all article URLs across the whole site
            article_urls = await navigator.collect_all_article_urls(
                base_url=job.start_url,
                domain=job.domain,
            )

            logger.info(
                "article_urls_collected",
                job_id=job.job_id,
                domain=job.domain,
                total_urls=len(article_urls),
            )

            # Fetch each article with bounded concurrency
            sem = asyncio.Semaphore(config.concurrency)

            async def fetch_and_emit(url: str) -> None:
                nonlocal pages_ok, pages_failed
                async with sem:
                    try:
                        # Validate / get selectors for this article page
                        html = await engine.get(url, domain=job.domain)

                        # Opportunistically validate article-page selectors
                        await selector_client.get_or_discover(
                            domain=job.domain,
                            sample_url=url,
                            html=html,
                            page_type="article",
                        )

                    except BlockedError:
                        # If HTTP engine blocked, escalate to browser
                        if not config.use_headless:
                            try:
                                async with BrowserEngine() as browser:
                                    html = await browser.get(url)
                            except Exception as exc:
                                logger.error(
                                    "browser_fallback_failed", url=url, error=str(exc)
                                )
                                pages_failed += 1
                                return
                        else:
                            pages_failed += 1
                            return
                    except Exception as exc:
                        logger.warning("article_fetch_failed", url=url, error=str(exc))
                        pages_failed += 1
                        return

                    page_id = str(uuid.uuid4())

                    # Archive raw HTML to MinIO (non-fatal on failure)
                    try:
                        raw_store.store(page_id, job.domain, url, html)
                    except Exception as exc:
                        logger.warning("minio_store_failed", url=url, error=str(exc))

                    # Emit to processing layer
                    page = RawHtmlPage(
                        job_id=job.job_id,
                        page_id=page_id,
                        domain=job.domain,
                        url=url,
                        html=html,
                        html_size_bytes=len(html.encode()),
                    )
                    await producer.emit_raw_page(page)
                    pages_ok += 1

            await asyncio.gather(
                *[fetch_and_emit(url) for url in article_urls[: job.max_pages]]
            )

        duration = time.monotonic() - start
        await _update_job_record(job, "done", pages_ok, pages_failed, duration)
        jobs_completed_total.labels(status="done").inc()
        logger.info(
            "job_done",
            job_id=job.job_id,
            domain=job.domain,
            pages_ok=pages_ok,
            pages_failed=pages_failed,
            duration_s=round(duration, 1),
        )

    except Exception as exc:
        duration = time.monotonic() - start
        await _update_job_record(job, "failed", pages_ok, pages_failed, duration, str(exc))
        jobs_completed_total.labels(status="failed").inc()
        logger.error(
            "job_failed",
            job_id=job.job_id,
            domain=job.domain,
            error=str(exc),
            exc_info=True,
        )
    finally:
        active_jobs.dec()


async def _update_job_record(
    job: ScrapeJob,
    status: str,
    pages_ok: int,
    pages_failed: int,
    duration: float,
    error_msg: str | None = None,
) -> None:
    try:
        async with get_db() as conn:
            await conn.execute(
                """
                UPDATE scrape_jobs SET
                    status=$1, pages_ok=$2, pages_failed=$3,
                    finished_at=NOW(), error_msg=$4
                WHERE id=$5::uuid
                """,
                status,
                pages_ok,
                pages_failed,
                error_msg,
                job.job_id,
            )
    except Exception as exc:
        logger.warning("job_record_update_failed", error=str(exc))


async def main() -> None:
    """Scraper node entry point."""
    logger.info("scraper_node_starting", node_id=config.node_id, headless=config.use_headless)

    start_metrics_server(config.metrics_port)
    await init_pool()

    # Register node in the DB
    try:
        import socket
        async with get_db() as conn:
            await conn.execute(
                """
                INSERT INTO scraper_nodes (node_id, hostname, status)
                VALUES ($1, $2, 'running')
                ON CONFLICT (node_id) DO UPDATE SET status='running', last_seen=NOW()
                """,
                config.node_id,
                socket.gethostname(),
            )
    except Exception as exc:
        logger.warning("node_registration_failed", error=str(exc))

    selector_client = SelectorClient()
    raw_store = RawStore()
    await raw_store.ensure_bucket()

    kafka_producer_client = KafkaProducerClient()
    await kafka_producer_client.start()
    producer = ScraperProducer(kafka_producer_client)

    # Each node uses a unique consumer group so every node receives all jobs.
    consumer = await create_consumer(
        topics=[TOPIC_JOBS],
        group_id=f"scraper-nodes-{config.node_id}",
    )

    async def handle_job(msg_value: dict) -> None:
        try:
            job = ScrapeJob(**msg_value)
            await process_job(job, selector_client, producer, raw_store)
        except Exception as exc:
            logger.error("job_handler_error", error=str(exc), exc_info=True)

    def _shutdown(*_):
        logger.info("shutdown_signal_received")
        _stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("scraper_node_ready", node_id=config.node_id)

    try:
        await consume_loop(consumer, handle_job, stop_event=_stop_event)
    finally:
        await kafka_producer_client.stop()
        await close_pool()
        logger.info("scraper_node_stopped")


if __name__ == "__main__":
    asyncio.run(main())
