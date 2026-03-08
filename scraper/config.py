"""
Hermes Scraper — runtime configuration via environment variables.

All settings are loaded from the environment (or .env file) via pydantic-settings.
The singleton `config` is imported by every module that needs settings.
"""
from pydantic import Field
from pydantic_settings import BaseSettings


class ScraperConfig(BaseSettings):
    # ── Runtime limits ────────────────────────────────────────────────────────
    scrape_limit: int = Field(100, alias="SCRAPE_LIMIT")          # max articles per run
    max_pages: int = Field(5, alias="SCRAPER_MAX_PAGES")          # max listing pages per section
    retry_limit: int = Field(3, alias="SCRAPER_RETRY_LIMIT")

    # ── Navigation & concurrency ──────────────────────────────────────────────
    delay_min: float = Field(1.5, alias="SCRAPER_DELAY_MIN")
    delay_max: float = Field(3.5, alias="SCRAPER_DELAY_MAX")
    concurrency: int = Field(3, alias="SCRAPER_CONCURRENCY")
    navigation_strategy: str = Field("domcontentloaded", alias="NAVIGATION_STRATEGY")
    max_sections: int = Field(50, alias="SCRAPER_MAX_SECTIONS")

    # ── Infinite scroll ───────────────────────────────────────────────────────
    scroll_max: int = Field(20, alias="SCRAPER_SCROLL_MAX")
    scroll_wait_ms: int = Field(1500, alias="SCRAPER_SCROLL_WAIT_MS")

    # ── Browser ───────────────────────────────────────────────────────────────
    use_headless: bool = Field(True, alias="HEADLESS")
    browser_timeout: int = Field(45000, alias="BROWSER_TIMEOUT")
    use_stealth: bool = Field(True, alias="USE_STEALTH")
    impersonate_browser: str = Field("chrome120", alias="IMPERSONATE_BROWSER")

    # ── Content quality ───────────────────────────────────────────────────────
    min_title_length: int = Field(20, alias="MIN_TITLE_LENGTH")

    # ── Enrichments ───────────────────────────────────────────────────────────
    capture_screenshot: bool = Field(False, alias="CAPTURE_SCREENSHOT")
    screenshot_type: str = Field("jpeg", alias="SCREENSHOT_TYPE")
    extract_emails: bool = Field(False, alias="EXTRACT_EMAILS")
    extract_hashtags: bool = Field(False, alias="EXTRACT_HASHTAGS")

    # ── Selector discovery ────────────────────────────────────────────────────
    retry_deep_analysis: int = Field(3, alias="RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS")

    # ── Infrastructure endpoints ──────────────────────────────────────────────
    llm_endpoint: str = Field("http://localhost:11434/v1", alias="LLM_BASE_URL")
    postgres_dsn: str = Field(
        "postgresql://scraper:scraper@localhost:5432/scraperdb",
        alias="POSTGRES_DSN",
    )
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    # ── Output ────────────────────────────────────────────────────────────────
    output_dir: str = Field("output", alias="OUTPUT_DIR")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_format: str = Field("console", alias="LOG_FORMAT")

    model_config = {"env_file": ".env", "extra": "ignore", "populate_by_name": True}


# Module-level singleton — import with: from scraper.config import config
config = ScraperConfig()
