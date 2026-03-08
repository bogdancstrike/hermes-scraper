"""
Content processing pipeline.
Transforms raw HTML pages into structured articles using trafilatura extraction.
No LLM calls — metadata (title, author, date, language) is extracted directly from HTML.
"""
from __future__ import annotations

import time

from processing.filters.deduplicator import Deduplicator
from processing.filters.extractor import extract_main_content
from shared.kafka import KafkaProducerClient, TOPIC_OUTPUT
from shared.logging import get_logger
from shared.metrics import pages_processed_total, es_index_total
from shared.models import RawHtmlPage, ScrapedArticle

logger = get_logger("pipeline")


class ContentPipeline:
    """
    Orchestrates the processing pipeline:
    1. Extract main content + metadata from HTML (trafilatura)
    2. Deduplicate via SimHash (Redis-backed)
    3. Emit structured article to Kafka (→ Elasticsearch)
    """

    def __init__(
        self,
        deduplicator: Deduplicator,
        kafka_producer: KafkaProducerClient,
    ):
        self.dedup = deduplicator
        self.producer = kafka_producer

    async def process(self, raw_page: RawHtmlPage) -> ScrapedArticle | None:
        """
        Full pipeline: HTML → structured article.
        Returns None if page is skipped (dedup or too short).
        """
        # Step 1: Extract main content + metadata
        result = extract_main_content(raw_page.html, url=raw_page.url)
        if not result:
            pages_processed_total.labels(status="skipped_short").inc()
            logger.debug("page_skipped_short", url=raw_page.url)
            return None

        text = result["text"]

        # Step 2: Near-dedup check
        is_dup = await self.dedup.is_duplicate(text, raw_page.url)
        if is_dup:
            pages_processed_total.labels(status="skipped_dedup").inc()
            logger.debug("page_skipped_dedup", url=raw_page.url)
            return None

        pages_processed_total.labels(status="extracted").inc()

        # Step 3: Build structured article from trafilatura metadata
        article = ScrapedArticle(
            job_id=raw_page.job_id,
            page_id=raw_page.page_id,
            source=raw_page.domain,
            url=raw_page.url,
            content=text,
            title=result.get("title"),
            author=result.get("author"),
            published_date=result.get("date"),
            language=result.get("language"),
        )

        # Step 4: Emit to Kafka → Elasticsearch
        await self.producer.send(
            TOPIC_OUTPUT,
            value=article.model_dump(),
            key=article.source,
        )
        logger.info(
            "article_extracted",
            url=raw_page.url,
            domain=raw_page.domain,
            title=article.title or "(no title)",
        )

        return article
