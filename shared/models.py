"""
Shared Pydantic data models used across all services.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Site Configuration ─────────────────────────────────────────────────────────

class SiteConfig(BaseModel):
    """Configuration for a site to scrape."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    domain: str
    name: str
    start_url: str
    is_active: bool = True
    schedule: str = "0 */6 * * *"
    max_pages: int = 100
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SiteSelectors(BaseModel):
    """CSS selectors discovered for a site, cached in Redis + PostgreSQL."""
    model_config = {"protected_namespaces": ()}

    domain: str
    article_links_selector: str = ""
    pagination_next_selector: str = ""
    article_body_selector: str = ""
    article_title_selector: str = ""
    article_date_selector: str = ""
    author_selector: str = ""
    confidence: float = 0.0
    llm_model: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def is_valid(self) -> bool:
        """Check if we have at minimum the essential selectors."""
        return bool(self.article_links_selector or self.article_body_selector)


# ── Kafka Messages ─────────────────────────────────────────────────────────────

class ScrapeJob(BaseModel):
    """Job message emitted by scheduler, consumed by scraper nodes."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    site_id: str
    domain: str
    start_url: str
    priority: int = 5
    max_pages: int = 100
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RawHtmlPage(BaseModel):
    """Raw HTML page emitted by scraper, consumed by processing layer."""
    job_id: str
    page_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: str
    url: str
    html: str
    html_size_bytes: int = 0
    fetch_duration_ms: int = 0
    http_status: int = 200
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("html_size_bytes", mode="before")
    @classmethod
    def auto_size(cls, v: int, info: Any) -> int:
        return v or 0


# ── Structured Output ──────────────────────────────────────────────────────────

class ScrapedArticle(BaseModel):
    """
    Canonical structured output schema.
    Stored in Elasticsearch after text extraction.
    Metadata (title, author, date, language) is extracted by trafilatura — no LLM needed.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    page_id: str
    source: str                      # domain
    url: str
    title: str | None = None
    author: str | None = None
    published_date: str | None = None
    language: str | None = None
    content: str = ""
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class ArticleRecord(BaseModel):
    """
    Rich structured article output.
    Canonical output format returned by the scraper for every article,
    regardless of which site or fetch strategy was used.
    """
    # Identity
    url: str
    domain: str
    canonical_url: str | None = None

    # Content
    title: str | None = None
    author: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    updated_date: str | None = None
    content: str = ""
    summary: str | None = None
    language: str | None = None
    article_type: str | None = None

    # Media & taxonomy
    top_image: str | None = None
    images: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    publisher: dict | None = None

    # Metrics
    word_count: int = 0
    reading_time_minutes: int = 1
    scraped_at: str = ""

    # Fetch metadata
    fetch_method: str = "playwright"   # "static" or "playwright"
    fetch_latency_ms: int = 0
    block_signals: list[str] = Field(default_factory=list)

    # Quality signals
    overall_score: float = 0.0
    title_score: float = 0.0
    content_score: float = 0.0
    date_score: float = 0.0
    author_score: float = 0.0
    likely_paywalled: bool = False
    likely_liveblog: bool = False

    # Extraction provenance
    field_sources: dict[str, str] = Field(default_factory=dict)
    field_confidence: dict[str, float] = Field(default_factory=dict)


# ── LLM API Request/Response ───────────────────────────────────────────────────

class SelectorRequest(BaseModel):
    """Request to discover CSS selectors for a domain."""
    domain: str
    dom: str                         # Compact DOM HTML (max 4000 chars)
    sample_url: str = ""


class SelectorResponse(BaseModel):
    """CSS selectors returned by LLM analysis."""
    article_links_selector: str = ""
    pagination_next_selector: str = ""
    article_body_selector: str = ""
    article_title_selector: str = ""
    article_date_selector: str = ""
    author_selector: str = ""
    confidence: float = 0.8
    llm_model: str = ""

    model_config = {"protected_namespaces": ()}


# ── Scraper Events (observability) ────────────────────────────────────────────

class ScraperEvent(BaseModel):
    """Status event emitted to Kafka for monitoring."""
    event_type: str                  # page_fetched | block_detected | job_done | error
    node_id: str
    job_id: str
    domain: str
    url: str = ""
    detail: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
