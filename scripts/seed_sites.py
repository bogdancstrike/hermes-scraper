"""
Seed the database with example site configurations.
Run: python scripts/seed_sites.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.db import init_pool, close_pool, run_schema, get_db
from shared.logging import configure_logging, get_logger

configure_logging("seed")
logger = get_logger("seed")

EXAMPLE_SITES = [
    {
        "domain": "news.ycombinator.com",
        "name": "Hacker News",
        "start_url": "https://news.ycombinator.com",
        "schedule": "0 */2 * * *",
        "max_pages": 3,
    },
    {
        "domain": "lobste.rs",
        "name": "Lobsters",
        "start_url": "https://lobste.rs",
        "schedule": "0 */4 * * *",
        "max_pages": 2,
    },
    {
        "domain": "dev.to",
        "name": "DEV Community",
        "start_url": "https://dev.to",
        "schedule": "0 */6 * * *",
        "max_pages": 5,
    },
    {
        "domain": "biziday.ro",
        "name": "Biziday",
        "start_url": "https://www.biziday.ro",
        "schedule": "0 */2 * * *",
        "max_pages": 3,
    },
    {
        "domain": "adevarul.ro",
        "name": "Adevarul",
        "start_url": "https://adevarul.ro",
        "schedule": "0 */2 * * *",
        "max_pages": 3,
    },
]


async def seed():
    await init_pool()
    await run_schema()

    async with get_db() as conn:
        for site in EXAMPLE_SITES:
            await conn.execute(
                """
                INSERT INTO sites (domain, name, start_url, schedule, max_pages)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (domain) DO UPDATE SET
                    name = EXCLUDED.name,
                    start_url = EXCLUDED.start_url,
                    schedule = EXCLUDED.schedule,
                    max_pages = EXCLUDED.max_pages
                """,
                site["domain"], site["name"], site["start_url"],
                site["schedule"], site["max_pages"],
            )
            logger.info("site_seeded", domain=site["domain"])

    logger.info("seeding_complete", count=len(EXAMPLE_SITES))
    await close_pool()


if __name__ == "__main__":
    asyncio.run(seed())
