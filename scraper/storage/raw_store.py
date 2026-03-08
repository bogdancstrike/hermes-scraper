"""
MinIO raw HTML archival.
Every fetched page is stored for replay/debugging.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from scraper.config import config
from shared.logging import get_logger

logger = get_logger("raw_store")


class RawStore:
    """Store raw HTML pages in MinIO with gzip compression."""

    def __init__(self):
        self._client = Minio(
            config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_use_ssl,
        )
        self._bucket = config.minio_bucket

    async def ensure_bucket(self) -> None:
        """Create bucket if it doesn't exist."""
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("minio_bucket_created", bucket=self._bucket)
        except S3Error as exc:
            logger.error("minio_bucket_error", error=str(exc))

    def store(self, page_id: str, domain: str, url: str, html: str) -> str:
        """
        Store HTML with metadata. Returns the object key.
        Path: {domain}/{YYYY/MM/DD}/{page_id}.json.gz
        """
        today = datetime.utcnow().strftime("%Y/%m/%d")
        object_key = f"{domain}/{today}/{page_id}.json.gz"

        payload = json.dumps({
            "page_id": page_id,
            "domain": domain,
            "url": url,
            "html": html,
            "scraped_at": datetime.utcnow().isoformat(),
        }).encode()

        compressed = gzip.compress(payload, compresslevel=6)
        buffer = BytesIO(compressed)

        try:
            self._client.put_object(
                self._bucket,
                object_key,
                buffer,
                length=len(compressed),
                content_type="application/gzip",
                metadata={"domain": domain, "url": url[:500]},
            )
            logger.debug("raw_html_stored", key=object_key, size_kb=len(compressed) // 1024)
        except S3Error as exc:
            logger.error("raw_html_store_failed", key=object_key, error=str(exc))
            raise

        return object_key

    def get(self, object_key: str) -> dict:
        """Retrieve and decompress a stored page."""
        try:
            response = self._client.get_object(self._bucket, object_key)
            compressed = response.read()
            payload = gzip.decompress(compressed)
            return json.loads(payload)
        except S3Error as exc:
            logger.error("raw_html_get_failed", key=object_key, error=str(exc))
            raise
