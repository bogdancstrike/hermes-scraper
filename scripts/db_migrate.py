"""
Run database schema creation (idempotent).
Run: python scripts/db_migrate.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.db import init_pool, close_pool, run_schema
from shared.logging import configure_logging, get_logger

configure_logging("migrate")
logger = get_logger("migrate")


async def main():
    logger.info("running_migrations")
    await init_pool()
    await run_schema()
    await close_pool()
    logger.info("migrations_complete")


if __name__ == "__main__":
    asyncio.run(main())
