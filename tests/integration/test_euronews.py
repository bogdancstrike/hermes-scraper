"""
Integration test: euronews.ro

Runs the full app pipeline via app.scrape_website():
  Playwright render → SelectorClient (PG cache → probe → LLM fallback)
  → SiteNavigator (section discovery + pagination)
  → trafilatura extraction → JSON + CSV export

Self-contained: sets required env vars, gracefully degrades without PG/Redis/LLM.
Output: tests/output/test_euronews/
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

# ── Environment ───────────────────────────────────────────────────────────────
os.environ.setdefault("POSTGRES_DSN", "postgresql://scraper:scraper@localhost:5432/scraperdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_FORMAT", "console")

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

# ── Import app entry point ────────────────────────────────────────────────────
from app import scrape_website, export_results  # noqa: E402

# ── Test parameters ───────────────────────────────────────────────────────────
DOMAIN = "euronews.ro"
MAX_PAGES = 1
MAX_ARTICLES = 5
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "test_euronews"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def articles() -> list[dict]:
    """Run the full app pipeline against euronews.ro once for the whole module."""
    results = asyncio.run(
        scrape_website(DOMAIN, max_pages=MAX_PAGES, max_articles=MAX_ARTICLES, output_dir=OUTPUT_DIR)
    )
    if results:
        export_results(results, DOMAIN, OUTPUT_DIR)
    return results


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_scrape_returns_articles(articles):
    """scrape_website() must complete without crashing and return at least 1 article."""
    assert isinstance(articles, list), "scrape_website() must return a list"
    assert len(articles) > 0, (
        f"No articles scraped from {DOMAIN}. Check site availability."
    )


def test_articles_are_dicts(articles):
    """scrape_website() must return plain dicts."""
    if not articles:
        pytest.skip("No articles")
    for a in articles:
        assert isinstance(a, dict), f"Expected dict, got {type(a)}"


def test_articles_have_required_fields(articles):
    """Each article dict must contain all expected fields."""
    if not articles:
        pytest.skip("No articles")
    required = {"url", "domain", "title", "content", "word_count", "scraped_at"}
    for a in articles:
        missing = required - a.keys()
        assert not missing, f"Article missing fields: {missing}"


def test_articles_have_content(articles):
    """At least 50% of articles must have meaningful content (≥50 words)."""
    if not articles:
        pytest.skip("No articles")
    with_content = [a for a in articles if a.get("word_count", 0) >= 50]
    ratio = len(with_content) / len(articles)
    assert ratio >= 0.5, (
        f"Only {len(with_content)}/{len(articles)} ({ratio:.0%}) articles "
        f"have ≥50 words. Check {OUTPUT_DIR}/."
    )


def test_articles_have_urls_on_correct_domain(articles):
    """Every article must have a non-empty URL on the euronews.ro domain."""
    if not articles:
        pytest.skip("No articles")
    for a in articles:
        assert a.get("url"), "Article URL is empty"
        assert DOMAIN in a["url"], f"URL not on expected domain: {a['url']}"


def test_articles_tagged_with_correct_domain(articles):
    """Articles must be tagged with domain=euronews.ro."""
    if not articles:
        pytest.skip("No articles")
    for a in articles:
        assert a.get("domain") == DOMAIN, (
            f"Wrong domain '{a.get('domain')}' — expected '{DOMAIN}'"
        )


def test_articles_have_titles(articles):
    """At least half of articles must have a title extracted."""
    if not articles:
        pytest.skip("No articles")
    with_title = [a for a in articles if a.get("title")]
    ratio = len(with_title) / len(articles)
    assert ratio >= 0.5, (
        f"Only {len(with_title)}/{len(articles)} articles have titles"
    )


def test_output_files_created(articles):
    """export_results() must create JSON and CSV files in the output dir."""
    if not articles:
        pytest.skip("No articles to export")
    assert OUTPUT_DIR.exists(), f"Output directory not created: {OUTPUT_DIR}"
    assert list(OUTPUT_DIR.glob("euronews_ro_*.json")), "JSON output file not created"
    assert list(OUTPUT_DIR.glob("euronews_ro_*.csv")), "CSV output file not created"
