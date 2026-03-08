# TODO

## Completed
- [x] Read and understand current enrichment code
- [x] Delete `llm_api/routers/extraction.py`
- [x] Remove EXTRACTION_SYSTEM / EXTRACTION_USER prompts from `llm_api/prompts.py`
- [x] Remove extraction router from `llm_api/main.py`
- [x] Update `processing/filters/extractor.py` — return metadata dict via trafilatura JSON output
- [x] Update `processing/pipeline.py` — remove `_llm_extract()`, use trafilatura metadata directly
- [x] Update `processing/main.py` — simplify ES mapping
- [x] Update `shared/models.py` — remove enrichment models
- [x] Update `shared/kafka.py` — remove TOPIC_FILTERED
- [x] Update `shared/metrics.py` — remove content_reduction_ratio
- [x] Update tests for deleted models/extractor changes
- [x] Update `scraper/selector_client.py` — remove comments_selector
- [x] Update `shared/db.py` — remove max_comments and comments_selector
- [x] Update scheduler and scripts — remove enrichment fields
- [x] Create integration tests: test_adevarul.py, test_biziday.py, test_euronews.py
- [x] Update `docs/Documentation.md`
- [x] Run integration tests and verify
- [x] Add optional direct LLMClient injection to `scraper/selector_client.py`
- [x] Create `app.py` — CLI entry point (`--website`, `--pages`, `--articles`, `--output`)
- [x] Wire BrowserEngine, SelectorClient, SiteNavigator, trafilatura in `app.py`
- [x] Export results to JSON + CSV in `output/`
- [x] Configure Ollama locally (qwen2.5-coder:7b) as LLM backend
- [x] Fix `shared/db.py` — call `run_schema()` on startup to auto-create tables
- [x] Fix LLM prompt — guard against Tailwind/utility CSS class selectors
- [x] Fix `_compact_dom` — strip Tailwind class names before sending to LLM
- [x] Add Ollama service to `docker/docker-compose.yml`
- [x] Add `scraped_urls` table to DB schema for URL deduplication
- [x] Add `upsert_site`, `filter_unscraped_urls`, `mark_urls_scraped` helpers to `shared/db.py`
- [x] Wire URL dedup + site registry into `app.py`
- [x] Fix Redis cleanup — add `SelectorClient.close()` and call it from `app.py`

### Scraper Improvements (from Morpheu/Zenith analysis)
- [x] 1. URL canonicalization — `shared/url_utils.py`, strip utm_*/fbclid/gclid before dedup
- [x] 2. Block detection — `scraper/detectors/anti_bot.py`, detects Cloudflare/DataDome/captcha/429
- [x] 3. Playwright resource blocking — tracking scripts (GTM, GA, Hotjar, DoubleClick) blocked
- [x] 4. Cookie/overlay dismissal — `_dismiss_overlays()` in BrowserEngine
- [x] 5. Static fetch first (curl-cffi Chrome124 TLS spoofing) with Playwright fallback
- [x] 6. Anti-bot request jitter — 150–750ms random delay in `static_fetcher.py`
- [x] 7. Multi-source extraction — `processing/extractors/` (JSON-LD + OG + htmldate + readability + trafilatura)
- [x] 8. Quality scoring — `processing/scoring/` (field merge by confidence + quality flags)
- [x] 9. Rich ArticleRecord output schema — `shared/models.py`
- [x] 10. Per-domain output directories — `output/adevarul.ro/`, `output/euronews.ro/`, etc.
- [x] 11. Site strategy table in DB — `site_strategies` table + helpers in `shared/db.py`

## In Progress
- (nothing in progress)

## Completed (Platform Redesign)
- [x] Immediate article persistence — `ArticleStore` saves to `scraped_articles` table right after extraction
- [x] Extended .env config: SCRAPE_LIMIT, HEADLESS, BROWSER_TIMEOUT, NAVIGATION_STRATEGY, USE_STEALTH, IMPERSONATE_BROWSER, EXTRACT_IMAGES, EXTRACT_COMMENTS, COMMENT_WAIT_MS, MIN_TITLE_LENGTH, CAPTURE_SCREENSHOT, SCREENSHOT_TYPE, EXTRACT_EMAILS, EXTRACT_HASHTAGS, RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS
- [x] `site_knowledge` DB table — comprehensive per-domain learning (WAF signals, strategy, content patterns, stats)
- [x] `scraped_articles` DB table — persistent article storage with full raw JSON
- [x] `shared/article_store.py` — ArticleStore: idempotent save, in-memory dedup, NDJSON fallback
- [x] `scraper/knowledge/site_knowledge.py` — SiteKnowledgeRepository + SiteProfile dataclass
- [x] Strategy selection: SiteProfile.recommend_fetch_method() → static/playwright based on DB knowledge
- [x] RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS=3 config added to scraper/config.py
- [x] Enrichment: full-page screenshot capture (BrowserEngine.get_with_screenshot + processing/enrichers/screenshot.py)
- [x] Enrichment: email extraction (processing/enrichers/email_extractor.py)
- [x] Enrichment: hashtag extraction (processing/enrichers/hashtag_extractor.py)
- [x] Update `scraper/config.py` with all new env vars
- [x] Update `app.py` to use immediate persistence, knowledge system, new config
- [x] Tests for ArticleStore (11 unit tests)
- [x] Tests for SiteKnowledge (19 unit tests)
- [x] Tests for enrichments: screenshot, email, hashtag (14 unit tests)
- [ ] Tune selector discovery prompt for edge-case sites
- [ ] Add --force-rediscover CLI flag to invalidate selector cache
- [ ] Add --skip-dedup CLI flag for re-scraping known URLs
- [ ] Graceful shutdown on SIGINT
- [ ] Dockerfile.app for standalone scraper container
- [ ] SPA hydration detection (domcontentloaded vs networkidle auto-detection)
- [ ] API XHR interception for JS-heavy sites
