#!/usr/bin/env python3
"""
On-demand scraper for biziday.ro and adevarul.ro.

Runs standalone — no Kafka, PostgreSQL, or Redis required.
Exports results to output/ as JSON + CSV.

Usage:
    python scripts/scrape_sites.py
    python scripts/scrape_sites.py --sites biziday
    python scripts/scrape_sites.py --sites biziday adevarul --pages 5

Requirements (pip install):
    httpx beautifulsoup4 lxml trafilatura rich python-dotenv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

# Load .env from project root
from pathlib import Path as _P
_env_file = _P(__file__).parent.parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    # No Accept-Encoding — let httpx manage decompression automatically
    "Connection": "keep-alive",
}

# ─────────────────────────────────────────────────────────────────────────────
# Site profiles
# ─────────────────────────────────────────────────────────────────────────────

SITE_PROFILES: dict[str, dict] = {
    "biziday": {
        "name": "Biziday",
        "domain": "biziday.ro",
        "start_url": "https://www.biziday.ro",
        "language": "ro",
        # CSS selectors — articles are in <li class="article"> inside <ul class="loop">
        "article_links_selector": "li.article a, ul.loop li a",
        "pagination_next_selector": "a.next, a[rel='next'], .nav-previous a, .older-posts a",
        "article_body_selector": ".entry-content, .post-content, article .content, .article-body",
        "article_title_selector": "h1.entry-title, h1.post-title, h1",
        "article_date_selector": "time, .entry-date, .post-date, .date",
        "author_selector": ".entry-author, .author, .byline",
        "delay_min": 1.5,
        "delay_max": 3.5,
        "max_listing_pages": 3,
        "max_articles": 20,
    },
    "euronews": {
        "name": "Euronews RO",
        "domain": "euronews.ro",
        # Use /ultimele-stiri — static HTML with article links; homepage is JS-only
        "start_url": "https://www.euronews.ro/ultimele-stiri",
        "language": "ro",
        # Target /articole/ paths directly — avoids matching nav/tag/category links
        "article_links_selector": "a[href*='/articole/']",
        "pagination_next_selector": (
            "a[rel='next'], a.next, .pagination__next a"
        ),
        "article_body_selector": (
            ".c-article-content, .article__content, "
            ".o-article__body, .article-body, .entry-content, main article"
        ),
        "article_title_selector": (
            "h1.c-article-title, h1.article__title, "
            ".o-article__title, h1"
        ),
        "article_date_selector": "time, .article__date, .c-article-date, .date",
        "author_selector": ".article__author, .c-article-author, .author, .byline",
        "delay_min": 1.5,
        "delay_max": 3.0,
        "max_listing_pages": 3,
        "max_articles": 20,
    },
    "adevarul": {
        "name": "Adevarul",
        "domain": "adevarul.ro",
        "start_url": "https://adevarul.ro",
        "language": "ro",
        # a.title = article headline links; a.item = secondary article cards
        "article_links_selector": "a.title, a.item",
        "pagination_next_selector": "a.next-page, a[rel='next'], .pagination .next a, li.next a",
        "article_body_selector": (
            ".article-body, .article__body, .story-body, "
            ".entry-content, #article-body, .content-article"
        ),
        "article_title_selector": "h1.article__title, h1.article-title, h1",
        "article_date_selector": "time, .article__date, .publish-date, .date-time",
        "author_selector": ".article__author, .author-name, .byline, .author",
        "delay_min": 2.0,
        "delay_max": 4.0,
        "max_listing_pages": 3,
        "max_articles": 20,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScrapedArticle:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    site: str = ""
    domain: str = ""
    url: str = ""
    title: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[str] = None
    language: Optional[str] = None
    content: str = ""
    word_count: int = 0
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

# ─────────────────────────────────────────────────────────────────────────────
# HTTP client
# ─────────────────────────────────────────────────────────────────────────────

class Fetcher:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            http2=True,
        )
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    async def get(self, url: str, delay_min: float = 1.5, delay_max: float = 3.5) -> tuple[str, int]:
        """Fetch URL with human-like delay. Returns (html, status_code)."""
        await asyncio.sleep(random.uniform(delay_min, delay_max))
        try:
            resp = await self._client.get(url)
            return resp.text, resp.status_code
        except Exception:
            return "", 0

# ─────────────────────────────────────────────────────────────────────────────
# Content extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_text(html: str, url: str = "") -> str:
    """Extract main article text using trafilatura + BS4 fallback."""
    if not html:
        return ""

    if HAS_TRAFILATURA:
        text = trafilatura.extract(
            html, url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
            no_fallback=False,
        )
        if text and len(text) > 150:
            return text.strip()

    # BS4 fallback
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
            tag.decompose()
        for sel in ["article", ".article-body", ".entry-content", ".post-content", "main", "#content"]:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(" ", strip=True)
                if len(t) > 150:
                    return t
        body = soup.body
        if body:
            return body.get_text(" ", strip=True)[:8000]
    except Exception:
        pass
    return ""


def extract_field(soup: BeautifulSoup, selector: str) -> str:
    """Extract text from first matching CSS selector."""
    if not selector:
        return ""
    try:
        el = soup.select_one(selector)
        if el:
            if el.name == "time":
                return el.get("datetime", "") or el.get_text(strip=True)
            return el.get_text(strip=True)
    except Exception:
        pass
    return ""


def extract_article_urls(html: str, base_url: str, profile: dict) -> list[str]:
    """Extract article URLs from a listing page using profile selectors."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
        domain = profile["domain"]
        urls = []
        for sel in profile["article_links_selector"].split(","):
            sel = sel.strip()
            if not sel:
                continue
            for el in soup.select(sel)[:100]:
                href = el.get("href", "")
                if not href:
                    a = el.find("a", href=True)
                    if a:
                        href = a["href"]
                if href and not href.startswith("#"):
                    full = urljoin(base_url, href)
                    parsed = urlparse(full)
                    # Strip URL fragment (#comments, #section, etc.) to avoid duplicates
                    full = parsed._replace(fragment="").geturl()
                    if (domain in parsed.netloc
                            and len(parsed.path) > 5
                            and full not in urls
                            and not any(x in parsed.path for x in ["/tag/", "/taguri/", "/categor", "/autor/", "/author/", "/page/"])):
                        urls.append(full)
        return urls
    except Exception:
        return []


