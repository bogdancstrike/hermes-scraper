"""
Content processing service entry point.
Consumes raw HTML from Kafka, extracts text + metadata, deduplicates, stores to Elasticsearch.
No LLM calls — trafilatura handles all extraction.

Run with:  python -m processing.main
"""
from __future__ import annotations

import asyncio
import os
import signal

from elasticsearch import AsyncElasticsearch

from processing.filters.deduplicator import Deduplicator
from processing.pipeline import ContentPipeline
from shared.kafka import (
    TOPIC_OUTPUT,
    TOPIC_RAW_HTML,
    KafkaProducerClient,
    consume_loop,
    create_consumer,
)
from shared.logging import configure_logging, get_logger
from shared.metrics import es_index_total, start_metrics_server
from shared.models import RawHtmlPage, ScrapedArticle

configure_logging("processing")
logger = get_logger("processing.main")

ES_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
ES_INDEX = os.getenv("ELASTICSEARCH_INDEX", "scraped_articles")
METRICS_PORT = int(os.getenv("METRICS_PORT", "9091"))

_stop_event = asyncio.Event()

ES_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "source": {"type": "keyword"},
            "url": {"type": "keyword"},
            "title": {"type": "text"},
            "author": {"type": "keyword"},
            "published_date": {"type": "date", "ignore_malformed": True},
            "language": {"type": "keyword"},
            "content": {"type": "text"},
            "scraped_at": {"type": "date"},
        }
    },
    "settings": {
        "number_of_shards": 3,
        "number_of_replicas": 1,
        "refresh_interval": "10s",
    },
}


async def ensure_es_index(es: AsyncElasticsearch) -> None:
    """Create Elasticsearch index if it doesn't exist."""
    exists = await es.indices.exists(index=ES_INDEX)
    if not exists:
        await es.indices.create(index=ES_INDEX, body=ES_INDEX_MAPPING)
        logger.info("es_index_created", index=ES_INDEX)


async def index_article(es: AsyncElasticsearch, article: ScrapedArticle) -> None:
    """Index a structured article into Elasticsearch."""
    try:
        await es.index(
            index=ES_INDEX,
            id=article.id,
            document=article.model_dump(),
        )
        es_index_total.labels(status="success").inc()
    except Exception as exc:
        es_index_total.labels(status="error").inc()
        logger.error("es_index_failed", url=article.url, error=str(exc))


async def main() -> None:
    logger.info("processing_service_starting")
    start_metrics_server(METRICS_PORT)

    # Init Elasticsearch
    es = AsyncElasticsearch([ES_URL])
    await ensure_es_index(es)

    # Init Redis deduplicator
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    deduplicator = await Deduplicator.create(redis_url)

    # Init Kafka
    kafka_producer = KafkaProducerClient()
    await kafka_producer.start()

    consumer = await create_consumer(
        topics=[TOPIC_RAW_HTML],
        group_id="processing-service",
    )

    pipeline = ContentPipeline(deduplicator, kafka_producer)

    async def handle_raw_page(msg_value: dict) -> None:
        try:
            page = RawHtmlPage(**msg_value)
            article = await pipeline.process(page)
            if article:
                await index_article(es, article)
        except Exception as exc:
            logger.error("processing_error", error=str(exc), exc_info=True)

    def _shutdown(*_):
        logger.info("shutdown_signal_received")
        _stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("processing_service_ready")

    try:
        await consume_loop(consumer, handle_raw_page, stop_event=_stop_event)
    finally:
        await kafka_producer.stop()
        await es.close()
        logger.info("processing_service_stopped")


if __name__ == "__main__":
    asyncio.run(main())
