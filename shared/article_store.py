"""
ArticleStore — idempotent, fault-tolerant article persistence.

Saves articles immediately after extraction (not batched at the end).
Falls back gracefully when the database is unavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Awaitable

from shared.logging import get_logger

logger = get_logger("article_store")


class ArticleStore:
    """
    Thin layer over `shared.db.save_article` with:
      - Graceful degradation if DB is unavailable
      - Optional JSON file fallback (streaming NDJSON)
      - Dedup guard (already-seen URLs skipped in memory)
    """

    def __init__(self, db_ok: bool = True, ndjson_path: Path | None = None):
        self._db_ok = db_ok
        self._seen: set[str] = set()
        self._ndjson_path = ndjson_path
        self._ndjson_fh = None
        if ndjson_path:
            ndjson_path.parent.mkdir(parents=True, exist_ok=True)
            self._ndjson_fh = open(ndjson_path, "a", encoding="utf-8")

    async def save(self, article: dict) -> bool:
        """
        Persist one article.  Returns True if newly saved, False if duplicate/error.
        Thread-safe for concurrent asyncio tasks (single event loop).
        """
        url = article.get("url", "")
        if not url or url in self._seen:
            return False
        self._seen.add(url)

        saved = False

        if self._db_ok:
            try:
                from shared.db import save_article
                saved = await save_article(article)
            except Exception as exc:
                logger.warning("article_store_db_error", url=url, error=str(exc))

        if self._ndjson_fh:
            try:
                self._ndjson_fh.write(json.dumps(article, ensure_ascii=False, default=str) + "\n")
                self._ndjson_fh.flush()
                saved = True
            except Exception as exc:
                logger.warning("article_store_ndjson_error", url=url, error=str(exc))

        if saved:
            logger.debug("article_saved", url=url)
        return saved

    def close(self) -> None:
        if self._ndjson_fh:
            self._ndjson_fh.close()
            self._ndjson_fh = None

    def __del__(self):
        self.close()