def find_next_page(html: str, current_url: str, profile: dict) -> str | None:
    """Find next listing page URL."""
    try:
        soup = BeautifulSoup(html, "lxml")
        sel = profile["pagination_next_selector"]
        for s in sel.split(","):
            el = soup.select_one(s.strip())
            if el:
                href = el.get("href", "")
                if href and href != current_url:
                    return urljoin(current_url, href)
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Core scraping logic
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_article(
    fetcher: Fetcher,
    url: str,
    profile: dict,
    progress: Progress,
    task_id,
) -> ScrapedArticle | None:
    """Fetch and process a single article page."""
    html, status = await fetcher.get(url, profile["delay_min"], profile["delay_max"])

    if not html or status not in (200, 0):
        progress.advance(task_id)
        return None

    soup = BeautifulSoup(html, "lxml")

    title = extract_field(soup, profile["article_title_selector"]) or None
    author = extract_field(soup, profile["author_selector"]) or None
    published_date = extract_field(soup, profile["article_date_selector"]) or None
    if published_date:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", published_date)
        if m:
            published_date = m.group(1)

    content = extract_text(html, url)
    if not content or len(content) < 80:
        progress.advance(task_id)
        return None

    article = ScrapedArticle(
        site=profile["name"],
        domain=profile["domain"],
        url=url,
        title=title,
        author=author,
        published_date=published_date,
        language=profile.get("language", "ro"),
        content=content,
        word_count=len(content.split()),
    )

    progress.advance(task_id)
    return article


async def scrape_site(
    profile: dict,
    fetcher: Fetcher,
    max_pages: int,
    max_articles: int,
    progress: Progress,
) -> list[ScrapedArticle]:
    """Scrape a full site: paginate listing, collect articles, extract content."""
    site_name = profile["name"]
    results: list[ScrapedArticle] = []
    article_urls: list[str] = []

    # ── Phase 1: collect article URLs from listing pages ─────
    console.print(f"\n[bold cyan]▶ {site_name}[/bold cyan] — collecting article URLs...")

    listing_task = progress.add_task(
        f"[cyan]{site_name}[/cyan] listing pages",
        total=max_pages,
    )

    current_url = profile["start_url"]
    for page_num in range(max_pages):
        html, status = await fetcher.get(current_url, profile["delay_min"], profile["delay_max"])
        if not html:
            break

        new_urls = extract_article_urls(html, current_url, profile)
        for u in new_urls:
            if u not in article_urls:
                article_urls.append(u)

        console.print(
            f"  Page {page_num + 1}: found {len(new_urls)} links "
            f"(total {len(article_urls)})"
        )
        progress.advance(listing_task)

        if len(article_urls) >= max_articles:
            break

        next_url = find_next_page(html, current_url, profile)
        if not next_url or next_url == current_url:
            break
        current_url = next_url

    progress.remove_task(listing_task)
    article_urls = article_urls[:max_articles]
    console.print(f"  [green]✓[/green] Collected {len(article_urls)} article URLs")

    if not article_urls:
        console.print(f"  [yellow]⚠[/yellow] No article URLs found — site structure may have changed")
        return results

    # ── Phase 2: scrape each article ─────────────────────────
    article_task = progress.add_task(
        f"[cyan]{site_name}[/cyan] articles",
        total=len(article_urls),
    )

    sem = asyncio.Semaphore(2)  # polite concurrency

    async def fetch_one(url: str) -> ScrapedArticle | None:
        async with sem:
            return await scrape_article(fetcher, url, profile, progress, article_task)

    batch = await asyncio.gather(*[fetch_one(u) for u in article_urls])
    results = [a for a in batch if a is not None]
    progress.remove_task(article_task)

    console.print(f"  [green]✓[/green] Scraped {len(results)} articles from {site_name}")
    return results

# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

