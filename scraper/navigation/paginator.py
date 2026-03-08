"""
Site navigation: section discovery, pagination, and infinite-scroll traversal.

Two classes:
  Paginator     — traverse a single listing page via next-page links or query param
                  increment. Used internally by SiteNavigator.
  SiteNavigator — orchestrates full-site crawl: discovers all sections from the
                  homepage, then drives Paginator / infinite-scroll per section.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from shared.logging import get_logger
from shared.models import SiteSelectors

logger = get_logger("paginator")

# ── Constants ──────────────────────────────────────────────────────────────────

# Fallback next-page selectors tried when the LLM-discovered selector yields nothing
FALLBACK_NEXT_SELECTORS = [
    "a[rel='next']",
    "a.next",
    "a.next-page",
    ".pagination a.next",
    ".pager a.next",
    "li.next a",
    "[aria-label='Next page']",
    "[aria-label='Next']",
    ".pagination__next",
    "button[data-testid='pagination-next']",
]

# CSS selectors used to locate navigation / menu regions on the homepage
SECTION_NAV_SELECTORS = [
    "nav a[href]",
    "header a[href]",
    "[role='navigation'] a[href]",
    ".nav a[href]",
    ".navigation a[href]",
    ".menu a[href]",
    "#nav a[href]",
    "#menu a[href]",
    "#header a[href]",
    ".main-menu a[href]",
    ".site-menu a[href]",
    ".navbar a[href]",
    ".sidebar a[href]",
    "aside a[href]",
]

# Path fragments that identify non-content pages (utility, tag, author pages, etc.)
_SECTION_SKIP = [
    "/tag/", "/tags/",
    "/author/", "/user/", "/profile/",
    "/search", "/find", "/results",
    "/login", "/register", "/signup", "/logout",
    "/about", "/contact", "/privacy", "/terms", "/legal",
    "/feed", "/rss", "/sitemap", "/robots",
    "/advertise", "/subscribe", "/newsletter",
    "/page/",       # pagination path segment
    "/cdn-cgi/",    # Cloudflare internal
    "/live/",       # streaming / live TV/radio pages
    "/emisiuni",    # TV show episodes (not news articles)
    "/video/",      # video galleries
    "/podcast",     # podcast pages
    "/galerie",     # photo galleries
    "/foto/",       # photo galleries
]


# ── Paginator ──────────────────────────────────────────────────────────────────

class Paginator:
    """
    Traverse a single section/listing area via next-page links.
    Works with both BrowserEngine and HttpEngine.
    """

    def __init__(self, engine, selectors: SiteSelectors, max_pages: int = 10):
        self.engine = engine
        self.selectors = selectors
        self.max_pages = max_pages

    async def collect_article_urls(self, start_url: str, domain: str) -> list[str]:
        """Follow next-page links from start_url and collect all article URLs."""
        visited: set[str] = set()
        article_urls: list[str] = []
        current_url: str | None = start_url
        page_num = 0

        while current_url and current_url not in visited and page_num < self.max_pages:
            visited.add(current_url)
            page_num += 1

            try:
                html = await self.engine.get(current_url, domain=domain)
            except Exception as exc:
                logger.warning("paginator_fetch_failed", url=current_url, error=str(exc))
                break

            soup = BeautifulSoup(html, "lxml")
            new_urls = self._extract_article_links(soup, current_url, domain)
            article_urls.extend(u for u in new_urls if u not in article_urls)

            logger.debug(
                "paginator_page_done",
                url=current_url,
                page_num=page_num,
                new=len(new_urls),
                total=len(article_urls),
            )

            current_url = self._find_next_page(soup, current_url)

        return article_urls

    def _extract_article_links(
        self, soup: BeautifulSoup, base_url: str, domain: str
    ) -> list[str]:
        """Extract article URLs from a listing page soup."""
        urls: list[str] = []
        selector = self.selectors.article_links_selector

        if selector:
            elements = soup.select(selector)
            if not elements:
                logger.debug(
                    "article_links_selector_empty_fallback",
                    selector=selector,
                    url=base_url,
                )
                elements = self._heuristic_article_links(soup)
        else:
            elements = self._heuristic_article_links(soup)

        for el in elements[:60]:
            if el.name == "a":
                href = el.get("href", "")
            else:
                a = el.find("a", href=True)
                href = a.get("href", "") if a else ""

            if not href or href.startswith("#") or href.startswith("javascript"):
                continue

            full_url = urljoin(base_url, href)
            if self._is_article_url(full_url, domain):
                urls.append(full_url)

        return list(dict.fromkeys(urls))  # dedup, preserve order

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """Return the next-page URL or None if this is the last page."""
        # Configured selector
        if self.selectors.pagination_next_selector:
            el = soup.select_one(self.selectors.pagination_next_selector)
            if el and el.name == "a":
                href = el.get("href")
                if href:
                    nxt = urljoin(current_url, href)
                    if nxt != current_url:
                        return nxt

        # Fallback selectors
        for sel in FALLBACK_NEXT_SELECTORS:
            try:
                el = soup.select_one(sel)
                if el:
                    href = el.get("href")
                    if href:
                        nxt = urljoin(current_url, href)
                        if nxt != current_url:
                            return nxt
            except Exception:
                continue

        # Query-parameter increment (e.g. ?page=2)
        return self._try_increment_page_param(current_url, soup)

    def _try_increment_page_param(self, url: str, soup: BeautifulSoup) -> str | None:
        from urllib.parse import parse_qs, urlencode, urlunparse
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for param in ("page", "p", "pg", "offset", "start"):
            if param in params:
                try:
                    val = int(params[param][0])
                    params[param] = [str(val + 1)]
                    new_query = urlencode(params, doseq=True)
                    new_url = urlunparse(parsed._replace(query=new_query))
                    if soup.find("a", href=re.compile(rf"{param}={val + 1}")):
                        return new_url
                except (ValueError, KeyError):
                    pass
        return None

    def _heuristic_article_links(self, soup: BeautifulSoup) -> list:
        return [
            a for a in soup.find_all("a", href=True)
            if len(a.get_text(strip=True)) > 15
            and not a["href"].startswith(("#", "javascript"))
        ]

    @staticmethod
    def _is_article_url(url: str, domain: str) -> bool:
        parsed = urlparse(url)
        if domain not in parsed.netloc:
            return False

        path = parsed.path.rstrip("/")

        # Skip utility / taxonomy pages
        skip = [
            "/tag/", "/tags/", "/category/", "/categorie/", "/categoria/",
            "/autor/", "/author/", "/autori/",
            "/page/", "/pagina/",
            "/search", "/cautare",
            "/feed", ".xml", ".rss",
            "/login", "/register", "/abonare",
            "/contact", "/despre", "/about",
        ]
        if any(s in path for s in skip):
            return False

        # Must have at least one non-empty path segment (not the bare root "/").
        parts = [p for p in path.split("/") if p]
        return len(parts) >= 1


# ── SiteNavigator ──────────────────────────────────────────────────────────────

class SiteNavigator:
    """
    Full-site crawler.

    1. Renders the site's base URL and discovers all section/category URLs from
       navigation menus and header links.
    2. For each section (including the homepage itself):
         - Fetches the page. If engine supports infinite scroll, scrolls until
           all items are loaded before extracting links.
         - Follows next-page links for conventional paginated sections.
         - Calls SelectorClient.get_or_discover() on every page; selectors that
           fail validation trigger transparent LLM re-discovery.
    3. Returns a flat, deduplicated list of article URLs.
    """

    def __init__(
        self,
        engine,
        selector_client,
        max_sections: int = 50,
        max_pages_per_section: int = 10,
        scroll_max: int = 20,
        scroll_wait_ms: int = 1500,
    ):
        self.engine = engine
        self.selector_client = selector_client
        self.max_sections = max_sections
        self.max_pages_per_section = max_pages_per_section
        self.scroll_max = scroll_max
        self.scroll_wait_ms = scroll_wait_ms

    # ── Public ─────────────────────────────────────────────────────────────────

    async def collect_all_article_urls(
        self, base_url: str, domain: str
    ) -> list[str]:
        """
        Discover sections from the homepage and collect article URLs from each.
        The base URL itself is always included as the first section.
        """
        # Render homepage
        try:
            homepage_html = await self._fetch(base_url, domain)
        except Exception as exc:
            logger.error("homepage_fetch_failed", url=base_url, domain=domain, error=str(exc))
            return []

        # Discover sections from nav/menu
        section_urls = self._discover_section_urls(homepage_html, base_url, domain)
        all_sections = list(dict.fromkeys([base_url] + section_urls))[: self.max_sections + 1]

        logger.info(
            "sections_discovered",
            domain=domain,
            total=len(all_sections),
            sections=all_sections[:10],
        )

        # Collect article URLs from each section
        all_article_urls: list[str] = []
        visited_sections: set[str] = set()

        for section_url in all_sections:
            if section_url in visited_sections:
                continue
            visited_sections.add(section_url)

            try:
                # Pass cached homepage HTML to avoid a second fetch for the first section
                cached_html = homepage_html if section_url == base_url else ""
                urls = await self._collect_from_section(section_url, domain, cached_html)
                new_urls = [u for u in urls if u not in all_article_urls]
                all_article_urls.extend(new_urls)
                logger.info(
                    "section_collected",
                    section=section_url,
                    domain=domain,
                    new_urls=len(new_urls),
                    total=len(all_article_urls),
                )
            except Exception as exc:
                logger.warning("section_failed", section=section_url, error=str(exc))

        return all_article_urls

    # ── Section collection ─────────────────────────────────────────────────────

    async def _collect_from_section(
        self, section_url: str, domain: str, cached_html: str = ""
    ) -> list[str]:
        """
        Collect all article URLs from one section.

        If BrowserEngine is the active engine:
          - Use get_with_infinite_scroll() on every listing page so all
            dynamically-loaded cards are present before link extraction.
        Fall back to link-based pagination regardless of engine.
        """
        # Load the first page (use cached HTML when available)
        if cached_html:
            first_html = cached_html
        elif self._has_infinite_scroll():
            first_html = await self.engine.get_with_infinite_scroll(section_url)
        else:
            first_html = await self._fetch(section_url, domain)

        # Discover / validate selectors for this section page
        selectors = await self.selector_client.get_or_discover(
            domain=domain,
            sample_url=section_url,
            html=first_html,
            page_type="listing",
        )

        article_urls: list[str] = []
        visited_pages: set[str] = set()
        current_url: str | None = section_url
        page_num = 0

        while (
            current_url
            and current_url not in visited_pages
            and page_num < self.max_pages_per_section
        ):
            visited_pages.add(current_url)
            page_num += 1

            # Reuse pre-fetched HTML for first page; fetch subsequent pages
            if page_num == 1:
                page_html = first_html
            else:
                try:
                    if self._has_infinite_scroll():
                        page_html = await self.engine.get_with_infinite_scroll(
                            current_url,
                            article_selector=selectors.article_links_selector,
                            max_scrolls=self.scroll_max,
                            wait_ms=self.scroll_wait_ms,
                        )
                    else:
                        page_html = await self._fetch(current_url, domain)
                except Exception as exc:
                    logger.warning(
                        "section_page_fetch_failed", url=current_url, error=str(exc)
                    )
                    break

                # Re-validate selectors for subsequent pages; re-discover on failure
                if not self.selector_client._validate_selectors(
                    selectors, page_html, "listing"
                ):
                    logger.info(
                        "selector_re_discovery",
                        url=current_url,
                        domain=domain,
                        reason="validation_failed_on_page",
                    )
                    selectors = await self.selector_client.get_or_discover(
                        domain=domain,
                        sample_url=current_url,
                        html=page_html,
                        page_type="listing",
                    )

            soup = BeautifulSoup(page_html, "lxml")
            paginator = Paginator(self.engine, selectors, max_pages=1)
            new_urls = paginator._extract_article_links(soup, current_url, domain)
            article_urls.extend(u for u in new_urls if u not in article_urls)

            logger.debug(
                "section_page_done",
                url=current_url,
                page=page_num,
                new=len(new_urls),
                total=len(article_urls),
            )

            current_url = paginator._find_next_page(soup, current_url)

        return article_urls

    # ── Section discovery ──────────────────────────────────────────────────────

    def _discover_section_urls(
        self, html: str, base_url: str, domain: str
    ) -> list[str]:
        """
        Extract section / category URLs from the homepage.

        Scans nav, header, and menu elements. Filters out:
          - External domains
          - Utility / non-content pages (login, tags, search, …)
          - Paths deeper than 2 levels (likely articles, not sections)
          - Links with no visible text
        """
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return []

        seen: set[str] = set()
        candidates: list[str] = []

        for nav_sel in SECTION_NAV_SELECTORS:
            try:
                for el in soup.select(nav_sel):
                    href = el.get("href", "")
                    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                        continue

                    full_url = urljoin(base_url, href)
                    parsed = urlparse(full_url)

                    if domain not in parsed.netloc:
                        continue

                    path = parsed.path.lower()
                    if any(skip in path for skip in _SECTION_SKIP):
                        continue

                    # Skip the homepage itself
                    if not path or path == "/":
                        continue

                    # Skip deep paths that look like articles
                    depth = len([p for p in path.split("/") if p])
                    if depth >= 3:
                        continue

                    # Require some link text
                    if len(el.get_text(strip=True)) < 2:
                        continue

                    # Normalise (strip trailing slash, drop query/fragment)
                    canonical = (
                        parsed.scheme + "://" + parsed.netloc + parsed.path.rstrip("/")
                    )
                    if canonical not in seen:
                        seen.add(canonical)
                        candidates.append(full_url)
            except Exception:
                continue

        return candidates[: self.max_sections]

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _fetch(self, url: str, domain: str = "") -> str:
        """Unified fetch — works with both BrowserEngine and HttpEngine."""
        if self._has_infinite_scroll():
            return await self.engine.get(url)
        return await self.engine.get(url, domain=domain)

    def _has_infinite_scroll(self) -> bool:
        """True when the active engine is BrowserEngine (has get_with_infinite_scroll)."""
        return hasattr(self.engine, "get_with_infinite_scroll")
