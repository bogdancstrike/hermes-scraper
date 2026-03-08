"""
Kafka producer and consumer helpers using aiokafka.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from shared.logging import get_logger

logger = get_logger("kafka")

BROKERS = os.getenv("KAFKA_BROKERS", "localhost:9092")

# Topic constants
TOPIC_JOBS = os.getenv("KAFKA_TOPIC_JOBS", "scraper.jobs")
TOPIC_RAW_HTML = os.getenv("KAFKA_TOPIC_RAW_HTML", "raw.html.pages")
TOPIC_OUTPUT = os.getenv("KAFKA_TOPIC_OUTPUT", "structured.output")
TOPIC_EVENTS = os.getenv("KAFKA_TOPIC_EVENTS", "scraper.events")


class KafkaProducerClient:
    """Async Kafka producer with JSON serialization."""

    def __init__(self):
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=BROKERS,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
            key_serializer=lambda k: k.encode() if isinstance(k, str) else k,
            compression_type="gzip",
            max_batch_size=32768,
            linger_ms=5,
        )
        await self._producer.start()
        logger.info("kafka_producer_started", brokers=BROKERS)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def send(self, topic: str, value: dict, key: str | None = None) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started")
        await self._producer.send(topic, value=value, key=key)

    async def send_and_wait(self, topic: str, value: dict, key: str | None = None):
        if not self._producer:
            raise RuntimeError("Producer not started")
        return await self._producer.send_and_wait(topic, value=value, key=key)


@asynccontextmanager
async def kafka_producer() -> AsyncGenerator[KafkaProducerClient, None]:
    """Context manager for a Kafka producer."""
    client = KafkaProducerClient()
    await client.start()
    try:
        yield client
    finally:
        await client.stop()


async def create_consumer(
    topics: list[str],
    group_id: str,
    auto_offset_reset: str = "earliest",
) -> AIOKafkaConsumer:
    """Create and start a Kafka consumer."""
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=BROKERS,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        value_deserializer=lambda v: json.loads(v.decode()),
        enable_auto_commit=True,
        auto_commit_interval_ms=1000,
        max_poll_records=10,
    )
    await consumer.start()
    logger.info("kafka_consumer_started", topics=topics, group=group_id)
    return consumer


async def consume_loop(
    consumer: AIOKafkaConsumer,
    handler: Callable,
    stop_event=None,
) -> None:
    """
    Run a consumption loop calling handler(message_value) for each message.
    Stops when stop_event is set (if provided).
    """
    try:
        async for msg in consumer:
            if stop_event and stop_event.is_set():
                break
            try:
                await handler(msg.value)
            except Exception as exc:
                logger.error(
                    "message_handler_error",
                    topic=msg.topic,
                    error=str(exc),
                    exc_info=True,
                )
    finally:
        await consumer.stop()
