"""
Scheduler service — emits scrape jobs to Kafka based on site configurations.

Run with:  python -m scheduler.main
"""
from __future__ import annotations

import asyncio
import os
import signal
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.db import close_pool, get_db, init_pool
from shared.kafka import TOPIC_JOBS, KafkaProducerClient
from shared.logging import configure_logging, get_logger
from shared.metrics import start_metrics_server
from shared.models import ScrapeJob

configure_logging("scheduler")
logger = get_logger("scheduler.main")

INTERVAL_SECONDS = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
MAX_CONCURRENT_JOBS = int(os.getenv("SCHEDULER_MAX_CONCURRENT_JOBS", "20"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9093"))

_stop_event = asyncio.Event()
_kafka_producer: KafkaProducerClient | None = None


async def emit_due_jobs() -> None:
    """
    Find sites that are due for scraping (not recently scraped)
    and emit job messages to Kafka.
    """
    try:
        async with get_db() as conn:
            sites = await conn.fetch(
                """
                SELECT s.id, s.domain, s.start_url, s.max_pages
                FROM sites s
                WHERE s.is_active = TRUE
                  AND NOT EXISTS (
                    SELECT 1 FROM scrape_jobs j
                    WHERE j.site_id = s.id
                      AND j.status IN ('queued', 'running')
                      AND j.created_at > NOW() - INTERVAL '1 hour'
                  )
                ORDER BY (
                    SELECT COALESCE(MAX(finished_at), '2000-01-01')
                    FROM scrape_jobs
                    WHERE site_id = s.id
                ) ASC
                LIMIT $1
                """,
                MAX_CONCURRENT_JOBS,
            )

        if not sites:
            logger.debug("no_sites_due")
            return

        logger.info("emitting_jobs", count=len(sites))

        for site in sites:
            job = ScrapeJob(
                job_id=str(uuid.uuid4()),
                site_id=str(site["id"]),
                domain=site["domain"],
                start_url=site["start_url"],
                max_pages=site["max_pages"],
                priority=5,
            )

            # Record job in DB
            async with get_db() as conn:
                await conn.execute(
                    """
                    INSERT INTO scrape_jobs (id, site_id, status, created_at)
                    VALUES ($1::uuid, $2::uuid, 'queued', NOW())
                    """,
                    job.job_id,
                    job.site_id,
                )

            # Emit to Kafka
            if _kafka_producer:
                await _kafka_producer.send(
                    TOPIC_JOBS,
                    value=job.model_dump(),
                    key=job.domain,
                )
                logger.info("job_emitted", domain=job.domain, job_id=job.job_id)

    except Exception as exc:
        logger.error("emit_jobs_error", error=str(exc), exc_info=True)


async def cleanup_stale_jobs() -> None:
    """Mark jobs that have been running too long as failed."""
    try:
        async with get_db() as conn:
            result = await conn.execute(
                """
                UPDATE scrape_jobs
                SET status = 'failed', error_msg = 'timeout', finished_at = NOW()
                WHERE status = 'running'
                  AND started_at < NOW() - INTERVAL '2 hours'
                """
            )
        logger.debug("stale_jobs_cleaned")
    except Exception as exc:
        logger.warning("cleanup_failed", error=str(exc))


async def main() -> None:
    global _kafka_producer

    logger.info("scheduler_starting")
    start_metrics_server(METRICS_PORT)

    await init_pool()

    _kafka_producer = KafkaProducerClient()
    await _kafka_producer.start()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(emit_due_jobs, "interval", seconds=INTERVAL_SECONDS, id="emit_jobs")
    scheduler.add_job(cleanup_stale_jobs, "interval", minutes=15, id="cleanup")
    scheduler.start()

    def _shutdown(*_):
        logger.info("shutdown_signal_received")
        _stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("scheduler_ready", interval_seconds=INTERVAL_SECONDS)
    await _stop_event.wait()

    scheduler.shutdown()
    if _kafka_producer:
        await _kafka_producer.stop()
    await close_pool()
    logger.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
