"""
Kafka producer wrapper for the scraper layer.
"""
from __future__ import annotations

from shared.kafka import KafkaProducerClient, TOPIC_RAW_HTML, TOPIC_EVENTS
from shared.models import RawHtmlPage, ScraperEvent
from shared.logging import get_logger

logger = get_logger("scraper_producer")


class ScraperProducer:
    """Emits scraper events and raw HTML to Kafka topics."""

    def __init__(self, producer: KafkaProducerClient):
        self._producer = producer

    async def emit_raw_page(self, page: RawHtmlPage) -> None:
        """Send raw HTML page to processing layer."""
        await self._producer.send(
            TOPIC_RAW_HTML,
            value=page.model_dump(),
            key=page.domain,
        )

    async def emit_event(self, event: ScraperEvent) -> None:
        """Send a status/monitoring event."""
        await self._producer.send(
            TOPIC_EVENTS,
            value=event.model_dump(),
            key=event.domain,
        )
