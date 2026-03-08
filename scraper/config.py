"""
Scraper node configuration loaded from environment variables.
"""
import socket
from pydantic import Field
from pydantic_settings import BaseSettings


class ScraperConfig(BaseSettings):
    # Node identity
    node_id: str = Field(default_factory=lambda: f"scraper-{socket.gethostname()}")
    node_env: str = Field("development", alias="NODE_ENV")

    # Runtime limits
    max_runtime: int = Field(600, alias="SCRAPER_MAX_RUNTIME")
    max_pages: int = Field(100, alias="SCRAPER_MAX_PAGES")
    retry_limit: int = Field(3, alias="SCRAPER_RETRY_LIMIT")
    scrape_limit: int = Field(100, alias="SCRAPE_LIMIT")  # max articles per run

    # Navigation
    delay_min: float = Field(1.5, alias="SCRAPER_DELAY_MIN")
    delay_max: float = Field(3.5, alias="SCRAPER_DELAY_MAX")
    concurrency: int = Field(3, alias="SCRAPER_CONCURRENCY")
    navigation_strategy: str = Field("domcontentloaded", alias="NAVIGATION_STRATEGY")

    # Section discovery
    max_sections: int = Field(50, alias="SCRAPER_MAX_SECTIONS")

    # Infinite scroll
    scroll_max: int = Field(20, alias="SCRAPER_SCROLL_MAX")
    scroll_wait_ms: int = Field(1500, alias="SCRAPER_SCROLL_WAIT_MS")

    # Browser
    use_headless: bool = Field(True, alias="HEADLESS")
    browser_timeout: int = Field(45000, alias="BROWSER_TIMEOUT")
    use_stealth: bool = Field(True, alias="USE_STEALTH")
    impersonate_browser: str = Field("chrome120", alias="IMPERSONATE_BROWSER")

    # Anti-bot
    use_proxies: bool = Field(False, alias="SCRAPER_USE_PROXIES")
    proxy_list_url: str = Field("", alias="SCRAPER_PROXY_LIST_URL")
    headless_timeout: int = Field(30, alias="SCRAPER_HEADLESS_TIMEOUT")
    robots_txt_respect: bool = Field(True, alias="ROBOTS_TXT_RESPECT")

    # Content quality filter
    min_title_length: int = Field(20, alias="MIN_TITLE_LENGTH")

    # Enrichment toggles
    extract_images: bool = Field(False, alias="EXTRACT_IMAGES")
    extract_comments: bool = Field(False, alias="EXTRACT_COMMENTS")
    comment_wait_ms: int = Field(5000, alias="COMMENT_WAIT_MS")
    capture_screenshot: bool = Field(False, alias="CAPTURE_SCREENSHOT")
    screenshot_type: str = Field("jpeg", alias="SCREENSHOT_TYPE")  # "jpeg" | "png"
    extract_emails: bool = Field(False, alias="EXTRACT_EMAILS")
    extract_hashtags: bool = Field(False, alias="EXTRACT_HASHTAGS")

    # Selector discovery / retry
    retry_deep_analysis: int = Field(3, alias="RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS")

    # Endpoints
    llm_endpoint: str = Field("http://localhost:8000", alias="LLM_BASE_URL")
    kafka_brokers: str = Field("localhost:9092", alias="KAFKA_BROKERS")
    postgres_dsn: str = Field(
        "postgresql://scraper:scraper@localhost:5432/scraperdb",
        alias="POSTGRES_DSN",
    )
    minio_endpoint: str = Field("localhost:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field("minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field("minioadmin", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field("raw-html", alias="MINIO_BUCKET")
    minio_use_ssl: bool = Field(False, alias="MINIO_USE_SSL")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    # Observability
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_format: str = Field("json", alias="LOG_FORMAT")
    metrics_port: int = Field(9090, alias="METRICS_PORT")

    model_config = {"env_file": ".env", "extra": "ignore", "populate_by_name": True}


# Singleton
config = ScraperConfig()
