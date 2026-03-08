"""
Playwright headless browser engine — primary engine for all fetching.
Handles JS-rendered pages, infinite scroll, and load-more patterns.
"""
from __future__ import annotations

import asyncio
import random

from scraper.config import config

# Realistic desktop User-Agent strings rotated per browser session
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _next_ua() -> str:
    return random.choice(_USER_AGENTS)
from shared.logging import get_logger

logger = get_logger("browser_engine")

# Fallback "load more" button selectors tried when no explicit selector given
_LOAD_MORE_FALLBACKS = [
    "button[class*='load-more']",
    "button[class*='loadmore']",
    "a[class*='load-more']",
    "[data-testid*='load-more']",
    "button:has-text('Load more')",
    "button:has-text('Show more')",
    "button:has-text('Mai mult')",
    "button:has-text('Incarca mai mult')",
]


class BrowserEngine:
    """
    Async Playwright engine with stealth settings.

    Primary engine for all scraping by default (use_headless=True).
    Use as async context manager — shares one browser / context across all pages.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BrowserEngine":
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--disable-extensions",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=_next_ua(),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        # Block heavy resources to speed up loading
        await self._context.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3,ogg,wav}",
            lambda route: route.abort(),
        )
        # Block tracking and analytics scripts that slow down page loads
        _TRACKING_DOMAINS = [
            "*doubleclick.net*", "*googletagmanager.com*", "*google-analytics.com*",
            "*facebook.net*", "*hotjar.com*", "*scorecardresearch.com*",
            "*adnxs.com*", "*amazon-adsystem.com*", "*pubmatic.com*",
            "*rubiconproject.com*", "*openx.net*", "*taboola.com*", "*outbrain.com*",
        ]
        for pattern in _TRACKING_DOMAINS:
            await self._context.route(pattern, lambda route: route.abort())
        return self

    async def _dismiss_overlays(self, page) -> None:
        """Click cookie consent / GDPR accept buttons and hide overlaying banners."""
        accept_texts = [
            "Accept", "Accept all", "Accept All", "Accept cookies",
            "Acceptă", "Accepta", "Acceptă toate", "Allow all",
            "Allow cookies", "Agree", "Agree and close", "Got it",
            "OK", "I agree", "I Accept",
        ]
        for text in accept_texts:
            try:
                btn = page.get_by_role("button", name=text, exact=True)
                if await btn.is_visible(timeout=300):
                    await btn.click()
                    await asyncio.sleep(0.3)
                    break
            except Exception:
                continue

        # CSS injection to hide any remaining overlays
        try:
            await page.add_style_tag(content="""
                .cookie-banner, .cookie-notice, .gdpr-banner, .consent-banner,
                [id*='cookie'], [class*='cookie-bar'], [class*='cookiebar'],
                [id*='consent'], [class*='consent-popup'], [class*='gdpr'],
                .modal-backdrop, .overlay { display: none !important; }
                body { overflow: auto !important; }
            """)
        except Exception:
            pass

    async def get(self, url: str, wait_for: str = "domcontentloaded", domain: str = "") -> str:
        """
        Navigate to URL, wait for JS to render, scroll halfway to trigger lazy loading,
        and return the full rendered HTML.

        `domain` parameter is accepted but unused — kept for interface compatibility
        with HttpEngine so Paginator can call engine.get(url, domain=domain) on both.
        """
        if not self._context:
            raise RuntimeError("BrowserEngine not started. Use as async context manager.")

        page = await self._context.new_page()
        try:
            await page.goto(
                url,
                wait_until=wait_for,
                timeout=config.browser_timeout,
            )
            # Scroll halfway to trigger above-the-fold lazy loading
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(1.0)
            await self._dismiss_overlays(page)
            html = await page.content()
            logger.debug("browser_fetch_success", url=url)
            return html
        except Exception as exc:
            logger.error("browser_fetch_error", url=url, error=str(exc))
            raise
        finally:
            await page.close()

    async def get_with_infinite_scroll(
        self,
        url: str,
        article_selector: str = "",
        max_scrolls: int | None = None,
        wait_ms: int | None = None,
        load_more_selector: str = "",
    ) -> str:
        """
        Load a listing page and scroll/click until all dynamic content is loaded.

        Strategy:
          1. Navigate and wait for initial render.
          2. On each iteration:
             a. If a "load more" button is visible — click it and wait.
             b. Otherwise scroll to the bottom and wait.
          3. Count elements matching article_selector after each step.
             If the count has not grown for 3 consecutive steps → content exhausted.
          4. Return fully-loaded HTML.

        Args:
            url:                  Page URL to load.
            article_selector:     CSS selector for article/item cards.
                                  Used to detect when new content has loaded.
                                  If empty, counts all <a> elements as proxy.
            max_scrolls:          Maximum scroll/click iterations. Defaults to config value.
            wait_ms:              Milliseconds to wait between scroll steps.
            load_more_selector:   Explicit CSS selector for a "Load More" button.
                                  Falls back to built-in heuristics when empty.
        """
        if max_scrolls is None:
            max_scrolls = config.scroll_max
        if wait_ms is None:
            wait_ms = config.scroll_wait_ms

        wait_s = wait_ms / 1000.0
        count_selector = article_selector or "a[href]"

        if not self._context:
            raise RuntimeError("BrowserEngine not started.")

        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=config.browser_timeout)
            await asyncio.sleep(1.0)
            await self._dismiss_overlays(page)

            prev_count = 0
            stable_rounds = 0

            for _ in range(max_scrolls):
                # Try explicit load-more selector first, then heuristics
                clicked = False
                candidates = (
                    [load_more_selector] if load_more_selector else []
                ) + _LOAD_MORE_FALLBACKS

                for sel in candidates:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=400):
                            await btn.scroll_into_view_if_needed()
                            await btn.click()
                            await asyncio.sleep(wait_s)
                            clicked = True
                            break
                    except Exception:
                        continue

                if not clicked:
                    # Plain scroll to bottom
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(wait_s)

                # Count visible content items
                try:
                    current_count = await page.locator(count_selector).count()
                except Exception:
                    current_count = prev_count

                if current_count <= prev_count:
                    stable_rounds += 1
                    if stable_rounds >= 3:
                        logger.debug(
                            "infinite_scroll_exhausted",
                            url=url,
                            total_items=current_count,
                            scrolls=_,
                        )
                        break
                else:
                    stable_rounds = 0

                prev_count = current_count

            html = await page.content()
            logger.info(
                "infinite_scroll_done",
                url=url,
                final_item_count=prev_count,
            )
            return html

        except Exception as exc:
            logger.error("infinite_scroll_error", url=url, error=str(exc))
            raise
        finally:
            await page.close()

    async def get_with_screenshot(
        self,
        url: str,
        screenshot_path: str,
        wait_for: str = "domcontentloaded",
        screenshot_type: str = "jpeg",
    ) -> str:
        """
        Navigate to URL, optionally capture a full-page screenshot, return HTML.
        Screenshot is saved to `screenshot_path` before the page is closed.
        """
        if not self._context:
            raise RuntimeError("BrowserEngine not started.")

        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until=wait_for, timeout=config.browser_timeout)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(1.0)
            await self._dismiss_overlays(page)
            html = await page.content()

            from pathlib import Path as _Path
            _Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
            kwargs = {"path": screenshot_path, "full_page": True, "type": screenshot_type}
            if screenshot_type == "jpeg":
                kwargs["quality"] = 80
            await page.screenshot(**kwargs)
            logger.debug("screenshot_captured", url=url, path=screenshot_path)
            return html
        except Exception as exc:
            logger.error("browser_fetch_with_screenshot_error", url=url, error=str(exc))
            raise
        finally:
            await page.close()

    async def __aexit__(self, *_) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
