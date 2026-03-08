"""
Prometheus metrics for the Hermes scraper.
"""
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import os

# ── Scraper ───────────────────────────────────────────────────────────────────
pages_fetched_total = Counter(
    "scraper_pages_fetched_total",
    "Total pages fetched",
    ["domain", "status"],
)

pages_blocked_total = Counter(
    "scraper_pages_blocked_total",
    "Pages blocked by anti-bot mechanisms",
    ["domain"],
)

fetch_duration_seconds = Histogram(
    "scraper_fetch_duration_seconds",
    "Time to fetch a single page",
    ["domain"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ── LLM / Selector cache ──────────────────────────────────────────────────────
llm_requests_total = Counter(
    "scraper_llm_requests_total",
    "Total LLM API requests",
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
    "Selector cache hits (Redis or PostgreSQL — no LLM call)",
    ["domain"],
)

selector_cache_misses = Counter(
    "scraper_selector_cache_misses_total",
    "Selector cache misses (LLM discovery invoked)",
    ["domain"],
)

# ── Run-level ─────────────────────────────────────────────────────────────────
active_jobs = Gauge("scraper_active_jobs", "Currently running scrape jobs")


def start_metrics_server(port: int | None = None) -> None:
    """Start the Prometheus metrics HTTP server on METRICS_PORT (default 9090)."""
    port = port or int(os.getenv("METRICS_PORT", "9090"))
    start_http_server(port)
