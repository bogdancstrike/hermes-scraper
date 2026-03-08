# Full Functionality and Flow Documentation
# LLM-Augmented Web Scraper

> **Version:** 1.0 | **Updated:** 2026-03-08

This document provides deep, exhaustive documentation of every significant function, class, module, and runtime flow in the LLM-Augmented Web Scraper. It is intended for maintainers extending the codebase, engineers debugging issues, and architects reviewing the design.

---

## Table of Contents

1. [Module: app.py](#1-module-apppy)
2. [Module: scraper/config.py](#2-module-scraperconfigpy)
3. [Module: scraper/engines/browser_engine.py](#3-module-scraperenginsbrowser_enginepy)
4. [Module: scraper/fetchers/static_fetcher.py](#4-module-scraperfetchersstatic_fetcherpy)
5. [Module: scraper/detectors/anti_bot.py](#5-module-scraperdetectorsanti_botpy)
6. [Module: scraper/navigation/paginator.py](#6-module-scrapernavigationpaginatorpy)
7. [Module: scraper/selector_client.py](#7-module-scraperselector_clientpy)
8. [Module: scraper/knowledge/site_knowledge.py](#8-module-scraperknowledgesite_knowledgepy)
9. [Module: shared/db.py](#9-module-shareddbpy)
10. [Module: shared/article_store.py](#10-module-sharedarticle_storepy)
11. [Module: shared/models.py](#11-module-sharedmodelspy)
12. [Module: shared/url_utils.py](#12-module-sharedurl_utilspy)
13. [Module: shared/logging.py](#13-module-sharedloggingpy)
14. [Module: shared/metrics.py](#14-module-sharedmetricspy)
15. [Module: processing/filters/extractor.py](#15-module-processingfiltersextractorpy)
16. [Module: processing/extractors/jsonld.py](#16-module-processingextractorsjsonldpy)
17. [Module: processing/extractors/og_meta.py](#17-module-processingextractorsoG_metapy)
18. [Module: processing/extractors/htmldate_extractor.py](#18-module-processingextractorshtmldate_extractorpy)
19. [Module: processing/extractors/readability_extractor.py](#19-module-processingextractorsreadability_extractorpy)
20. [Module: processing/scoring/merge.py](#20-module-processingscoringmergepy)
21. [Module: processing/scoring/quality.py](#21-module-processingscoringqualitypy)
22. [Module: processing/enrichers/email_extractor.py](#22-module-processingenrichersemail_extractorpy)
23. [Module: processing/enrichers/hashtag_extractor.py](#23-module-processingenrichershashtag_extractorpy)
24. [Module: processing/enrichers/screenshot.py](#24-module-processingenrichersscreenshotpy)
25. [Module: llm_api/llm_client.py](#25-module-llm_apillm_clientpy)
26. [Module: llm_api/prompts.py](#26-module-llm_apipromptspy)
27. [Cross-Cutting Flows](#27-cross-cutting-flows)
28. [Test Suite Documentation](#28-test-suite-documentation)

---

## 1. Module: `app.py`

**Role**: CLI entry point and pipeline orchestrator. This is the only runnable script in standalone mode. All other modules are libraries invoked from here.

**Location**: `/app.py`

---

### `_parse_args() → argparse.Namespace`

**Purpose**: Parse command-line arguments.

**Arguments**:
| Argument | Short | Type | Default | Description |
|----------|-------|------|---------|-------------|
| `--website` | `-w` | str | required | Domain to scrape (e.g. `adevarul.ro`) |
| `--pages` | `-p` | int | `SCRAPER_MAX_PAGES` env (def: 5) | Max listing pages per section |
| `--articles` | `-a` | int | `SCRAPE_LIMIT` env (def: 100) | Max total articles |
| `--output` | `-o` | str | `OUTPUT_DIR` env (def: `output`) | Output directory path |

**Side effects**: None. Pure argument parsing.

**Usage context**: Called once at startup in `_main()`.

---

### `_build_llm_client() → LLMClient | None`

**Purpose**: Lazily initialize the LLM client based on available API keys.

**Algorithm**:
1. Check for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `LLM_BASE_URL` in environment
2. If none found: log `no_llm_configured` warning and return `None`
3. If found: import and instantiate `LLMClient()` from `llm_api.llm_client`
4. If instantiation fails: log `llm_client_init_failed` warning and return `None`

**Behavior when returning `None`**: `SelectorClient` operates without LLM fallback — cache misses result in empty selectors, and sites with no cached selectors will produce zero article URLs.

**Design note**: The LLM client is deliberately lazy (not instantiated at module load) because: (a) it requires API keys that may not be present, (b) the Anthropic/OpenAI SDK imports are expensive, (c) most runs use cached selectors and never need the LLM.

---

### `_init_db() → bool`

**Purpose**: Establish database connection and ensure schema exists.

**Steps**:
1. `init_pool()` — creates asyncpg connection pool
2. `run_schema()` — executes all `CREATE TABLE IF NOT EXISTS` DDL statements
3. Returns `True` if both succeed

**Failure behavior**: Catches any exception. Logs `db_unavailable` warning. Returns `False`. The rest of the pipeline uses `db_ok=False` to skip all DB operations and fall back to file persistence.

**Idempotency**: `run_schema()` is safe to run multiple times. All `CREATE TABLE IF NOT EXISTS` statements are no-ops if tables exist.

---

### `_enrich_article(article: dict, html: str) → dict`

**Purpose**: Apply optional content enrichments based on configuration flags.

**Enrichments**:
| Flag | Enricher | Output Field |
|------|---------|-------------|
| `config.extract_emails` | `processing.enrichers.email_extractor.extract_emails()` | `article["emails"]` |
| `config.extract_hashtags` | `processing.enrichers.hashtag_extractor.extract_hashtags()` | `article["hashtags"]` |

**Inputs**:
- `article`: The assembled article dict (title, content, etc. already populated)
- `html`: Raw HTML of the article page (for email/hashtag extraction from markup)

**Returns**: The same `article` dict with enrichment fields added.

**Side effects**: None. Purely additive.

**Design note**: Enrichers are imported lazily (inside the `if` block) so their dependencies (e.g. regex compilation) are only loaded if the feature is enabled.

---

### `scrape_website(domain, max_pages, max_articles, output_dir) → list[dict]`

**Purpose**: Full pipeline for one website. This is the core of the application.

**Phase 1 — URL Discovery**:
```
1. _init_db() → db_ok
2. upsert_site(domain, start_url)
3. SiteKnowledgeRepository.load(domain) → SiteProfile
4. _build_llm_client() → llm_client
5. SelectorClient(llm_client)
6. ArticleStore(db_ok, ndjson_path)
7. async with BrowserEngine() as browser:
8.     SiteNavigator.collect_all_article_urls(start_url, domain)
9.     → canonicalize_url() all URLs
10.    → dict.fromkeys() for in-run dedup
11.    → filter_unscraped_urls() for cross-run dedup
12.    → truncate to max_articles
```

**Phase 2 — Article Extraction**:
```
13. asyncio.gather([fetch_and_extract(url) for url in article_urls])
14.    (each runs under asyncio.Semaphore(SCRAPER_CONCURRENCY))
15. filter(None, results) → articles
16. mark_urls_scraped(domain, [a["url"] for a in articles])
```

**Cleanup**:
```
17. article_store.close()
18. selector_client.close()
19. close_pool()
```

**Returns**: List of article dicts for all successfully extracted and persisted articles.

**Error propagation**: Any error in Phase 1 (e.g., `no_article_urls_found`) causes early return of empty list. Phase 2 errors are per-article and do not propagate.

---

### `fetch_and_extract(url: str) → dict | None` (inner closure)

**Purpose**: Process a single article URL end-to-end: fetch → extract → enrich → persist.

This is an inner closure inside `scrape_website()`. It captures: `browser`, `selector_client`, `site_profile`, `knowledge`, `article_store`, `config`, `output_dir`, `domain`.

**Concurrency**: Wrapped by `async with sem:` (asyncio.Semaphore) to limit simultaneous executions.

**Step-by-step**:
1. `canonicalize_url(url)` — strip tracking params
2. `site_profile.recommend_fetch_method()` → strategy
3. **Static fetch attempt** (if strategy is `static` or `unknown`):
   - `fetch_static(canonical)` → `{html, block_signals, latency_ms}`
   - `is_blocked(block_signals)` — if blocked or HTML < 500 chars: fall through
   - If OK: record static success via `knowledge.record_static_success()`
4. **Playwright fallback** (if static failed):
   - If `config.capture_screenshot`: `browser.get_with_screenshot()` → HTML + save screenshot
   - Otherwise: `browser.get(url)` → HTML
   - If Playwright throws: log warning, `knowledge.record_article_fetched(..., success=False)`, return `None`
5. `extract_main_content(html, url)` → result dict
   - If empty: return `None`
6. **Quality gate**: `len(title) < config.min_title_length` → return `None`
7. **ArticleRecord assembly**: All fields mapped from extraction result
8. **Enrichment**: `_enrich_article(article, html)`
9. **Knowledge updates**: `record_metadata_signals()`, `record_article_fetched(..., success=True)`
10. **Persistence**: `await article_store.save(article)`
11. Return `article`

**When `None` is returned**: The result is filtered from the final `articles` list. The article is not persisted and not counted.

---

### `export_results(articles, domain, output_dir) → dict[str, Path]`

**Purpose**: Write JSON and CSV export files for a completed run.

**JSON output** (`{timestamp}.json`):
```json
{
  "domain": "biziday.ro",
  "scraped_at": "2026-03-08T10:15:00",
  "total": 48,
  "articles": [...]
}
```

**CSV output** (`{timestamp}.csv`):
Columns: `url, domain, title, author, published_date, language, word_count, overall_score, fetch_method, scraped_at`

Uses `extrasaction="ignore"` so additional article fields (tags, keywords, etc.) are silently excluded from CSV without error.

**Returns**: Dict mapping `"json"` and `"csv"` to their file paths.

---

## 2. Module: `scraper/config.py`

**Role**: Central configuration definition. Single source of truth for all tunable parameters.

### `ScraperConfig` (Pydantic BaseSettings)

All fields use `Field(default, alias="ENV_VAR_NAME")`. The `alias` is the environment variable name that overrides the default.

**Key behaviors**:
- `model_config = {"env_file": ".env", "extra": "ignore", "populate_by_name": True}`
  - `env_file`: Load from `.env` in the current working directory
  - `extra = "ignore"`: Unknown env vars don't cause validation errors
  - `populate_by_name = True`: Fields can be accessed by Python name OR alias

**Singleton pattern**: `config = ScraperConfig()` at module level. All other modules import `from scraper.config import config` — no re-instantiation.

**Extension note**: Adding a new config value requires:
1. Adding a `Field` in `ScraperConfig`
2. Documenting the env var in `.env.example`
3. The value is immediately available anywhere via `config.field_name`

---

## 3. Module: `scraper/engines/browser_engine.py`

**Role**: Full headless browser control. Manages the Playwright lifecycle, stealth, overlays, scrolling, and screenshots.

### `BrowserEngine` (async context manager)

**Instance state**: `_playwright`, `_browser`, `_context`, `_page` — all initialized in `__aenter__`.

---

### `__aenter__(self) → BrowserEngine`

**Browser launch args** (all required for Docker/CI stability):
- `--no-sandbox`: Required when running as root in Docker
- `--disable-gpu`: Prevents GPU-related crashes in headless mode
- `--disable-dev-shm-usage`: Prevents `/dev/shm` exhaustion on low-memory systems
- `--disable-extensions`: Reduces attack surface and startup time

**Stealth mode** (when `USE_STEALTH=True`):
- Uses `playwright_stealth.stealth_async(page)` to patch:
  - `navigator.webdriver` → undefined (not `true`)
  - `window.chrome` → present (fake Chrome runtime)
  - `navigator.plugins` → non-empty
  - Permission APIs → realistic responses
  - WebGL vendor/renderer → realistic strings

**Context settings**:
- `user_agent`: From `ua_rotator` (random desktop UA per session)
- `viewport`: `{"width": 1366, "height": 768}` — most common desktop resolution
- `locale`: `"en-US"` — consistent behavior regardless of operator locale
- `timezone_id`: `"America/New_York"` — US-based timezone for consistency

---

### `get(url: str, wait_for: str = "domcontentloaded") → str`

**Algorithm**:
1. `page.goto(url, wait_until=wait_for, timeout=BROWSER_TIMEOUT)` — navigate
2. `_dismiss_overlays()` — remove cookie banners
3. 5 iterations of `page.evaluate("window.scrollBy(0, 800)")` + `asyncio.sleep(1.5)` — trigger lazy loading
4. `page.content()` → return HTML

**wait_for values**:
- `"domcontentloaded"`: Wait until DOM is parsed (faster, may miss late-loading JS content)
- `"networkidle"`: Wait until no network requests for 500ms (slower, more complete)

**When to use `networkidle`**: Sites that load article content via XHR after DOM load. Set `NAVIGATION_STRATEGY=networkidle` in `.env`.

---

### `get_with_infinite_scroll(url: str, max_scrolls: int, wait_ms: int) → str`

**Algorithm**:
1. Navigate to URL
2. `_dismiss_overlays()`
3. Track `prev_length = 0`
4. Loop up to `max_scrolls`:
   a. Scroll to bottom: `window.scrollTo(0, document.body.scrollHeight)`
   b. Sleep `wait_ms` milliseconds
   c. Get current page content length
   d. If length == `prev_length`: increment stability counter
   e. If stability counter >= 3: break (stable — no more content loading)
   f. Try clicking "Load More" button (various selectors)
   g. Update `prev_length`
5. Return `page.content()`

**Load More selectors tried** (in order):
```python
["button[class*='load-more']", "a[class*='load-more']",
 "button[data-testid*='load']", ".load-more-button", "#load-more"]
```

**Performance consideration**: With `max_scrolls=20` and `wait_ms=1500`, worst case is 30 seconds per section page. This is only used when pagination is absent.

---

### `get_with_screenshot(url: str, path: str, wait_for: str, screenshot_type: str) → str`

**Steps**:
1. Navigate and dismiss overlays (same as `get()`)
2. Ensure parent directory of `path` exists
3. `page.screenshot(path=path, full_page=True, type=screenshot_type, quality=80 if jpeg else None)`
4. Return `page.content()`

**Quality note**: JPEG quality 80 provides good visual fidelity at ~60-80% smaller file size than PNG. PNG is lossless but significantly larger for full-page screenshots.

**Failure behavior**: If screenshot fails (disk full, permission error), the exception is caught by the caller in `app.py`, logged, but the HTML extraction continues.

---

### `_dismiss_overlays(self)`

**CSS injection** (hides matching elements):
```css
[class*='cookie'], [class*='consent'], [class*='gdpr'],
[class*='newsletter'], [class*='popup'], [class*='modal'],
[class*='overlay'], [id*='cookie'], [id*='consent'],
[id*='gdpr'], [id*='newsletter'], [id*='popup'], [id*='modal'],
.cookie-notice, .cookie-banner, .cookie-wall
{ display: none !important; visibility: hidden !important; }
```

**Button click JS** (matches by text content):
```javascript
const accept_texts = ['accept', 'agree', 'allow', 'ok', 'got it',
                      'accepta', 'acceptă', 'sunt de acord'];
for (const btn of document.querySelectorAll('button, a, [role="button"]')) {
    if (accept_texts.some(t => btn.textContent.toLowerCase().trim().startsWith(t))) {
        btn.click(); break;
    }
}
```

**Scroll restoration**:
```javascript
document.body.style.overflow = 'auto';
document.documentElement.style.overflow = 'auto';
```

**Error handling**: All JS execution is wrapped in try/except. Overlay dismissal failures are non-fatal.

---

## 4. Module: `scraper/fetchers/static_fetcher.py`

**Role**: Fast, stealthy HTTP fetching using TLS fingerprint impersonation.

### `fetch_static(url: str) → dict`

**Algorithm**:

```
1. Random jitter: sleep(random.uniform(0.15, 0.75))
2. Try curl-cffi (up to 3 attempts):
   a. curl-cffi.requests.get(url, impersonate="chrome124", headers=HEADERS, timeout=30)
   b. On success: parse response → return result dict
   c. On curl-cffi exception: retry with 1s backoff
3. On curl-cffi failure: fall back to requests library
   a. requests.get(url, headers=REQUESTS_HEADERS, timeout=20)
4. Run is_blocked() on result
5. Return standard result dict
```

**HEADERS** (for curl-cffi — Chrome 124 realistic):
```python
{
    "Accept": "text/html,application/xhtml+xml,...",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
```

**Why Romanian Accept-Language**: This scraper primarily targets Romanian news sites. Romanian locale often triggers server-side content selection, returning Romanian article content rather than an English default.

**Return schema**:
```python
{
    "html": str,               # Response body as text
    "final_url": str,          # After redirects
    "status_code": int,
    "headers": dict,           # Response headers
    "latency_ms": int,         # Time from request send to response body received
    "method": str,             # "curl_cffi" or "requests"
    "block_signals": list[str],# ["cloudflare", "rate_limit", etc.]
    "error": str | None,       # Exception message if all attempts failed
}
```

**curl-cffi TLS impersonation**: The `impersonate="chrome124"` parameter makes curl-cffi use Chrome 124's exact TLS ClientHello: cipher suites, extensions, elliptic curves, and ALPN in Chrome's exact order. Systems using JA3/JA4 fingerprinting cannot distinguish this from a real Chrome browser.

---

## 5. Module: `scraper/detectors/anti_bot.py`

**Role**: Detect WAF and anti-bot protection signals in HTTP responses.

### `is_blocked(signals: list[str]) → bool`

**Input**: A list of signal strings from `detect_block_signals()`.
**Output**: `True` if the response represents a hard block (should trigger fallback); `False` if safe to proceed.

**Paywall handling**: Paywall signals are detected but treated as soft blocks (`is_blocked()` returns `False` for paywalls). The content is still extracted and marked with `likely_paywalled=True`.

---

### `detect_block_signals(html: str, status_code: int, headers: dict) → list[str]`

**Detection categories**:

| Signal | Detection Method |
|--------|-----------------|
| `"cloudflare"` | `cf-ray` header present OR HTML contains "attention required" + "cf-ray" |
| `"datadome"` | `x-datadome-*` header OR HTML contains `__ddg` |
| `"captcha"` | HTML contains "recaptcha", "hcaptcha", "are you a robot" |
| `"js_challenge"` | HTML contains "javascript required", "javascript must be enabled" |
| `"rate_limit"` | HTTP status 429 |
| `"server_error"` | HTTP status 403, 503, 520–524 |
| `"bot_protection"` | HTML contains "security check", "ddos protection" |
| `"paywall"` | HTML contains "subscribe to continue", "abonează-te", "premium content" |

**HTML scanning scope**: First 8,192 bytes of HTML (case-insensitive). This avoids scanning full article content while catching challenge pages that typically appear at the top.

**Performance**: O(n) where n = 8KB = constant. Very fast.

---

## 6. Module: `scraper/navigation/paginator.py`

**Role**: Discovers site sections and traverses listing pages to collect article URLs.

### Constants

**`FALLBACK_NEXT_SELECTORS`** (16 patterns):
```python
["a[rel='next']", "a.next", "a.next-page", ".pagination a.next",
 ".pager a.next", "li.next a", "[aria-label='Next page']",
 "[aria-label='Next']", ".pagination__next",
 "button[data-testid='pagination-next']", ...]
```

**`SECTION_NAV_SELECTORS`** (14 patterns):
```python
["nav a[href]", "header a[href]", "[role='navigation'] a[href]",
 ".nav a[href]", ".navigation a[href]", ".menu a[href]",
 "#nav a[href]", "#menu a[href]", "#header a[href]",
 ".main-menu a[href]", ".site-menu a[href]", ".navbar a[href]",
 ".sidebar a[href]", "aside a[href]"]
```

**`_SECTION_SKIP`** (37 patterns):
Tag pages, author pages, search, login, feed, RSS, CDN paths (`/cdn-cgi/`), social media, API endpoints, legal pages, error pages, ads, and pagination artifacts. This list is critical for focusing on content sections, not utility pages.

---

### `class Paginator`

**Purpose**: Traverse a single section's listing pages, extracting article URLs from each page.

#### `__init__(engine, selector_client, domain, page_type)`

Stores references to the browser engine and selector client. Does not perform any I/O.

#### `collect_article_urls(section_url: str, max_pages: int) → list[str]`

**Algorithm**:
```
current_url = section_url
all_urls = []
for page_num in range(max_pages):
    html = await engine.get(current_url)
    selectors = await selector_client.get_or_discover(domain, current_url, html, page_type)
    page_urls = _extract_article_urls(html, selectors.article_links_selector, domain)
    all_urls.extend(page_urls)
    next_url = _get_next_page_url(html, selectors.pagination_next_selector, current_url)
    if not next_url or next_url == current_url:
        break
    current_url = next_url
return all_urls
```

#### `_extract_article_urls(html, selector, domain) → list[str]`

**Steps**:
1. `BeautifulSoup(html).select(selector)` → list of `<a>` elements
2. For each `<a>`:
   - Get `href`, make absolute via `urljoin(base, href)`
   - Check domain match: `extract_domain(url) == domain`
   - Check not a pagination URL: no `?page=`, no `/page/N`
   - Check link text length > 15 chars (excludes nav labels)
   - Check not in `_URL_SKIP` list
3. Return unique valid URLs

**URL validation skip list** (`_URL_SKIP`):
Includes CDN-CGI paths, tag/category pages when they appear in article lists, feed URLs, login/auth endpoints, social share buttons.

#### `_get_next_page_url(html, selector, current_url) → str | None`

**Algorithm**:
1. Try LLM-discovered `selector` first
2. If no match: try each of `FALLBACK_NEXT_SELECTORS` in order
3. If still no match: try query parameter increment:
   - Detect `?page=N`, `?p=N`, `?pg=N`, `?offset=N`, `?start=N` patterns
   - Increment N by 1 (or by detected page size for `offset`)
4. Validate next URL is different from current URL (prevents loops)
5. Return absolute URL or `None`

---

### `class SiteNavigator`

**Purpose**: Orchestrates full-site URL discovery across all sections.

#### `collect_all_article_urls(start_url: str, domain: str) → list[str]`

**Algorithm**:
```
1. html = await engine.get(start_url)  (homepage)
2. sections = _discover_sections(html, start_url)
3. all_urls = []
4. for section_url in sections[:max_sections]:
       urls = await _collect_urls_from_section(section_url, domain)
       all_urls.extend(urls)
5. return deduplicated all_urls
```

**Caching optimization**: The homepage HTML is fetched once and passed to `_discover_sections`. The same HTML is also passed to `selector_client.get_or_discover()` for the homepage section, avoiding a second fetch.

#### `_discover_sections(html: str, base_url: str) → list[str]`

**Algorithm**:
1. Try each `SECTION_NAV_SELECTORS` in order
2. First selector that returns ≥ 3 links is used (avoids degenerate cases)
3. For each `<a href>`:
   - Make URL absolute
   - Check `_is_valid_section(url, base_url)`
4. Return unique valid section URLs

#### `_is_valid_section(url: str, base_url: str) → bool`

Checks:
- Same domain as `base_url`
- URL path in `_SECTION_SKIP` patterns → reject
- URL is not identical to `base_url` (skip homepage itself)
- Path depth ≤ 2 segments (avoids deeply nested pages)
- Not a file URL (no `.pdf`, `.jpg`, `.zip` extension)

**Path depth heuristic**: `/tech/` (depth 1) → valid section. `/tech/ai/article-title` (depth 3) → likely an article, not a section. This prevents treating article URLs as sections.

---

## 7. Module: `scraper/selector_client.py`

**Role**: Three-tier CSS selector cache and LLM-based discovery. The most complex module.

### `class SelectorClient`

**Constructor**: `SelectorClient(llm_client=None)`
- `llm_client=None`: Uses HTTP endpoint (`LLM_ENDPOINT/v1/analyze-selectors`) for LLM calls
- `llm_client=<LLMClient>`: Calls LLM directly (standalone mode — no HTTP hop)

The direct client mode is used when running `app.py` standalone. The HTTP endpoint mode is used in distributed architecture where `llm_api` is a separate service.

---

### `get_or_discover(domain, url, html, page_type="listing") → SiteSelectors`

**Full algorithm** (see C4 Architecture document for sequence diagram):

```python
async def get_or_discover(self, domain, url, html, page_type="listing"):
    # L1: Redis
    selectors = await self._get_from_redis(domain, page_type)
    if selectors:
        if self._validate_selectors(selectors, html):
            selector_cache_hits.labels(domain=domain).inc()
            return selectors
        await self._invalidate_redis(domain, page_type)

    # L2: PostgreSQL
    selectors = await self._get_from_postgres(domain, page_type)
    if selectors:
        if self._validate_selectors(selectors, html):
            await self._write_to_redis(domain, page_type, selectors)
            selector_cache_hits.labels(domain=domain).inc()
            return selectors
        await self._invalidate_postgres(domain, page_type)

    # L3: LLM
    selector_cache_misses.labels(domain=domain).inc()
    for attempt in range(self._retry_count):
        selectors = await self._call_llm(domain, url, html, page_type)
        await self._store_selectors(domain, page_type, selectors)
        if self._validate_selectors(selectors, html):
            return selectors
        await self._invalidate_caches(domain, page_type)

    return SiteSelectors()  # empty — all retries exhausted
```

---

### `_compact_dom(html: str) → str`

**Purpose**: Reduce HTML to a manageable representation for the LLM context window.

**Algorithm**:
1. `BeautifulSoup(html, "html.parser")`
2. `soup.decompose()` for all `script`, `style`, `svg`, `iframe` tags
3. For each element with a `class` attribute:
   - Filter each class name against Tailwind/utility patterns
   - Tailwind patterns (regex):
     - Single characters: `^[a-z]$`
     - Tailwind prefixes: `^(flex|grid|block|inline|hidden|p|m|w|h|text|font|bg|border|rounded|shadow|z|opacity|cursor|select|resize|overflow|whitespace|break|align|justify|items|content|space|gap|col|row|auto|fixed|absolute|relative|sticky|top|right|bottom|left|inset|sr|not)-`
     - Responsive prefixes: `^(sm|md|lg|xl|2xl):`
     - Dark mode: `^dark:`
     - Pseudo-classes: `^(hover|focus|active|visited|disabled|group|peer):`
     - Arbitrary values: contains `[` or `]`
   - If class list becomes empty: remove `class` attribute entirely
4. `str(soup)[:4000]` — truncate to 4,000 characters

**Why 4,000 chars**: Local models (qwen2.5-coder:7b) have limited effective context windows for following instruction-format prompts. 4,000 chars provides enough DOM structure for selector discovery while staying well within practical context limits.

---

### `_validate_selectors(selectors: SiteSelectors, html: str) → bool`

```python
def _validate_selectors(self, selectors, html):
    if not selectors.article_links_selector:
        return False
    if len(html) < 500:
        return True  # Too short to validate; assume OK (loading/error page)
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.select(selectors.article_links_selector)
    return len(elements) >= MIN_ARTICLE_LINKS  # MIN_ARTICLE_LINKS = 1
```

**Why validate only `article_links_selector`**: This is the most critical selector — it's the one that determines whether we can collect article URLs. The other selectors (title, date, author, body) are used during extraction, where fallback is handled by the multi-source extraction pipeline.

**Why HTML < 500 chars skips validation**: Short HTML typically indicates a redirect page, error page, or loading screen. These are transient states; the selector may be valid for the actual content page.

---

### `_store_selectors(domain, page_type, selectors) → None`

Writes to both Redis (L1) and PostgreSQL (L2) atomically:

**Redis write**:
```python
await redis.setex(
    f"selector:{domain}:{page_type}",
    REDIS_SELECTOR_TTL,  # 3600 seconds
    selectors.model_dump_json()
)
```

**PostgreSQL write**:
```sql
INSERT INTO site_selectors (domain, page_type, article_links_selector, ..., confidence, model_used)
VALUES ($1, $2, $3, ..., $N)
ON CONFLICT (domain, page_type) DO UPDATE SET
  article_links_selector = EXCLUDED.article_links_selector,
  ...,
  updated_at = NOW()
```

**Design**: Writing to both caches simultaneously avoids a cache-miss cascade on the next L1 check.

---

### `close() → None`

Closes the Redis connection pool. Must be called at end of run to avoid resource leaks.

In `app.py`, this is called in the cleanup section: `await selector_client.close()`.

---

## 8. Module: `scraper/knowledge/site_knowledge.py`

**Role**: Load, maintain, and persist per-domain scraping knowledge.

### `STRATEGY_*` Constants

```python
STRATEGY_STATIC = "static"
STRATEGY_PLAYWRIGHT = "playwright"
STRATEGY_API_INTERCEPT = "api_intercept"  # planned, not fully implemented
```

---

### `@dataclass SiteProfile`

**Fields**:
| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `domain` | str | required | Domain name |
| `is_known` | bool | False | Whether we have historical data |
| `preferred_fetch_method` | str | "playwright" | Best known fetch strategy |
| `requires_js` | bool | False | Site needs JS rendering |
| `is_spa` | bool | False | Single-page application |
| `has_cloudflare` | bool | False | Cloudflare WAF detected |
| `has_datadome` | bool | False | DataDome detected |
| `has_recaptcha` | bool | False | reCAPTCHA detected |
| `has_paywall` | bool | False | Paywall detected |
| `has_infinite_scroll` | bool | False | Infinite scroll detected |
| `has_jsonld` | bool | False | JSON-LD structured data present |
| `has_og_meta` | bool | False | Open Graph meta tags present |
| `avg_latency_ms` | int | 0 | Rolling average fetch latency |
| `avg_word_count` | int | 0 | Rolling average article word count |
| `total_scraped` | int | 0 | Cumulative successful article count |
| `total_failed` | int | 0 | Cumulative failed article count |
| `selector_failures` | int | 0 | Selector validation failure count |
| `block_rate` | float | 0.0 | Fraction of fetches that were blocked |

---

### `SiteProfile.recommend_fetch_method() → str`

**Logic**:
```python
def recommend_fetch_method(self) -> str:
    # SPAs and JS-required sites always need Playwright
    if self.is_spa or self.requires_js:
        return STRATEGY_PLAYWRIGHT

    # Static is preferred if it's been working and block rate is acceptable
    if self.preferred_fetch_method == STRATEGY_STATIC and self.block_rate < 0.30:
        return STRATEGY_STATIC

    # Default: Playwright (safe but slow)
    return STRATEGY_PLAYWRIGHT
```

**Block rate threshold (30%)**: If more than 30% of fetches are blocked, the scraper switches from static to Playwright for that domain. This balances: 30% block rate on static is acceptable (Playwright fallback handles blocked requests), but above 30% suggests the WAF specifically targets curl-cffi.

---

### `class SiteKnowledgeRepository`

#### `load(domain: str) → SiteProfile`

```python
async def load(self, domain: str) -> SiteProfile:
    if not self._db_ok:
        return SiteProfile(domain=domain)  # default profile

    row = await get_site_knowledge(domain)  # shared/db.py
    if not row:
        return SiteProfile(domain=domain, is_known=False)

    return SiteProfile(
        domain=domain,
        is_known=True,
        preferred_fetch_method=row["preferred_fetch_method"],
        has_cloudflare=row["has_cloudflare"],
        ...
    )
```

#### `record_article_fetched(domain, method, latency_ms, word_count, success, block_signals)`

**Updates `_profile` in memory**:
1. `total_scraped += 1` if success else `total_failed += 1`
2. Rolling latency: `avg_latency = old * 0.8 + new * 0.2`
3. Rolling word count: `avg_word_count = old * 0.8 + new * 0.2`
4. Block signal detection:
   - `"cloudflare"` in signals → `has_cloudflare = True`
   - `"datadome"` in signals → `has_datadome = True`
   - `"captcha"` in signals → `has_recaptcha = True`
5. Block rate calculation: running mean of `is_blocked` per fetch
6. If method is static and success: `preferred_fetch_method = static`
7. If block rate > 0.30: `preferred_fetch_method = playwright`

**Why not write to DB immediately**: Writing after every article would create N DB transactions per run. Instead, the profile is updated in memory and persisted once at run end. This is safe because the process is single-run and in-memory state is not shared.

#### `record_static_success(domain)`

Marks the domain as static-fetch capable. Called immediately when static fetch succeeds.

```python
async def record_static_success(self, domain: str):
    self._profile.preferred_fetch_method = STRATEGY_STATIC
```

#### `record_metadata_signals(domain, has_jsonld, has_og_meta)`

Updates boolean flags:
```python
if has_jsonld: self._profile.has_jsonld = True
if has_og_meta: self._profile.has_og_meta = True
```

These flags inform future extraction priority decisions (though currently they don't change extraction behavior — all 5 sources are always tried). In the future, knowing `has_jsonld=True` could allow skipping weaker extractors.

---

## 9. Module: `shared/db.py`

**Role**: All database interaction. asyncpg connection pool, schema creation, and helper functions for all tables.

### Connection Pool

```python
_pool: asyncpg.Pool | None = None

async def init_pool():
    global _pool
    _pool = await asyncpg.create_pool(config.postgres_dsn, min_size=2, max_size=10)

async def close_pool():
    if _pool:
        await _pool.close()

@asynccontextmanager
async def get_db():
    async with _pool.acquire() as conn:
        yield conn
```

**Pool sizing**: `min_size=2, max_size=10`. With `SCRAPER_CONCURRENCY=3` and selector cache operations, peak concurrency is well within 10 connections.

---

### `run_schema()`

Executes a large DDL string. All statements use `IF NOT EXISTS`. Safe to run on every startup.

Tables created (in order, respecting FK dependencies):
1. `sites`
2. `site_selectors`
3. `scrape_jobs` (FK to sites)
4. `scraper_nodes`
5. `robots_cache`
6. `scraped_urls`
7. `site_strategies`
8. `site_knowledge`
9. `scraped_articles`

**Indexes created**:
- `idx_scraped_urls_domain` on `scraped_urls(domain)`
- `idx_scraped_articles_domain` on `scraped_articles(domain)`
- `idx_scraped_articles_scraped_at` on `scraped_articles(scraped_at)`

---

### `upsert_site(domain, start_url) → None`

```sql
INSERT INTO sites (domain, start_url)
VALUES ($1, $2)
ON CONFLICT (domain) DO UPDATE SET
  start_url = EXCLUDED.start_url,
  updated_at = NOW()
```

Called once per run. Ensures the domain is registered in the sites table.

---

### `filter_unscraped_urls(urls: list[str]) → list[str]`

```python
async def filter_unscraped_urls(urls):
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT url FROM scraped_urls WHERE url = ANY($1::text[])",
            urls
        )
    scraped = {row["url"] for row in rows}
    return [u for u in urls if u not in scraped]
```

**Batch query**: Uses PostgreSQL `ANY($1::text[])` to check all URLs in a single query. This is critical for performance — checking 100 URLs takes ~1ms vs 100ms for 100 individual queries.

---

### `mark_urls_scraped(domain, urls) → None`

```sql
INSERT INTO scraped_urls (url, domain)
SELECT unnest($1::text[]), $2
ON CONFLICT (url) DO NOTHING
```

Uses `unnest()` to batch-insert multiple URLs efficiently. `ON CONFLICT DO NOTHING` handles concurrent runs attempting to insert the same URL.

---

### `save_article(article: dict) → None`

The most complex helper. Maps the full article dict to PostgreSQL columns.

**Key design**: `raw_json = article_dict_as_jsonb`. The entire article dict is stored as JSONB. This means:
- Schema changes don't require data migrations for existing columns
- New fields added to the article dict are automatically preserved in `raw_json`
- Query flexibility: PostgreSQL JSONB operators can access any field

**Idempotency**:
```sql
INSERT INTO scraped_articles (url, domain, title, ...)
VALUES ($1, $2, $3, ...)
ON CONFLICT (url) DO NOTHING
```

If the same article URL is inserted twice (from concurrent runs or retry), the second insert is silently discarded.

---

### `get_site_knowledge(domain) → dict | None`

```sql
SELECT * FROM site_knowledge WHERE domain = $1
```

Returns a row dict or `None` if the domain has no knowledge yet.

---

### `upsert_site_knowledge(domain, fields) → None`

```sql
INSERT INTO site_knowledge (domain, preferred_fetch_method, ..., avg_latency_ms, ...)
VALUES ($1, $2, ..., $N)
ON CONFLICT (domain) DO UPDATE SET
  preferred_fetch_method = EXCLUDED.preferred_fetch_method,
  avg_latency_ms = (
    site_knowledge.avg_latency_ms * 0.8 + EXCLUDED.avg_latency_ms * 0.2
  ),
  total_scraped = site_knowledge.total_scraped + EXCLUDED.total_scraped,
  updated_at = NOW()
```

**Rolling average in SQL**: The averaging formula `old * 0.8 + new * 0.2` runs server-side in the `DO UPDATE` clause. This ensures atomic updates even with concurrent scraper processes.

---

## 10. Module: `shared/article_store.py`

**Role**: Dual-sink article persistence with in-memory deduplication.

### `class ArticleStore`

**State**:
- `_db_ok: bool` — whether PostgreSQL is available
- `_ndjson: IO` — open file handle for appending
- `_seen_urls: set[str]` — in-memory URL dedup set

---

### `save(article: dict) → None`

**Step 1 — In-memory dedup**:
```python
if article["url"] in self._seen_urls:
    logger.debug("duplicate_skipped", url=article["url"])
    return
self._seen_urls.add(article["url"])
```

This O(1) check prevents the same URL from being written twice within a run, even if `asyncio.gather()` somehow processes the same URL twice (e.g., if it appeared in multiple sections).

**Step 2 — DB save** (if available):
```python
if self._db_ok:
    try:
        await save_article(article)
    except Exception as e:
        logger.error("article_db_save_failed", url=article["url"], error=str(e))
```

DB failures are caught and logged. NDJSON save still proceeds.

**Step 3 — NDJSON append**:
```python
line = json.dumps(article, ensure_ascii=False, default=str)
self._ndjson.write(line + "\n")
self._ndjson.flush()
```

`ensure_ascii=False`: Preserves Unicode characters (Romanian diacritics, etc.).
`default=str`: Handles non-serializable types (datetime objects) by converting to string.
`flush()`: Ensures the line is on disk immediately. Without this, a crash could lose buffered articles.

---

### `close() → None`

```python
def close(self):
    self._ndjson.flush()
    self._ndjson.close()
```

Final flush before close. Double-flush is safe and ensures no data loss.

---

## 11. Module: `shared/models.py`

**Role**: Pydantic model definitions for all data structures.

### `SiteConfig`

Represents a site to be scraped. Used in distributed scheduler mode.

Fields: `id`, `domain`, `name`, `start_url`, `schedule` (cron), `max_pages`, `active`

### `SiteSelectors`

The output of selector discovery. Used by `SelectorClient` and `SiteNavigator`.

Fields:
- `article_links_selector: str` — CSS selector for article links on listing pages
- `pagination_next_selector: str` — CSS selector for "next page" link
- `article_body_selector: str` — CSS selector for article content container
- `title_selector: str` — CSS selector for article title
- `date_selector: str` — CSS selector for publication date
- `author_selector: str` — CSS selector for author name
- `confidence: float` — LLM confidence in these selectors (0.0–1.0)
- `model_used: str` — Name of the LLM model that generated these selectors

**Default**: All selectors default to `""`. Empty string means "not known/not applicable".

### `ArticleRecord`

The canonical article schema. Contains all possible fields an article can have.

Key field groups:
- **Identity**: `url`, `canonical_url`, `domain`
- **Content**: `title`, `author`, `authors`, `content`, `summary`
- **Dates**: `published_date`, `updated_date`, `scraped_at`
- **Classification**: `language`, `article_type`, `publisher`
- **Media**: `top_image`, `tags`, `keywords`
- **Quality**: `overall_score`, `title_score`, `content_score`, `date_score`, `author_score`
- **Flags**: `likely_paywalled`, `likely_liveblog`
- **Provenance**: `field_sources`, `field_confidence`
- **Operational**: `fetch_method`, `fetch_latency_ms`, `word_count`, `reading_time_minutes`
- **Enrichments**: `emails`, `hashtags`, `screenshot_path`

---

## 12. Module: `shared/url_utils.py`

**Role**: URL normalization and domain extraction.

### `canonicalize_url(url: str) → str`

**Algorithm**:
1. Parse URL into components via `urllib.parse.urlparse()`
2. Parse query string via `urllib.parse.parse_qs(query, keep_blank_values=True)`
3. Remove tracking parameters (30+ patterns):
   - UTM: `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`
   - Google: `gclid`, `gclsrc`, `dclid`, `gbraid`, `wbraid`
   - Facebook: `fbclid`, `fb_action_ids`, `fb_action_types`
   - Microsoft: `msclkid`
   - HubSpot: `hsa_acc`, `hsa_cam`, `hsa_grp`, `hsa_ad`, etc.
   - Mailchimp: `mc_cid`, `mc_eid`
   - GA: `_ga`, `_gl`
   - Generic: `ref`, `referrer`, `source`
4. Reconstruct query string without removed params
5. Remove fragment (`#section`)
6. Normalize trailing slash (remove unless it's the root path `/`)
7. Return canonical URL

**Impact**: `https://biziday.ro/article?utm_source=facebook&utm_medium=social` → `https://biziday.ro/article`

This prevents the same article from appearing multiple times in the deduplication table with different tracking parameters.

### `extract_domain(url: str) → str`

```python
def extract_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = parsed.netloc or parsed.path.split("/")[0]
    return domain.removeprefix("www.")
```

Handles URLs with and without protocol prefix. Always strips `www.` prefix so `www.biziday.ro` and `biziday.ro` are treated as the same domain.

---

## 13. Module: `shared/logging.py`

**Role**: Configure structlog for the entire application.

### `get_logger(name: str) → structlog.BoundLogger`

Returns a logger bound with the given name as `logger` context key.

**Configuration** (applied globally at module load):

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,  # JSONRenderer or ConsoleRenderer based on LOG_FORMAT
    ],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    logger_factory=structlog.PrintLoggerFactory(),
)
```

**Noisy library suppression**:
```python
for lib in ["httpx", "asyncpg", "elasticsearch", "aiokafka", "playwright"]:
    logging.getLogger(lib).setLevel(logging.WARNING)
```

This prevents third-party library debug logs from flooding the output.

**Usage pattern**:
```python
logger = get_logger("module_name")
logger.info("event_name", key1="value1", key2="value2")
logger.warning("problem_detected", url=url, error=str(e))
```

All log events use snake_case event names (first positional arg) and keyword args for context.

---

## 14. Module: `shared/metrics.py`

**Role**: Prometheus metrics definitions. All metrics are module-level singletons.

### Defined Metrics

**Scraper**:
```python
pages_fetched_total = Counter("pages_fetched_total", "Total pages fetched", ["domain", "method"])
pages_blocked_total = Counter("pages_blocked_total", "Pages blocked", ["domain"])
jobs_completed_total = Counter("jobs_completed_total", "Completed jobs", ["site"])
fetch_duration_seconds = Histogram("fetch_duration_seconds", "Fetch duration", ["domain", "method"])
```

**LLM**:
```python
llm_requests_total = Counter("llm_requests_total", "LLM API requests", ["endpoint", "model", "status"])
llm_tokens_sent_total = Counter("llm_tokens_sent_total", "Approximate tokens sent", ["endpoint"])
llm_duration_seconds = Histogram("llm_duration_seconds", "LLM request duration", ["endpoint"])
```

**Selectors**:
```python
selector_cache_hits = Counter("selector_cache_hits_total", "Selector cache hits", ["domain"])
selector_cache_misses = Counter("selector_cache_misses_total", "Selector cache misses", ["domain"])
```

**Processing**:
```python
pages_processed_total = Counter("pages_processed_total", "Pages through pipeline")
dedup_rejections_total = Counter("dedup_rejections_total", "Dedup rejections")
```

**Observability**:
```python
active_jobs = Gauge("active_jobs", "Currently active scrape jobs")
```

**Usage**: Metrics are imported where needed:
```python
from shared.metrics import selector_cache_hits
selector_cache_hits.labels(domain=domain).inc()
```

Metrics are exposed on port `METRICS_PORT` (default 9090) via a Prometheus HTTP server started by the distributed services. In standalone mode, metrics are updated but not exposed (no HTTP server started).

---

## 15. Module: `processing/filters/extractor.py`

**Role**: Master extraction function. Orchestrates all extractors and returns a merged, quality-scored article dict.

### `extract_main_content(html: str, url: str) → dict | None`

**Algorithm**:

```python
def extract_main_content(html, url):
    sources = {}

    # Source 1: JSON-LD (highest confidence)
    try:
        data = extract_jsonld(html)
        if data and data.get("title"):
            sources["jsonld"] = {"data": data, "confidence": 0.97}
    except Exception:
        pass  # Non-fatal; continue with other sources

    # Source 2: Trafilatura (best body content extractor)
    try:
        traf_result = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            with_metadata=True,
        )
        if traf_result:
            traf_data = json.loads(traf_result)
            sources["trafilatura"] = {"data": traf_data, "confidence": 0.92}
    except Exception:
        pass

    # Source 3: Open Graph meta tags
    try:
        og_data = extract_og(html)
        if og_data:
            sources["og"] = {"data": og_data, "confidence": 0.80}
    except Exception:
        pass

    # Source 4: htmldate (specialized date extraction)
    try:
        date_str = find_date(html, url=url, extensive_search=True, original_date=True)
        if date_str:
            sources["htmldate"] = {"data": {"date": date_str}, "confidence": 0.90}
    except Exception:
        pass

    # Source 5: Readability (fallback for body content)
    traf_text = sources.get("trafilatura", {}).get("data", {}).get("text", "")
    if len(traf_text) < 100:
        try:
            read_data = extract_readability(html)
            if read_data:
                sources["readability"] = {"data": read_data, "confidence": 0.65}
        except Exception:
            pass

    if not sources:
        return None  # Nothing extracted

    # Merge by confidence
    merged, field_sources, field_confidence = merge_fields(sources)
    if not merged.get("title") and not merged.get("text"):
        return None  # No meaningful content

    # Quality scoring
    quality = compute_quality(merged)

    return {
        **merged,
        **quality,
        "field_sources": field_sources,
        "field_confidence": field_confidence,
    }
```

**Error handling per extractor**: Each extractor is wrapped in `try/except`. An extractor failure doesn't prevent other extractors from running. This is the key resilience property of the multi-source approach.

**Readability threshold (100 chars)**: Readability is only run when trafilatura extracts less than 100 characters. This avoids redundant computation when trafilatura works well, while providing a fallback for sites where trafilatura struggles.

**Return `None` conditions**:
1. All extractors produce nothing (`sources` is empty)
2. Merged result has no `title` AND no `text` (unusable)

---

## 16. Module: `processing/extractors/jsonld.py`

**Role**: Extract structured article data from JSON-LD (`<script type="application/ld+json">`) tags.

### `extract(html: str) → dict | None`

**Algorithm**:
1. `BeautifulSoup(html).find_all("script", type="application/ld+json")` → list of script tags
2. For each tag:
   a. Extract text content
   b. Clean trailing commas (common LLM/CMS authoring mistake): `re.sub(r',\s*([}\]])', r'\1', text)`
   c. `json.loads()` → dict or list
   d. If list: find item with `@type` matching article types
   e. If `@graph` present: recursively search graph nodes
3. Article type matching (15+ types):
   ```python
   ARTICLE_TYPES = {
       "article", "newsarticle", "blogposting", "reportage",
       "analysisnewsarticle", "opinionNewsarticle", "reviewNewsarticle",
       "satiricalArticle", "scholarlyArticle", "techArticle",
       "socialMediaPosting", "liveblogposting", "medicalwebpage",
       "webpageelement", "webpage"
   }
   ```
   (case-insensitive comparison)
4. Extract fields: `headline`, `name`, `author`, `datePublished`, `dateModified`, `description`, `url`, `image`, `publisher`, `keywords`, `articleSection`, `inLanguage`
5. Normalize `author`:
   - String: `{"name": author_string}`
   - Dict with `name`: `{"name": author["name"]}`
   - List of dicts/strings: First non-empty name

**Why JSON-LD is highest confidence**: JSON-LD is explicitly authored structured data. It's machine-readable markup that directly expresses the article's metadata according to schema.org vocabulary. Sites that use it tend to use it accurately because it affects SEO and rich results.

---

## 17. Module: `processing/extractors/og_meta.py`

**Role**: Extract metadata from Open Graph and HTML meta tags.

### `extract(html: str) → dict`

**Tags extracted**:
| Tag | Field |
|-----|-------|
| `og:title` | `title` |
| `og:description` | `description` |
| `og:image` | `image_url` |
| `og:url` | `url` |
| `og:type` | `type` |
| `article:published_time` | `date` |
| `article:modified_time` | `updated_date` |
| `article:author` | `author` |
| `twitter:title` | `title` (fallback if no og:title) |
| `twitter:description` | `description` (fallback) |
| `twitter:image` | `image_url` (fallback) |
| `description` | `description` (meta fallback) |
| `keywords` | `keywords` |
| `author` | `author` (meta fallback) |
| `canonical` link | `canonical_url` |
| `html[lang]` | `language` |

**Keyword parsing**: `meta name=keywords` content is split by commas: `"AI, machine learning, Python"` → `["AI", "machine learning", "Python"]`

**Language detection**: `<html lang="ro">` → `"ro"`. Falls back to None if not present.

---

## 18. Module: `processing/extractors/htmldate_extractor.py`

**Role**: Extract publication dates using the `htmldate` library.

### `extract(html: str, url: str) → dict | None`

```python
from htmldate import find_date

def extract(html, url):
    date = find_date(
        html,
        url=url,
        extensive_search=True,  # Search URL path, meta, visible text
        original_date=True,      # Prefer published over modified date
        output_format="%Y-%m-%dT%H:%M:%S",
    )
    return {"date": date} if date else None
```

**htmldate strategies** (applied in order):
1. Schema.org JSON-LD `datePublished`
2. Open Graph `article:published_time`
3. HTML `<time>` element `datetime` attribute
4. Meta tags: `pubdate`, `date`, `article:published_time`
5. URL path date patterns: `/2026/03/08/`
6. Visible text date patterns: "March 8, 2026" in body text
7. HTTP `Last-Modified` header

**Why a dedicated date extractor**: Publication dates appear in many inconsistent formats and locations across sites. `htmldate` has been specifically optimized for this task and outperforms general-purpose extractors at date mining.

**Confidence 0.90**: Slightly lower than JSON-LD (0.97) because htmldate uses heuristics that occasionally pick up modification dates or incorrect dates. When JSON-LD is available, it wins; htmldate fills in when JSON-LD is absent.

---

## 19. Module: `processing/extractors/readability_extractor.py`

**Role**: Mozilla Readability algorithm as content extraction fallback.

### `extract(html: str) → dict | None`

```python
from readability import Document
from html2text import html2text

def extract(html):
    doc = Document(html)
    summary_html = doc.summary()  # Returns cleaned HTML of main content
    text = html2text(summary_html)  # Convert to markdown-ish plaintext
    title = doc.title()

    # Minimum content threshold
    words = text.split()
    if len(words) < 50:
        return None  # Not enough content to be a real article

    return {"title": title, "text": text}
```

**When used**: Only when trafilatura extracts < 100 characters. This typically happens on:
- Sites with unusual HTML structures that confuse trafilatura's content scoring
- Pages with very short content (which Readability also filters by the 50-word threshold)
- JavaScript-rendered pages where Playwright failed to fully render content

**Confidence 0.65**: Readability is a generalist algorithm without domain knowledge. It performs well on article pages but can include navigation, sidebars, or footers in its output on some sites.

---

## 20. Module: `processing/scoring/merge.py`

**Role**: Select the highest-confidence value for each field across all extraction sources.

### `FIELD_PRIORITY` Dictionary

```python
FIELD_PRIORITY = {
    "title":        ["jsonld", "trafilatura", "og", "readability"],
    "author":       ["jsonld", "trafilatura", "og"],
    "authors":      ["jsonld", "trafilatura"],
    "date":         ["jsonld", "htmldate", "trafilatura", "og"],
    "updated_date": ["jsonld", "trafilatura", "og"],
    "text":         ["trafilatura", "readability"],
    "summary":      ["trafilatura", "jsonld", "og"],
    "url":          ["jsonld", "og", "trafilatura"],
    "language":     ["trafilatura", "og"],
    "image_url":    ["og", "jsonld", "trafilatura"],
    "publisher":    ["jsonld", "og"],
    "tags":         ["jsonld", "trafilatura"],
    "keywords":     ["jsonld", "og"],
    "article_type": ["jsonld"],
}
```

**Why trafilatura before readability for text**: trafilatura's NLP-based content scoring generally produces cleaner text with fewer navigation artifacts. Readability is a fallback.

**Why htmldate before trafilatura for date**: htmldate is specialized for date extraction and has higher accuracy than trafilatura's general-purpose date parsing.

**Why jsonld wins almost everything**: JSON-LD is authoritative structured data with minimal ambiguity.

---

### `pick_field(field, sources) → tuple[Any, str, float] | tuple[None, None, None]`

```python
def pick_field(field, sources):
    for source_name in FIELD_PRIORITY.get(field, []):
        if source_name not in sources:
            continue
        value = sources[source_name]["data"].get(field)
        if value:  # truthy check handles None, "", [], 0
            confidence = sources[source_name]["confidence"]
            return value, source_name, confidence
    return None, None, None
```

**Note**: `if value` uses truthiness — an empty list, empty string, or None all fall through to the next source. This handles cases where a source returns `author: ""` or `tags: []`.

---

### `merge_fields(sources) → tuple[dict, dict, dict]`

```python
def merge_fields(sources):
    merged = {}
    field_sources = {}
    field_confidence = {}

    for field in FIELD_PRIORITY:
        value, source_name, confidence = pick_field(field, sources)
        if value is not None:
            merged[field] = value
            field_sources[field] = source_name
            field_confidence[field] = confidence

    return merged, field_sources, field_confidence
```

**Returns**:
1. `merged`: `{"title": "Article Title", "author": "John Doe", ...}`
2. `field_sources`: `{"title": "jsonld", "author": "trafilatura", ...}`
3. `field_confidence`: `{"title": 0.97, "author": 0.92, ...}`

---

## 21. Module: `processing/scoring/quality.py`

**Role**: Compute quality scores and detect article type flags.

### `compute_quality(article: dict) → dict`

**Score formulas**:
```python
title_score = 1.0 if article.get("title") else 0.0
content_score = min(1.0, len(article.get("text", "").split()) / 600)
date_score = 1.0 if article.get("date") else 0.0
author_score = 1.0 if article.get("author") else 0.0
overall_score = 0.25 * title_score + 0.45 * content_score + 0.15 * date_score + 0.15 * author_score
```

**Why content_score is 45% of overall**: Content richness is the most important quality signal. An article with no author and no date but good body content is more useful than an attributed empty article.

**600 words for perfect content score**: This is the approximate length of a standard news article. Shorter pieces (briefs, summaries) get proportionally lower scores; longer pieces (features, analysis) cap at 1.0.

**Paywall detection** (`PAYWALL_PATTERNS`):
```python
PAYWALL_PATTERNS = [
    "subscribe to continue", "subscribe to read", "subscription required",
    "premium content", "premium article", "members only",
    "abonează-te", "abonati-va", "cont premium", "membri premium",
    "to access this article", "create a free account to read",
    "sign in to read", "log in to continue",
]
```

**Liveblog detection** (`LIVEBLOG_PATTERNS`):
```python
LIVEBLOG_PATTERNS = [
    "live", "live blog", "live updates", "liveblog",
    "transmisiune live", "ultima ora", "ultimele știri",
    "breaking news", "latest updates",
]
```

Both pattern sets are matched case-insensitively against the article text.

**Reading time formula**: `max(1, word_count // 200)` minutes. 200 words/minute is a conservative reading rate. Always at least 1 minute.

---

## 22. Module: `processing/enrichers/email_extractor.py`

**Role**: Extract email addresses from article text and HTML.

### `extract_emails(text: str, html: str) → list[str]`

**Regex pattern** (simplified RFC-5321):
```python
EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)
```

**Noise filtering** (removes these patterns):
- `@example.com`, `@test.com`, `@sample.com` (placeholder domains)
- Image extensions: `@*.png`, `@*.jpg`, `@*.gif`, `@*.svg`
- Sentry: `@sentry.io`
- JavaScript: `@*.js`

**Combined scan**: Both `text` and `html` are scanned. `set()` deduplicates across both sources.

**Returns**: Sorted list of unique email addresses.

**Use case**: Primarily useful for company profile pages or author bios that embed contact emails. Not relevant for most news articles.

---

## 23. Module: `processing/enrichers/hashtag_extractor.py`

**Role**: Extract hashtags from article text and HTML.

### `extract_hashtags(text: str, html: str) → list[str]`

**Regex pattern** (Unicode-aware):
```python
HASHTAG_PATTERN = re.compile(
    r'#([A-Za-z\u00C0-\u017E][A-Za-z0-9\u00C0-\u017E_]{1,})',
    re.UNICODE
)
```

**Unicode range** `\u00C0-\u017E`: Covers Latin Extended-A and Latin Extended-B, which includes Romanian diacritics (ă, â, î, ș, ț, etc.) and most Western European characters.

**Minimum length**: `{1,}` after the first character requires at least 2-character hashtags total.

**Noise filtering**:
- Pure numerics: `#12345` → rejected
- CSS hex colors: `#fff`, `#a1b2c3` → rejected (hex character pattern check)

**Normalization**: All hashtags lowercased for deduplication.

**Returns**: Sorted list of unique hashtag strings (without `#` prefix).

---

## 24. Module: `processing/enrichers/screenshot.py`

**Role**: Screenshot capture helpers (wraps `BrowserEngine.get_with_screenshot()`).

### `capture_screenshot(browser, url, output_dir, domain, slug, screenshot_type) → str | None`

**Path construction**:
```python
date_str = datetime.utcnow().strftime("%Y%m%d")
safe_slug = re.sub(r'[^a-zA-Z0-9\-_]', '_', slug)[:80]
ext = "jpg" if screenshot_type == "jpeg" else "png"
path = f"{output_dir}/{domain}/screenshots/{date_str}/{safe_slug}.{ext}"
```

**Screenshot path format**: `output/biziday.ro/screenshots/20260308/article_slug_here.jpg`

**Returns**: Path string if screenshot succeeded, `None` if failed.

This module is a thin wrapper — the actual screenshot logic lives in `BrowserEngine.get_with_screenshot()`.

---

## 25. Module: `llm_api/llm_client.py`

**Role**: Unified LLM interface supporting multiple providers with metrics and error handling.

### `class LLMClient`

**Provider detection** (in `__init__`):
```python
def __init__(self):
    if os.getenv("ANTHROPIC_API_KEY"):
        self._provider = "anthropic"
        self._client = anthropic.AsyncAnthropic()
        self._model = "claude-sonnet-4-5"
    elif os.getenv("OPENAI_API_KEY"):
        self._provider = "openai"
        self._client = openai.AsyncOpenAI()
        self._model = "gpt-4o-mini"
    else:
        self._provider = "openai_compat"  # Ollama/vLLM
        self._client = openai.AsyncOpenAI(
            base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
        )
        self._model = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
```

**Why `api_key="ollama"`**: The OpenAI SDK requires a non-empty API key even for local servers. `"ollama"` is a conventional placeholder used by the Ollama community.

---

### `complete(system_prompt, user_prompt, endpoint_label="default") → tuple[str, str]`

```python
async def complete(self, system_prompt, user_prompt, endpoint_label="default"):
    start = time.monotonic()
    try:
        if self._provider == "anthropic":
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                temperature=0.1,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            text = response.content[0].text
        else:  # OpenAI / Ollama
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            text = response.choices[0].message.content

        # Update metrics
        llm_requests_total.labels(endpoint=endpoint_label, model=self._model, status="success").inc()
        llm_duration_seconds.labels(endpoint=endpoint_label).observe(time.monotonic() - start)
        llm_tokens_sent_total.labels(endpoint=endpoint_label).inc(len(user_prompt.split()))

        return text, self._model

    except Exception as e:
        llm_requests_total.labels(endpoint=endpoint_label, model=self._model, status="error").inc()
        raise
```

**Temperature 0.1**: Near-deterministic responses. CSS selectors should be deterministic given the same DOM — creativity hurts here.

**Max tokens 1024**: CSS selectors for 6 fields with a confidence score fit comfortably in ~200 tokens. 1024 leaves ample margin while capping runaway generation.

---

### `parse_json_response(text: str) → dict`

**Algorithm** (handles 4 LLM output formats):
```python
def parse_json_response(text):
    # 1. Direct parse attempt
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code blocks: ```json ... ```
    text = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Find JSON object boundaries in prose
    start = text.find('{')
    end = text.rfind('}') + 1
    if start != -1 and end > start:
        candidate = text[start:end]
        # 4. Fix trailing commas
        candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
        return json.loads(candidate)

    raise ValueError(f"No JSON found in LLM response: {text[:200]}")
```

**Why robust parsing matters**: Local models like qwen2.5-coder:7b often:
- Wrap JSON in markdown code blocks
- Include explanatory prose before/after JSON
- Generate trailing commas (invalid JSON but common in JavaScript)

This function handles all of these gracefully.

---

## 26. Module: `llm_api/prompts.py`

**Role**: System and user prompt strings for selector discovery.

### `SELECTOR_DISCOVERY_SYSTEM`

Expert persona with specific CSS selector rules. Key directives:

1. **Output format**: JSON only, no prose
2. **Selector quality rules** (15+ guidelines):
   - Prefer semantic HTML: `<article>`, `<main>`, `<header>`, `<h1>`–`<h6>`, `<time>`, `<figure>`
   - Prefer stable identifiers: `id`, `data-*` attributes, BEM class names
   - Use maximum 2 class names per selector
   - Avoid structural selectors: `div > div > span` (too fragile)
3. **Tailwind prohibition** (explicit examples):
   - NEVER use: classes with `:`, `[`, `]`
   - NEVER use: `flex`, `grid`, `p-*`, `m-*`, `w-*`, `h-*`, `text-*`, `bg-*`, `border-*`, `rounded-*`, `shadow-*`
   - Rationale: "Utility classes change with every UI update; they are not stable selectors"
4. **Missing selector handling**: Return `""` if a selector cannot be determined
5. **Confidence**: Include float 0.0–1.0 based on certainty

### `SELECTOR_DISCOVERY_USER`

Template with format parameters:
```
Given this compact DOM from {domain} (listing page at {url}):

{compact_dom}

Return JSON with these 6 selectors:
- article_links_selector: CSS selector to find article <a> elements
- pagination_next_selector: CSS selector for "next page" link
- article_body_selector: CSS selector for article content container
- title_selector: CSS selector for article title
- date_selector: CSS selector for publication date
- author_selector: CSS selector for author name

Include a confidence float (0.0-1.0).
```

**Why this prompt structure works**:
- The system prompt establishes expertise and rules once
- The user prompt provides the concrete task with real data
- The compact DOM is the critical input — too much noise and the LLM generates utility classes
- The confidence score provides calibrated uncertainty

---

## 27. Cross-Cutting Flows

### 27.1 First-Time Site Flow (No Cache, No Knowledge)

```
1. _init_db() → db_ok=True
2. upsert_site("new-site.ro") → registered in sites table
3. knowledge.load("new-site.ro") → SiteProfile(is_known=False)
4. BrowserEngine starts
5. navigator.collect_all_article_urls("https://new-site.ro", "new-site.ro")
   a. Render homepage → HTML
   b. _discover_sections() → 6 section URLs found
   c. For section 1:
      - selector_client.get_or_discover("new-site.ro", ..., html)
        * Redis MISS
        * PostgreSQL MISS
        * _compact_dom() → 3,847 chars compact DOM
        * LLM call → {article_links_selector: "article.post a", confidence: 0.87, ...}
        * Store in Redis + PostgreSQL
        * Validate: 12 matches ✓
      - Collect 12 article URLs from section 1
   d. Repeat for sections 2-6 (all Redis hits after section 1 if same domain/page_type)
   → Total: 68 article URLs
6. filter_unscraped_urls(68) → all 68 new (empty scraped_urls table)
7. Truncate to max_articles=50
8. fetch_and_extract(url) × 50 (concurrency=3):
   a. recommend_fetch_method() → "playwright" (is_known=False, default safe)
   b. Try static first anyway (is_known=False condition)
      - fetch_static() → HTML 52KB, no blocks
      - record_static_success() → preferred=static
   c. extract_main_content() → article data
   d. article_store.save() → DB + NDJSON
9. mark_urls_scraped("new-site.ro", 48 URLs)
10. upsert_site_knowledge("new-site.ro", {preferred=static, total_scraped=48, ...})
```

### 27.2 Repeat Run Flow (All Cache Warm)

```
1. knowledge.load("new-site.ro") → SiteProfile(is_known=True, preferred=static, total_scraped=48)
2. navigator.collect_all_article_urls(...)
   a. Render homepage → HTML
   b. _discover_sections() → same 6 sections
   c. For section 1:
      - selector_client.get_or_discover() → Redis HIT (age: 35 min) → validate OK
      - Collect 14 article URLs (site added 2 new articles)
   d-f. Sections 2-6: all Redis HITs
   → Total: 72 article URLs
3. filter_unscraped_urls(72) → 4 new (68 already scraped from previous run)
4. fetch_and_extract(url) × 4:
   a. recommend_fetch_method() → "static" (is_known=True, preferred=static, block_rate=0.0)
   b. fetch_static() → HTML, no blocks
   c. extract_main_content() → article data
   d. article_store.save()
5. mark_urls_scraped()
6. upsert_site_knowledge() → total_scraped=52
```

**Result**: Second run fetches only 4 new articles, makes zero LLM calls, and completes in ~5 seconds vs ~2 minutes for the first run.

### 27.3 Site Redesign Recovery Flow

```
[Day 30+: site redesigned, old selectors invalid]

1. knowledge.load() → SiteProfile(is_known=True, preferred=static)
2. navigator.collect_all_article_urls(...)
3. Section 1: selector_client.get_or_discover()
   a. Redis MISS (TTL expired)
   b. PostgreSQL HIT (30 days not yet expired)
   c. Validate cached selector against new HTML: 0 matches → FAIL
   d. Delete from Redis + PostgreSQL
   e. LLM attempt 1: new selectors → validate → 0 matches (site still loading?) → delete
   f. LLM attempt 2: new selectors → validate → 8 matches ✓
   g. Store new selectors in Redis + PostgreSQL
4. Continue URL collection with new selectors
5. Remainder of run proceeds normally
```

**Transparent recovery**: The operator sees `selector_validation_failed` and `cache_miss` log events but the run succeeds. The site's selector cache is automatically updated.

---

## 28. Test Suite Documentation

### Unit Tests (`tests/unit/`)

All 121 unit tests run without live infrastructure (PostgreSQL, Redis, Ollama). They use mocking, fixtures, and standalone HTML strings.

---

### `test_article_store.py` (11 tests)

Tests `ArticleStore` behavior:
- `test_save_saves_to_ndjson`: Verifies NDJSON file append on save
- `test_save_skips_duplicate_url`: In-memory dedup prevents double-write
- `test_save_with_db_ok_calls_save_article`: DB save invoked when `db_ok=True`
- `test_save_without_db_ok_skips_db`: DB not called when `db_ok=False`
- `test_db_failure_still_writes_ndjson`: NDJSON still written despite DB error
- `test_close_flushes_and_closes`: `close()` properly finalizes file handle
- `test_concurrent_saves_no_duplicate`: Multiple concurrent `save()` calls don't duplicate
- `test_ndjson_format_is_valid_json`: Each line in NDJSON file is valid JSON
- `test_article_fields_preserved`: All article fields survive serialize/deserialize cycle
- `test_empty_article_handled`: Empty dict doesn't crash save
- `test_unicode_content_preserved`: Romanian diacritics preserved in NDJSON

---

### `test_site_knowledge.py` (19 tests)

Tests `SiteProfile` and `SiteKnowledgeRepository`:
- `test_default_profile_is_playwright`: Unknown sites default to Playwright
- `test_static_recommended_after_success`: Static recommended after static success recorded
- `test_playwright_recommended_high_block_rate`: High block rate → Playwright
- `test_spa_always_playwright`: `is_spa=True` → Playwright regardless
- `test_requires_js_always_playwright`: `requires_js=True` → Playwright
- `test_rolling_latency_average`: Rolling average formula correct (80%/20%)
- `test_cloudflare_signal_detected`: Cloudflare block signal sets `has_cloudflare`
- `test_datadome_signal_detected`: DataDome signal sets `has_datadome`
- `test_block_rate_calculation`: Block rate correctly computed from success/failure ratio
- `test_load_with_db_ok_false_returns_default`: No DB → default profile
- `test_metadata_signals_recorded`: JSON-LD and OG flags set correctly
- [8 more tests for edge cases and statistical tracking]

---

### `test_enrichers.py` (14 tests)

Tests email, hashtag, and screenshot enrichers:
- `test_extract_emails_basic`: Valid email found in text
- `test_extract_emails_filters_placeholders`: `@example.com` excluded
- `test_extract_emails_deduplicates`: Same email from text and HTML → 1 result
- `test_extract_hashtags_basic`: `#Python` → `["python"]`
- `test_extract_hashtags_unicode`: `#românia` → `["românia"]`
- `test_extract_hashtags_filters_numbers`: `#12345` excluded
- `test_extract_hashtags_filters_hex_colors`: `#ff00aa` excluded
- `test_screenshot_path_construction`: Path format matches expected pattern
- [6 more edge case tests]

---

### `test_extractor.py`

Tests `extract_main_content()` and individual extractors:
- JSON-LD parsing including @graph, nested types, malformed JSON
- Open Graph meta tag extraction
- htmldate integration
- Confidence-weighted field merging
- Quality score computation
- Paywall detection patterns
- Liveblog detection patterns

---

### `test_anti_bot.py`

Tests `detect_block_signals()` and `is_blocked()`:
- Cloudflare detection via header
- DataDome detection via HTML content
- CAPTCHA detection
- HTTP 429/403/503 status codes
- Paywall is_blocked = False (soft block)
- Clean response → no signals

---

### `test_url_utils.py`

Tests `canonicalize_url()` and `extract_domain()`:
- UTM parameter stripping
- fbclid, gclid removal
- Fragment removal
- Trailing slash normalization
- www. prefix stripping
- Protocol-less URLs

---

### Integration Tests (`tests/integration/`)

These require live infrastructure (PostgreSQL, Redis, Ollama) and network access to target sites.

**`test_biziday.py`**: Full pipeline test against biziday.ro
- `test_biziday_homepage_accessible`: Site reachable
- `test_biziday_article_extraction`: Can extract a valid article
- `test_biziday_selector_discovery`: LLM returns valid selectors
- `test_biziday_full_run`: End-to-end: 5 articles, verify DB persistence

**`test_adevarul.py`** and **`test_euronews.py`**: Similar integration coverage for those sites.

**Note**: Integration tests are not part of the CI unit test run. Run them manually:
```bash
source .venv/bin/activate
python -m pytest tests/integration/test_biziday.py -v
```