def export_results(articles: list[ScrapedArticle], site_key: str, output_dir: Path) -> dict[str, Path]:
    """Export articles to JSON and CSV. Returns dict of {format: path}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base_name = f"{site_key}_{timestamp}"
    exported = {}

    # ── JSON (full data) ──────────────────────────────────────
    json_path = output_dir / f"{base_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "site": site_key,
                "scraped_at": datetime.utcnow().isoformat(),
                "total_articles": len(articles),
                "articles": [a.to_dict() for a in articles],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    exported["json"] = json_path

    # ── CSV ───────────────────────────────────────────────────
    csv_path = output_dir / f"{base_name}.csv"
    csv_fields = [
        "id", "site", "url", "title", "author", "published_date",
        "language", "word_count", "scraped_at",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for a in articles:
            writer.writerow({k: a.to_dict().get(k, "") for k in csv_fields})
    exported["csv"] = csv_path

    # ── Content text dump ─────────────────────────────────────
    txt_path = output_dir / f"{base_name}_content.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(f"{'='*80}\n")
            f.write(f"URL: {a.url}\n")
            f.write(f"Title: {a.title or '(unknown)'}\n")
            f.write(f"Author: {a.author or '(unknown)'}\n")
            f.write(f"Date: {a.published_date or '(unknown)'}\n")
            f.write(f"\nContent:\n{a.content[:3000]}{'...' if len(a.content) > 3000 else ''}\n\n")
    exported["txt"] = txt_path

    return exported

# ─────────────────────────────────────────────────────────────────────────────
# Summary display
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(all_results: dict[str, list[ScrapedArticle]]):
    """Print a rich summary table of results."""
    console.print()
    table = Table(title="Scraping Results", show_header=True, header_style="bold cyan")
    table.add_column("Site", style="bold")
    table.add_column("Articles", justify="right")
    table.add_column("Avg Words", justify="right")
    table.add_column("With Title", justify="right")
    table.add_column("With Date", justify="right")

    for site_key, articles in all_results.items():
        if not articles:
            table.add_row(site_key, "0", "-", "-", "-")
            continue

        avg_words = sum(a.word_count for a in articles) // len(articles)
        with_title = sum(1 for a in articles if a.title)
        with_date = sum(1 for a in articles if a.published_date)

        table.add_row(
            SITE_PROFILES[site_key]["name"],
            str(len(articles)),
            str(avg_words),
            f"{with_title}/{len(articles)}",
            f"{with_date}/{len(articles)}",
        )

    console.print(table)

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def run(
    site_keys: list[str],
    max_pages: int,
    max_articles: int,
    output_dir: Path,
):
    console.rule("[bold blue]Web Scraper")
    console.print(f"[cyan]Sites:[/cyan] {', '.join(site_keys)}")
    console.print(f"[cyan]Max listing pages:[/cyan] {max_pages} per site")
    console.print(f"[cyan]Max articles:[/cyan] {max_articles} per site")
    console.print(f"[cyan]Output directory:[/cyan] {output_dir.resolve()}")

    all_results: dict[str, list[ScrapedArticle]] = {}
    all_exports: dict[str, dict] = {}

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        async with Fetcher() as fetcher:
            for site_key in site_keys:
                profile = SITE_PROFILES[site_key]
                articles = await scrape_site(
                    profile=profile,
                    fetcher=fetcher,
                    max_pages=max_pages,
                    max_articles=max_articles,
                    progress=progress,
                )
                all_results[site_key] = articles

                if articles:
                    exports = export_results(articles, site_key, output_dir)
                    all_exports[site_key] = exports
                    console.print(f"  [green]✓[/green] Exported {site_key}:")
                    for fmt, path in exports.items():
                        console.print(f"      [{fmt.upper()}] {path}")

    print_summary(all_results)

    console.print()
    console.rule("[bold green]Done")
    total = sum(len(v) for v in all_results.values())
    console.print(f"[bold]Total articles scraped: {total}[/bold]")
    console.print(f"[bold]Output directory:[/bold] {output_dir.resolve()}/")
    console.print()
    for site_key, exports in all_exports.items():
        for fmt, path in exports.items():
            rel = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
            console.print(f"  {rel}")


def main():
    parser = argparse.ArgumentParser(
        description="On-demand scraper for biziday.ro and adevarul.ro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/scrape_sites.py
  python scripts/scrape_sites.py --sites biziday
  python scripts/scrape_sites.py --sites biziday adevarul --pages 5 --articles 30
        """,
    )
    parser.add_argument(
        "--sites",
        nargs="+",
        choices=list(SITE_PROFILES.keys()),
        default=list(SITE_PROFILES.keys()),
        help="Which sites to scrape (default: all)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Max listing pages to paginate per site (default: 3)",
    )
    parser.add_argument(
        "--articles",
        type=int,
        default=20,
        help="Max articles to scrape per site (default: 20)",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR),
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    args = parser.parse_args()

    asyncio.run(run(
        site_keys=args.sites,
        max_pages=args.pages,
        max_articles=args.articles,
        output_dir=Path(args.output),
    ))


if __name__ == "__main__":
    main()
