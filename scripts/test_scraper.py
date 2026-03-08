"""
Quick end-to-end smoke test.
Fetches a URL, runs it through the content pipeline, calls LLM extraction.

Usage:
  python scripts/test_scraper.py --url https://news.ycombinator.com --pages 1
"""
import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.json import JSON

from processing.filters.extractor import extract_main_content
from shared.logging import configure_logging

configure_logging("smoke-test")
console = Console()


async def smoke_test(url: str, llm_endpoint: str = "http://localhost:8000"):
    console.rule("[bold blue]LLM Scraper Smoke Test")
    console.print(f"[cyan]Target URL:[/cyan] {url}")
    console.print(f"[cyan]LLM Endpoint:[/cyan] {llm_endpoint}")
    console.print()

    # Step 1: Fetch page
    console.print("[yellow]Step 1:[/yellow] Fetching page...")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
        console.print(f"  ✅ Fetched {len(html):,} bytes (HTTP {resp.status_code})")
    except Exception as exc:
        console.print(f"  ❌ Fetch failed: {exc}")
        return

    # Step 2: Extract content
    console.print("[yellow]Step 2:[/yellow] Extracting main content...")
    text = extract_main_content(html, url)
    if text:
        console.print(f"  ✅ Extracted {len(text):,} characters ({len(text)/len(html)*100:.1f}% of raw HTML)")
        console.print(f"  Preview: {text[:200]}...")
    else:
        console.print("  ⚠️  Content extraction returned nothing (page may require JS)")
        text = html[:2000]

    # Step 3: Selector discovery
    console.print("[yellow]Step 3:[/yellow] Testing LLM selector discovery...")
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    compact_dom = html[:4000]

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{llm_endpoint}/v1/analyze-selectors",
                json={"domain": domain, "dom": compact_dom, "sample_url": url},
            )
            selectors = resp.json()
        console.print("  ✅ Selectors discovered:")
        console.print(Panel(JSON(json.dumps(selectors, indent=2)), title="CSS Selectors"))
    except Exception as exc:
        console.print(f"  ⚠️  Selector discovery failed: {exc} (LLM API may not be running)")

    # Step 4: Content extraction
    console.print("[yellow]Step 4:[/yellow] Testing LLM content extraction...")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{llm_endpoint}/v1/extract",
                json={
                    "url": url,
                    "domain": domain,
                    "text": text[:6000],
                    "job_id": "smoke-test",
                    "page_id": "smoke-test-page",
                },
            )
            extracted = resp.json()
        console.print("  ✅ Extraction result:")
        console.print(Panel(JSON(json.dumps(extracted, indent=2)), title="Extracted Article"))
    except Exception as exc:
        console.print(f"  ⚠️  Extraction failed: {exc} (LLM API may not be running)")

    console.rule("[bold green]Smoke Test Complete")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://news.ycombinator.com", help="URL to test")
    parser.add_argument("--llm", default=os.getenv("LLM_BASE_URL", "http://localhost:8000"), help="LLM API endpoint")
    args = parser.parse_args()
    asyncio.run(smoke_test(args.url, args.llm))


if __name__ == "__main__":
    main()
