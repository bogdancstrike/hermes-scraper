"""
Prometheus metrics definitions shared across services.
Each service only uses the metrics relevant to it.
"""
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import os


# ── Scraper Metrics ────────────────────────────────────────────
pages_fetched_total = Counter(
    "scraper_pages_fetched_total",
    "Total pages fetched",
    ["domain", "status"],  # status: success | blocked | error
)

pages_blocked_total = Counter(
    "scraper_pages_blocked_total",
    "Pages blocked by anti-bot mechanisms",
    ["domain"],
)

jobs_completed_total = Counter(
    "scraper_jobs_completed_total",
    "Scraping jobs completed",
    ["status"],  # done | failed
)

fetch_duration_seconds = Histogram(
    "scraper_fetch_duration_seconds",
    "Time to fetch a single page",
    ["domain"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ── LLM Metrics ───────────────────────────────────────────────
llm_requests_total = Counter(
    "scraper_llm_requests_total",
    "Total LLM API requests made",
    ["endpoint", "model", "status"],
)

llm_tokens_sent_total = Counter(
    "scraper_llm_tokens_sent_total",
    "Approximate tokens sent to LLM",
    ["endpoint"],
)

llm_duration_seconds = Histogram(
    "scraper_llm_duration_seconds",
    "LLM API response time",
    ["endpoint"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

selector_cache_hits = Counter(
    "scraper_selector_cache_hits_total",
    "Selector cache hits (no LLM needed)",
    ["domain"],
)

selector_cache_misses = Counter(
    "scraper_selector_cache_misses_total",
    "Selector cache misses (LLM called)",
    ["domain"],
)

# ── Processing Metrics ────────────────────────────────────────
pages_processed_total = Counter(
    "processing_pages_processed_total",
    "Pages processed by content pipeline",
    ["status"],  # extracted | skipped_dedup | skipped_short
)

dedup_rejections_total = Counter(
    "processing_dedup_rejections_total",
    "Pages rejected as near-duplicates",
)

# ── Storage Metrics ───────────────────────────────────────────
es_index_total = Counter(
    "storage_es_index_total",
    "Documents indexed in Elasticsearch",
    ["status"],
)

# ── Active jobs gauge ─────────────────────────────────────────
active_jobs = Gauge(
    "scraper_active_jobs",
    "Currently running scrape jobs",
)

kafka_consumer_lag = Gauge(
    "scraper_kafka_consumer_lag",
    "Kafka consumer lag",
    ["topic", "partition"],
)


def start_metrics_server(port: int | None = None) -> None:
    """Start the Prometheus metrics HTTP server."""
    port = port or int(os.getenv("METRICS_PORT", "9090"))
    start_http_server(port)
