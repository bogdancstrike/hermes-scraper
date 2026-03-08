# LLM-Augmented Web Scraper — Complete Technical Documentation

> **Version:** 3.0 | **Updated:** 2026-03-08 | **Status:** Production-ready (standalone mode)

---

## Table of Contents

1. [Title and Overview](#1-title-and-overview)
2. [Executive Summary](#2-executive-summary)
3. [Business and Functional Goals](#3-business-and-functional-goals)
4. [Architecture Overview](#4-architecture-overview)
5. [Project Structure](#5-project-structure)
6. [Core Concepts](#6-core-concepts)
7. [Configuration Reference](#7-configuration-reference)
8. [Runtime Flows](#8-runtime-flows)
9. [Extraction Strategies](#9-extraction-strategies)
10. [Persistence Layer](#10-persistence-layer)
11. [Database Schema Documentation](#11-database-schema-documentation)
12. [Selector Learning and Reuse](#12-selector-learning-and-reuse)
13. [Legacy Inspirations (Morpheu / Zenith)](#13-legacy-inspirations-morpheu--zenith)
14. [Error Handling and Resilience](#14-error-handling-and-resilience)
15. [Logging, Observability, and Debugging](#15-logging-observability-and-debugging)
16. [Performance and Optimization](#16-performance-and-optimization)
17. [Security, Safety, and Compliance](#17-security-safety-and-compliance)
18. [Extensibility Guide](#18-extensibility-guide)
19. [Deployment and Operation](#19-deployment-and-operation)
20. [Known Limitations](#20-known-limitations)
21. [Future Improvements](#21-future-improvements)
22. [Glossary](#22-glossary)
23. [Appendix](#23-appendix)

---

## 1. Title and Overview

### Project Name
**LLM-Augmented Generalist Web Scraper** (`llm-scraper`)

### Purpose
This system is a self-improving, configuration-driven web scraping platform that extracts structured article content from any news or content website without requiring manual, site-specific CSS selectors or XPath expressions. It uses a Large Language Model (LLM) to discover CSS selectors on first contact with a site, caches those selectors persistently across runs, and reuses them automatically — calling the LLM again only when selectors fail live validation or the cache expires.

### Main Problem Solved
Traditional web scrapers require a developer to manually write site-specific CSS selectors or XPath expressions for every website. This approach is fundamentally brittle: selectors break whenever a site updates its frontend framework or design, and maintaining hundreds of site-specific scrapers is expensive and fragile.

This project solves that problem through five mechanisms:

1. **Automatic selector discovery** — An LLM analyzes the real rendered DOM and returns precise CSS selectors for article links, pagination, title, author, date, and body content.
2. **Persistent selector caching** — Discovered selectors are stored in Redis (L1, 1-hour TTL) and PostgreSQL (L2, 30-day TTL) so the LLM is not invoked on subsequent runs.
3. **Live selector validation** — Before trusting any cached selector, the system tests it against the actual HTML of the current page. Zero matches triggers re-discovery.
4. **Per-domain strategy learning** — The system records whether static HTTP or full Playwright rendering worked best per domain, and reuses that knowledge on subsequent runs.
5. **Immediate article persistence** — Articles are written to PostgreSQL after each extraction, not batched, enabling partial-run recovery.

### Key Architectural Goals

| Goal | Implementation |
|------|---------------|
| Zero site-specific code | LLM-discovered selectors for any site |
| Minimal LLM calls | LLM used only on cache miss or validation failure |
| Progressive improvement | Every run improves future run speed and reliability |
| Graceful degradation | DB unavailable → file fallback; LLM unavailable → cached selectors only |
| Canonical output | Same `ArticleRecord` schema regardless of site or fetch strategy |
| Idempotent persistence | `ON CONFLICT DO NOTHING` throughout; duplicate URLs skipped |

### High-Level Capabilities

- Discovers all sections and categories of a news site from its homepage navigation
- Renders pages with a full headless Chromium browser (full JavaScript execution, overlay dismissal, infinite scroll simulation)
- Tries lightweight static HTTP fetch first (milliseconds); falls back to browser only when needed
- Extracts article metadata from five sources: JSON-LD, trafilatura, Open Graph tags, htmldate, and readability
- Merges extracted fields by confidence score, tracking the provenance of every field value
- Persists articles to PostgreSQL immediately after extraction with rich quality metadata
- Learns per-domain knowledge: WAF presence, best fetch strategy, metadata reliability, block signals
- Optionally captures full-page screenshots, extracts emails, and extracts hashtags from article content
- Exports results to JSON and CSV files per domain per run
- Deduplicates URLs across runs using a persistent `scraped_urls` table

### Why This Is Different from a Simple Scraper

| Simple Scraper | LLM-Augmented Scraper |
|----------------|----------------------|
| Hardcoded CSS selectors | LLM discovers selectors dynamically |
| Breaks on site redesigns | Detects selector drift, re-learns automatically |
| Static configuration | Learns per-domain knowledge across runs |
| Single extraction method | Multi-source extraction with confidence merging |
| Batch persistence | Immediate per-article persistence |
| No WAF awareness | Detects and records Cloudflare, DataDome, captchas |
| No strategy memory | Remembers best fetch method per domain |

---

## 2. Executive Summary

### What the Platform Does

The LLM-augmented scraper is a Python-based standalone CLI (`app.py`) that scrapes any news or article website and produces a normalized, quality-scored `ArticleRecord` for every article found. It operates in two distinct phases:

**Phase 1 — URL Discovery**: Starting from the site's homepage, the system discovers all section and category URLs from navigation menus, visits each section, simulates infinite scrolling to reveal dynamically loaded content, and collects all article URLs. LLM-discovered CSS selectors identify article links, and selector validation ensures the selectors are still valid against the live page.

**Phase 2 — Article Extraction**: For each discovered article URL, the system tries a lightweight static HTTP fetch first (using `curl-cffi` with Chrome124 TLS fingerprint spoofing, completing in ~150–400ms). If static fetch is blocked or returns empty content, it falls back to full Playwright browser rendering. The resulting HTML is passed through a five-source extraction pipeline that merges fields by confidence score. Each article is persisted to PostgreSQL immediately after extraction.

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| LLM as last resort | Called only on cache miss or selector validation failure |
| Persistent knowledge | Site strategies, selectors, and article counts stored in PostgreSQL |
| Graceful degradation | Every component has a fallback path |
| Canonical output | Same `ArticleRecord` regardless of site, strategy, or extraction source |
| Immediate persistence | Articles saved to DB right after extraction, not at end of run |
| Strategy reuse | Best fetch method stored per domain and reused on subsequent runs |
| Metrics-first | Prometheus instrumentation at every layer |

### Why Persistent Site Knowledge Matters

Without persistent site knowledge, every run would perform the same expensive probing steps: which fetch strategy works, whether the site uses JSON-LD structured data, what WAF signals appear, how the navigation is structured. By persisting this knowledge in the `site_knowledge` table, subsequent runs:
- Skip static fetch probing (use the known-good strategy immediately)
- Skip LLM selector calls (use cached selectors from Redis/PostgreSQL)
- Know whether to expect WAF interference
- Know whether JSON-LD metadata is available (skip weaker extraction paths)

### Why Selector Reuse Matters

An LLM call for CSS selector discovery (even to a local Ollama model) takes 3–15 seconds and consumes GPU resources. On a site with 10 sections, that would be 10–50 seconds just for selector discovery per run. The three-tier cache (Redis → PostgreSQL → LLM) ensures that selector discovery is typically a sub-millisecond Redis hit after the first run.

### Why Immediate Persistence Matters

If the scraper crashes midway through a 100-article run, articles already extracted and saved to DB are not lost. On the next run, the `scraped_urls` deduplication table ensures those URLs are skipped, so the run continues from where it left off.

---

## 3. Business and Functional Goals

### Functional Requirements

| Requirement | Implementation |
|-------------|---------------|
| Scrape any news site without manual configuration | LLM-based selector discovery |
| Discover all content sections from homepage | `SiteNavigator.collect_all_article_urls()` |
| Handle JavaScript-rendered pages | Playwright browser engine |
| Minimize browser usage cost | Static fetch first; Playwright fallback |
| Extract rich article metadata | 5-source extraction pipeline |
| Deduplicate articles across runs | `scraped_urls` table + canonical URL normalization |
| Persist articles permanently | `scraped_articles` table + NDJSON fallback |
| Support optional email and hashtag extraction | Enrichment pipeline |
| Support optional screenshot capture | `BrowserEngine.get_with_screenshot()` |
| Export per-run results | JSON + CSV export in `output/{domain}/` |
| Track per-domain learning | `site_knowledge` table |

### Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Static article fetch latency | 150–750ms including anti-bot jitter |
| Playwright article fetch latency | 2–10s depending on site complexity |
| Concurrent article fetching | Configurable (default: 3 parallel via Semaphore) |
| LLM calls per run (after warmup) | Zero (selectors cached in Redis/PG) |
| Article deduplication guarantee | Cross-run via PostgreSQL; within-run via in-memory set |
| Persistence reliability | NDJSON fallback if PostgreSQL unavailable |

### Reliability Goals

- **Per-article failure tolerance**: One failed article does not stop the run; the error is logged and the next URL is processed.
- **DB unavailability tolerance**: If PostgreSQL is unavailable at startup, the scraper continues with file-only output.
- **LLM unavailability tolerance**: If the LLM is not configured or unreachable, the scraper uses cached selectors only. If no cache exists, URL collection degrades but extraction still proceeds.
- **Anti-bot tolerance**: Block signals trigger Playwright fallback and are recorded in `site_knowledge` for future runs.

### Maintainability Goals

- All configuration via `.env` — no code changes for operational tuning
- All site-specific behavior learned at runtime — no site-specific code files
- Structured logging (structlog) makes log analysis programmatic
- Pydantic models enforce data contract at every layer boundary
- 121 unit tests covering all major modules without requiring live infrastructure

---

## 4. Architecture Overview

### High-Level Architecture

The system is organized into four functional layers:

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (app.py)                            │
│              Orchestration, argument parsing, export             │
├──────────────────┬───────────────────┬───────────────────────────┤
│   Scraper Layer  │  Processing Layer │    LLM Integration        │
│                  │                   │                           │
│  BrowserEngine   │  extract_main_    │   LLMClient               │
│  StaticFetcher   │  content()        │   (Claude/OpenAI/Ollama)  │
│  SiteNavigator   │                   │                           │
│  SelectorClient  │  Merge by conf.   │   SELECTOR_DISCOVERY      │
│  SiteKnowledge   │  Quality scoring  │   prompts                 │
│  AntiBotDetector │  Enrichers        │                           │
├──────────────────┴───────────────────┴───────────────────────────┤
│                        Shared Layer                              │
│          DB (asyncpg), ArticleStore, Models, URL utils           │
├──────────────────────────────────────────────────────────────────┤
│                    Infrastructure                                │
│    PostgreSQL · Redis · Ollama/LLM API · Playwright/Chromium     │
└──────────────────────────────────────────────────────────────────┘
```

### Core Subsystems

**1. Scraper Subsystem** (`scraper/`)
Responsible for URL collection. Manages browser rendering, static HTTP fetching, WAF detection, navigation/pagination, and CSS selector discovery/caching. The scraper subsystem knows *how to find* URLs; it does not perform content extraction.

**2. Processing Subsystem** (`processing/`)
Responsible for turning raw HTML into structured `ArticleRecord` data. Runs five independent extractors (JSON-LD, trafilatura, OG meta, htmldate, readability), merges outputs by confidence score, applies quality scoring, and optionally runs enrichments (email, hashtag, screenshot).

**3. LLM Integration** (`llm_api/`)
Provides a unified LLM client that supports Anthropic Claude, OpenAI-compatible APIs, and local Ollama models. Used exclusively for CSS selector discovery — not for content extraction. Manages prompt construction, response parsing, and per-call metrics.

**4. Shared Layer** (`shared/`)
Cross-cutting infrastructure: asyncpg database pool, article persistence, Pydantic models, URL canonicalization, structlog logging, and Prometheus metrics.

### Main Runtime Responsibilities

| Component | Primary Responsibility |
|-----------|----------------------|
| `app.py` | Orchestrates the full pipeline; CLI entry point |
| `BrowserEngine` | Headless Chromium control via Playwright |
| `StaticFetcher` | Fast HTTP fetch with TLS fingerprint spoofing |
| `SiteNavigator` | Discovers sections and collects article URLs |
| `SelectorClient` | Manages the three-tier selector cache |
| `SiteKnowledgeRepository` | Loads and updates per-domain learning |
| `AntiBotDetector` | Detects Cloudflare, DataDome, captchas, 429s |
| `extract_main_content()` | Multi-source HTML → structured data |
| `ArticleStore` | Idempotent article persistence |
| `LLMClient` | Unified LLM access for selector discovery |

---

## 5. Project Structure

```
llm-scraper/
├── app.py                          # CLI entry point, full pipeline
├── pyproject.toml                  # Build config, linting, type checking settings
├── pytest.ini                      # Test runner configuration
├── .env                            # Local environment configuration (not committed)
│
├── scraper/                        # URL discovery subsystem
│   ├── config.py                   # ScraperConfig (pydantic-settings), all env vars
│   ├── engines/
│   │   └── browser_engine.py       # Playwright browser: stealth, overlays, scroll, screenshots
│   ├── fetchers/
│   │   └── static_fetcher.py       # curl-cffi TLS spoofing + requests fallback
│   ├── detectors/
│   │   └── anti_bot.py             # Cloudflare/DataDome/captcha/429 detection
│   ├── navigation/
│   │   └── paginator.py            # SiteNavigator + Paginator (section discovery, pagination)
│   ├── knowledge/
│   │   └── site_knowledge.py       # SiteKnowledgeRepository + SiteProfile
│   └── selector_client.py          # L1=Redis, L2=PG, L3=LLM selector cache
│
├── processing/                     # Content extraction subsystem
│   ├── filters/
│   │   └── extractor.py            # Main extraction entry: 5-source merge pipeline
│   ├── extractors/
│   │   ├── jsonld.py               # JSON-LD schema.org extraction
│   │   ├── og_meta.py              # Open Graph + HTML meta tags
│   │   ├── htmldate_extractor.py   # htmldate library wrapper for date mining
│   │   └── readability_extractor.py # Mozilla Readability fallback
│   ├── scoring/
│   │   ├── merge.py                # Confidence-based field merging
│   │   └── quality.py              # Quality scoring, paywall/liveblog detection
│   ├── enrichers/
│   │   ├── email_extractor.py      # Email extraction from text + HTML
│   │   ├── hashtag_extractor.py    # Hashtag extraction (Unicode-aware)
│   │   └── screenshot.py           # Screenshot capture helpers
│   ├── pipeline.py                 # ContentPipeline (Kafka-based distributed mode)
│   └── main.py                     # Distributed processing service entry point
│
├── llm_api/                        # LLM integration
│   ├── llm_client.py               # Unified client: Claude / OpenAI / Ollama
│   ├── prompts.py                  # SELECTOR_DISCOVERY_SYSTEM/USER prompt strings
│   └── main.py                     # FastAPI HTTP service (distributed mode)
│
├── shared/                         # Cross-cutting utilities
│   ├── db.py                       # asyncpg pool, schema creation, all DB helpers
│   ├── article_store.py            # ArticleStore: idempotent save, NDJSON fallback
│   ├── models.py                   # Pydantic models: SiteSelectors, ArticleRecord, etc.
│   ├── url_utils.py                # canonicalize_url, extract_domain
│   ├── logging.py                  # structlog configuration
│   └── metrics.py                  # Prometheus metrics definitions
│
├── scheduler/                      # Distributed job scheduler (unused in standalone mode)
├── scripts/                        # Operational utility scripts
│
├── tests/
│   ├── unit/                       # 121 unit tests, no live infra required
│   │   ├── test_article_store.py   # 11 tests: idempotency, dedup, NDJSON fallback
│   │   ├── test_site_knowledge.py  # 19 tests: strategy recommendation, stat learning
│   │   ├── test_enrichers.py       # 14 tests: email, hashtag, screenshot
│   │   ├── test_extractor.py       # Extraction pipeline tests
│   │   ├── test_quality_scoring.py # Quality score and flag tests
│   │   ├── test_anti_bot.py        # Block signal detection tests
│   │   ├── test_url_utils.py       # URL canonicalization tests
│   │   ├── test_paginator.py       # Pagination and section discovery tests
│   │   ├── test_models.py          # Pydantic model validation tests
│   │   └── test_llm_client.py      # LLM client and JSON parsing tests
│   └── integration/                # Live tests requiring infra + network
│       ├── test_adevarul.py
│       ├── test_biziday.py
│       └── test_euronews.py
│
├── docker/
│   ├── docker-compose.yml          # Full local dev stack (PG, Redis, Kafka, Ollama, UIs)
│   └── Dockerfile.scraper          # Container image for scraper service
│
├── output/                         # Per-run output: JSON, CSV, NDJSON, screenshots
│   └── {domain}/
│       ├── {timestamp}.json
│       ├── {timestamp}.csv
│       ├── {timestamp}.ndjson
│       └── screenshots/{YYYYMMDD}/{slug}.jpg
│
└── docs/
    ├── Documentation.md            # This document
    ├── C4_Architecture.md          # C4 model diagrams
    └── Flows.md                    # Detailed flow documentation
```

### Module Dependency Graph

```
app.py
  ├── scraper/config.py
  ├── scraper/engines/browser_engine.py
  │     └── shared/logging.py
  ├── scraper/fetchers/static_fetcher.py
  │     └── scraper/detectors/anti_bot.py
  ├── scraper/navigation/paginator.py
  │     ├── scraper/selector_client.py
  │     │     ├── shared/db.py
  │     │     ├── shared/models.py
  │     │     ├── shared/metrics.py
  │     │     └── llm_api/llm_client.py
  │     │           └── llm_api/prompts.py
  │     └── shared/models.py
  ├── scraper/knowledge/site_knowledge.py
  │     └── shared/db.py
  ├── processing/filters/extractor.py
  │     ├── processing/extractors/jsonld.py
  │     ├── processing/extractors/og_meta.py
  │     ├── processing/extractors/htmldate_extractor.py
  │     ├── processing/extractors/readability_extractor.py
  │     ├── processing/scoring/merge.py
  │     └── processing/scoring/quality.py
  ├── shared/article_store.py
  │     └── shared/db.py
  ├── shared/db.py
  │     └── shared/logging.py
  ├── shared/url_utils.py
  └── shared/logging.py
```

---

## 6. Core Concepts

### 6.1 Site Knowledge

Site knowledge is the accumulated understanding of a specific domain's scraping characteristics. It answers: "How should we scrape this site efficiently?" It is stored in the `site_knowledge` PostgreSQL table and modeled as `SiteProfile` in Python.

Site knowledge encompasses:
- **Preferred fetch method**: `static`, `playwright`, or `api_intercept`
- **WAF signals**: Whether Cloudflare, DataDome, reCAPTCHA, or other anti-bot systems have been detected
- **Content structure flags**: Whether the site has paywalled content, comments sections, or infinite scroll
- **Metadata format**: Whether the site uses JSON-LD structured data or Open Graph meta tags
- **Performance statistics**: Average latency per fetch method, average word count per article, success rate, block rate

Site knowledge is **learned**, not configured. On the first scrape of a domain, the system has no knowledge and probes both static and Playwright fetch methods. On subsequent runs, it uses the recorded knowledge to skip probing.

### 6.2 Selector Mining (LLM-Based Discovery)

When CSS selectors for a domain are not in cache, the system calls the LLM with a compact representation of the page DOM. The LLM acts as an expert web scraping engineer and returns a JSON object with six CSS selectors:

| Selector Key | Purpose |
|-------------|---------|
| `article_links_selector` | Selects article `<a>` elements on listing/section pages |
| `pagination_next_selector` | Selects the "next page" link on listing pages |
| `article_body_selector` | Selects the main content container on article pages |
| `title_selector` | Selects the article title element |
| `date_selector` | Selects the publication date element |
| `author_selector` | Selects the author name element |

The LLM also returns a `confidence` float (0.0–1.0) indicating how certain it is about the selectors.

To make the LLM's task tractable, the DOM is compacted before being sent:
- Scripts, styles, SVGs, and iframes are stripped
- Tailwind utility class names are removed (flex, grid, p-*, m-*, text-*, etc.)
- Class attributes with only utility classes are removed entirely
- Output is capped at 4,000 characters

This compaction is critical for local LLMs (qwen2.5-coder:7b has limited context window and often generates utility class names as selectors when the full DOM is provided).

### 6.3 Verified vs. Mined Selectors

**Mined selectors** are those returned directly by the LLM without live validation. They are stored in the cache but not considered "proven" until validated.

**Verified selectors** are mined selectors that have been tested against the actual rendered HTML of the page being scraped. A selector is verified if it matches at least one element (`MIN_ARTICLE_LINKS = 1`) on a real listing page. Only verified selectors are used for URL collection.

If a cached selector fails validation, both Redis (L1) and PostgreSQL (L2) caches are invalidated immediately, and fresh LLM discovery is triggered. This prevents stale selectors from silently producing empty results.

### 6.4 Strategy Selection

Before fetching any article, the system determines the best fetch strategy for the domain. The `SiteProfile.recommend_fetch_method()` method implements this logic:

```
IF site is known as SPA or requires JS:
    → Use Playwright
ELSE IF static worked before AND block rate < 30%:
    → Try static first
ELSE:
    → Default to Playwright (safe choice)
```

This strategy is stored in `site_knowledge.preferred_fetch_method` and updated after each successful or failed fetch. The system learns: if 10 consecutive static fetches succeed, static is marked as the preferred method. If static fetches start returning blocked responses, Playwright preference is recorded.

### 6.5 Fallback Strategies

The system has multiple fallback layers:

| Primary | Fallback | Trigger |
|---------|---------|---------|
| Static fetch (curl-cffi) | Playwright | Block detected or HTML < 500 chars |
| Playwright | Skip article | Playwright throws exception |
| Redis selector (L1) | PostgreSQL selector (L2) | Redis miss or validation failure |
| PostgreSQL selector (L2) | LLM discovery (L3) | PG miss or validation failure |
| LLM discovery | Empty selectors | LLM unavailable or returns invalid JSON |
| PostgreSQL persistence | NDJSON file | DB connection unavailable |
| Full extraction | Partial extraction | Individual extractor fails |

### 6.6 Browser Rendering vs. Static Requests

**Static requests** use `curl-cffi` with `impersonate="chrome124"`, which spoofs the TLS fingerprint of Chrome 124. This bypasses many basic bot detection systems that check TLS handshake characteristics. The request includes realistic Sec-Fetch headers, Accept-Language for the target locale, and a random delay (150–750ms) to simulate human behavior.

**Browser rendering** uses Playwright with a real Chromium binary. This executes JavaScript, handles redirects, renders dynamic content, and can interact with the page (dismiss overlays, click "Load More", scroll). It is ~10–50x slower than static fetch but handles any site.

The key insight is that many sites that appear to require JavaScript actually serve sufficient content for extraction via static HTTP (the server renders HTML server-side even if the frontend is React/Vue). The system tests this cheaply on the first request and remembers the result.

### 6.7 Multi-Source Extraction and Confidence Merging

Raw HTML passes through five independent extractors. Each returns a dict of field → value pairs. The merging system tracks confidence per source:

| Source | Confidence Range | Strengths |
|--------|-----------------|-----------|
| JSON-LD | 0.95–0.98 | Structured, authoritative, machine-readable |
| trafilatura | 0.86–0.95 | Best-in-class for news body content |
| Open Graph | 0.70–0.90 | Good title and image; weak date |
| htmldate | 0.90 | Date mining from URL, meta, visible text |
| readability | 0.65 | Fallback for body content only |

For each field, the value from the highest-confidence source that has a non-empty value wins. The winning source name and confidence score are stored in `field_sources` and `field_confidence` dictionaries within the `ArticleRecord`.

### 6.8 Scraped URL Deduplication

The `scraped_urls` table maintains a persistent record of every URL that has been successfully scraped. Before processing article URLs in a run, `filter_unscraped_urls()` queries this table and removes any already-scraped URLs from the work queue. After a successful scrape, `mark_urls_scraped()` batch-inserts the processed URLs into this table.

Additionally, `canonicalize_url()` normalizes URLs before deduplication:
- Removes 30+ tracking parameters (UTM, fbclid, gclid, msclkid, HubSpot, Mailchimp, GA)
- Removes URL fragments (`#section`)
- Normalizes trailing slashes

This ensures that `https://site.com/article?utm_source=twitter` and `https://site.com/article` are treated as the same article.

### 6.9 Article Normalization

All articles, regardless of source site or extraction method, are stored as the same `ArticleRecord` structure. This provides a single, predictable data contract for downstream consumers. The schema includes:
- Core: `url`, `canonical_url`, `domain`, `title`, `content`, `author`, `published_date`, `language`
- Quality: `overall_score`, `title_score`, `content_score`, `date_score`, `author_score`
- Provenance: `field_sources`, `field_confidence` (which extractor won each field)
- Flags: `likely_paywalled`, `likely_liveblog`
- Operational: `fetch_method`, `fetch_latency_ms`, `scraped_at`, `word_count`, `reading_time_minutes`
- Optional: `tags`, `keywords`, `top_image`, `summary`, `publisher`, `emails`, `hashtags`, `screenshot_path`

### 6.10 Anti-Bot / Stealth Behavior

The system employs multiple stealth techniques:

**TLS fingerprint spoofing**: `curl-cffi` with `impersonate="chrome124"` makes the TLS handshake indistinguishable from a real Chrome browser. Tools like JA3 fingerprinting or ALPN inspection cannot distinguish this from a legitimate browser.

**Request jitter**: A random 150–750ms delay is applied before each static fetch, mimicking human reading and navigation pauses.

**Realistic headers**: Requests include `Accept`, `Accept-Language`, `Accept-Encoding`, `Upgrade-Insecure-Requests`, and `Sec-Fetch-*` headers matching the impersonated browser.

**Resource blocking**: Playwright blocks images, fonts, media, and known tracking domains (Google Tag Manager, Google Analytics, Hotjar, DoubleClick) to reduce bandwidth and avoid beacon-based bot detection.

**Overlay dismissal**: Cookie consent banners and GDPR overlays are dismissed automatically. The system tries multiple methods: CSS injection to hide the overlay, JavaScript click on consent buttons (matching text like "Accept", "Agree", "Allow", "Acceptă" in Romanian), and `document.body.style.overflow = 'auto'` to restore scrollability.

**Stealth mode**: When `USE_STEALTH=True`, the Playwright browser uses `playwright-stealth` to mask headless browser fingerprints (navigator.webdriver, Chrome runtime, permission APIs, etc.).

### 6.11 Quality and Validation Signals

Each extracted article receives quality scores:

| Score | Formula | Meaning |
|-------|---------|---------|
| `title_score` | 1.0 if title present, else 0.0 | Whether a title was extracted |
| `content_score` | min(1.0, word_count / 600) | Content richness (600 words = perfect score) |
| `date_score` | 1.0 if date present, else 0.0 | Whether a publish date was found |
| `author_score` | 1.0 if author present, else 0.0 | Whether an author was attributed |
| `overall_score` | 0.25T + 0.45C + 0.15D + 0.15A | Weighted composite quality score |

**Paywall detection** checks for 10+ phrases across multiple languages: "subscribe to continue", "premium content", "abonează-te", "membri Premium", etc. Paywalled articles are not excluded — they are marked with `likely_paywalled=True` for downstream filtering.

**Liveblog detection** checks for "live", "transmisiune live", "último hora". Liveblogs are marked with `likely_liveblog=True`.

**Minimum title length gate**: Articles with a title shorter than `MIN_TITLE_LENGTH` characters (default 20) are silently discarded. This filters out navigation snippets, tag pages, and other non-article content that passed URL collection.

---

## 7. Configuration Reference

All configuration is loaded via `scraper/config.py` using `pydantic-settings` from environment variables (`.env` file or shell environment). Configuration is available as a singleton `config` object imported as `from scraper.config import config`.

### Node Identity

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_ENV` | `development` | Environment name; used in logs |
| `NODE_ID` | `scraper-{hostname}` | Unique node identifier for distributed mode |

### Runtime Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPE_LIMIT` | `100` | Maximum articles to extract per run |
| `SCRAPER_MAX_PAGES` | `100` | Maximum listing pages to visit per section |
| `SCRAPER_MAX_RUNTIME` | `600` | Maximum run time in seconds (not enforced via timeout, informational) |
| `SCRAPER_RETRY_LIMIT` | `3` | General retry limit |
| `RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS` | `3` | Max LLM re-discovery attempts when selectors fail validation |

### Navigation and Concurrency

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPER_DELAY_MIN` | `1.5` | Minimum delay between page fetches (seconds) |
| `SCRAPER_DELAY_MAX` | `3.5` | Maximum delay between page fetches (seconds) |
| `SCRAPER_CONCURRENCY` | `3` | Number of parallel article fetches (asyncio.Semaphore) |
| `NAVIGATION_STRATEGY` | `domcontentloaded` | Playwright wait strategy: `domcontentloaded` or `networkidle` |
| `SCRAPER_MAX_SECTIONS` | `50` | Maximum number of sections/categories to discover per site |

### Infinite Scroll

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPER_SCROLL_MAX` | `20` | Maximum scroll iterations per page |
| `SCRAPER_SCROLL_WAIT_MS` | `1500` | Milliseconds to wait after each scroll for content to load |

### Browser Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `HEADLESS` | `True` | Run Chromium in headless mode. Set `False` to see the browser (debugging) |
| `BROWSER_TIMEOUT` | `45000` | Playwright navigation timeout in milliseconds |
| `USE_STEALTH` | `True` | Apply playwright-stealth patches to hide headless fingerprints |
| `IMPERSONATE_BROWSER` | `chrome120` | curl-cffi impersonation profile for static fetch |

### Anti-Bot

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPER_USE_PROXIES` | `False` | Enable proxy rotation (requires `SCRAPER_PROXY_LIST_URL`) |
| `SCRAPER_PROXY_LIST_URL` | `""` | URL to fetch a proxy list from |
| `ROBOTS_TXT_RESPECT` | `True` | Whether to check robots.txt (informational; not enforced in current code) |

### Content Quality Filter

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_TITLE_LENGTH` | `20` | Minimum character count for a valid article title; shorter → discard |

### Enrichment Toggles

| Variable | Default | Description | Side Effects |
|----------|---------|-------------|-------------|
| `EXTRACT_EMAILS` | `False` | Extract email addresses from article text and HTML | Adds `emails` field to ArticleRecord |
| `EXTRACT_HASHTAGS` | `False` | Extract hashtags from article text and HTML | Adds `hashtags` field to ArticleRecord |
| `CAPTURE_SCREENSHOT` | `False` | Capture full-page screenshot of each article | Forces Playwright for all articles; adds `screenshot_path` field; stores files in `output/{domain}/screenshots/` |
| `SCREENSHOT_TYPE` | `jpeg` | Screenshot format: `jpeg` (smaller, lossy) or `png` (larger, lossless) | |
| `EXTRACT_IMAGES` | `False` | Placeholder for image extraction (not fully implemented) | |
| `EXTRACT_COMMENTS` | `False` | Placeholder for comments extraction (not fully implemented) | |
| `COMMENT_WAIT_MS` | `5000` | Milliseconds to wait for comments to load (when enabled) | |

> **Warning**: Enabling `CAPTURE_SCREENSHOT` forces all article fetches through Playwright, disabling the static fetch optimization entirely. This significantly increases scraping time and resource usage.

### Selector Discovery

| Variable | Default | Description |
|----------|---------|-------------|
| `RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS` | `3` | How many times to retry LLM selector discovery when selectors fail validation |
| `LLM_SELECTOR_CACHE_TTL` | `30` | Days before a PostgreSQL-cached selector is considered expired |
| `REDIS_SELECTOR_TTL` | `3600` | Seconds for Redis L1 selector cache TTL (1 hour) |

### LLM Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible LLM endpoint. Use for Ollama or vLLM |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Model name to request from the LLM endpoint |
| `ANTHROPIC_API_KEY` | `""` | If set, uses Anthropic Claude API (highest priority) |
| `OPENAI_API_KEY` | `""` | If set and no Anthropic key, uses OpenAI API |

LLM priority order: **Anthropic > OpenAI > Ollama/vLLM (via LLM_BASE_URL)**

### Infrastructure Endpoints

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DSN` | `postgresql://scraper:scraper@localhost:5432/scraperdb` | asyncpg-compatible PostgreSQL DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `KAFKA_BROKERS` | `localhost:9092` | Kafka bootstrap servers (distributed mode only) |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO/S3 endpoint (distributed mode only) |

### Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `json` | Log format: `json` (structured) or `console` (human-readable) |
| `METRICS_PORT` | `9090` | Port for Prometheus `/metrics` endpoint |

---

## 8. Runtime Flows

### 8.1 Startup Flow

**Trigger**: `python3 app.py --website domain.ro`

1. Python loads `app.py`; `.env` file is loaded via `dotenv` before any module-level code runs
2. `ScraperConfig` is instantiated; all env vars are validated via pydantic-settings
3. `_parse_args()` parses CLI arguments: `--website`, `--pages`, `--articles`, `--output`
4. Configuration summary is printed to stdout
5. `asyncio.run(_main())` starts the async event loop
6. `scrape_website()` is called with the parsed arguments

### 8.2 Database Initialization Flow

**Trigger**: First step inside `scrape_website()`

1. `_init_db()` calls `init_pool()` to establish asyncpg connection pool
2. `run_schema()` is called, which executes `CREATE TABLE IF NOT EXISTS` for all 9 tables
   - This is safe to call on every startup; existing tables are left unchanged
   - New tables are created only if missing
3. If PostgreSQL is unavailable, `_init_db()` logs a warning and returns `False`
4. `db_ok` flag propagates through the rest of the run; all DB operations check this flag

### 8.3 Site Initialization Flow

**Trigger**: After DB initialization, before URL discovery

1. If `db_ok`, `upsert_site(domain, start_url)` registers the domain in the `sites` table
2. `SiteKnowledgeRepository(db_ok=db_ok)` is instantiated
3. `knowledge.load(domain)` queries `site_knowledge` table for this domain
4. If no record exists, a default `SiteProfile` is returned (`is_known=False`)
5. The loaded profile is logged: known status, total scraped count, preferred method
6. `LLMClient` is lazily instantiated (checks for API keys; warns if none configured)
7. `SelectorClient(llm_client=llm_client)` is instantiated
8. `ArticleStore(db_ok=db_ok, ndjson_path=...)` is instantiated with per-domain timestamped NDJSON file

### 8.4 URL Discovery Flow

**Trigger**: `navigator.collect_all_article_urls(start_url, domain)`

1. `BrowserEngine` is started as an async context manager (launches Chromium)
2. `SiteNavigator` is instantiated with the browser, selector client, and configuration
3. `_discover_sections(start_url)` fetches the homepage HTML and applies 14 CSS nav selectors to find section/category links
4. Section links are filtered: duplicates removed, off-domain links removed, skip-list paths excluded (`/tag/`, `/search`, `/login`, etc.)
5. For each discovered section URL:
   a. `_collect_urls_from_section(section_url, domain)` is called
   b. The section page is rendered with Playwright
   c. `selector_client.get_or_discover(domain, section_url, html)` is called to get CSS selectors
   d. Article link elements are extracted using the returned `article_links_selector`
   e. URLs are validated (same domain, not a pagination URL, path length heuristics)
   f. Paginator advances to the next listing page if `pagination_next_selector` matches
   g. Infinite scroll is attempted if no pagination found
6. All collected URLs are returned as a flat list

### 8.5 Selector Lookup and Validation Flow

**Trigger**: `selector_client.get_or_discover(domain, url, html, page_type)`

1. **L1 Check (Redis)**: Redis key `selector:{domain}` is queried
   - Hit: Deserialize JSON → `SiteSelectors`; proceed to validation
   - Miss: Continue to L2

2. **L2 Check (PostgreSQL)**: `site_selectors` table queried for domain + page_type
   - Hit: Deserialize → `SiteSelectors`; write-back to Redis; proceed to validation
   - Miss: Continue to L3

3. **Validation**: Test `article_links_selector` against the provided HTML using BeautifulSoup
   - Minimum 1 match required (`MIN_ARTICLE_LINKS = 1`)
   - HTML < 500 chars: skip validation (assume startup/error page)
   - Validation passes: return `SiteSelectors`
   - Validation fails: invalidate both Redis and PostgreSQL caches; continue to L3

4. **L3 (LLM Discovery)**:
   - `_compact_dom(html)` strips scripts, styles, Tailwind classes; caps at 4000 chars
   - LLM is called with `SELECTOR_DISCOVERY_SYSTEM` + `SELECTOR_DISCOVERY_USER` prompts
   - Response is parsed for JSON; code blocks are stripped if present
   - `SiteSelectors` is constructed from parsed JSON
   - Result is stored in Redis (L1) and PostgreSQL (L2)
   - Returned to caller

5. **Retry Logic**: If validation fails after LLM discovery, up to `RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS` (default 3) re-discovery attempts are made before giving up

### 8.6 Article Fetch and Extract Flow

**Trigger**: `fetch_and_extract(url)` called for each article URL

1. `sem.acquire()` — respects concurrency limit (asyncio.Semaphore)
2. `canonicalize_url(url)` — strips tracking parameters
3. **Strategy determination**: `site_profile.recommend_fetch_method()` returns `static` or `playwright`
4. **Static fetch attempt** (if recommended or unknown):
   a. `fetch_static(canonical)` is called
   b. Returns `html`, `block_signals`, `latency_ms`
   c. `is_blocked(block_signals)` checks for WAF markers
   d. If not blocked and HTML > 500 chars: use this HTML, record static success
   e. If blocked or short: fall through to Playwright
5. **Playwright fetch** (if static failed or not attempted):
   a. If `CAPTURE_SCREENSHOT=True`: `browser.get_with_screenshot(url, ...)` → HTML + screenshot file
   b. Otherwise: `browser.get(url, wait_for=NAVIGATION_STRATEGY)` → HTML
   c. If Playwright fails: log warning, record failure in knowledge, return `None`
6. **Extraction**: `extract_main_content(html, url)` → merged dict
7. **Quality gate**: Title length < `MIN_TITLE_LENGTH` → return `None` (discard)
8. **ArticleRecord construction**: All fields assembled from extraction result
9. **Enrichment**: If `EXTRACT_EMAILS=True`, run `extract_emails(text, html)`; if `EXTRACT_HASHTAGS=True`, run `extract_hashtags(text, html)`
10. **Knowledge update**: `knowledge.record_metadata_signals(...)` and `knowledge.record_article_fetched(...)` update rolling stats
11. **Immediate persistence**: `article_store.save(article)` saves to DB and/or NDJSON
12. Return article dict

### 8.7 Screenshot Capture Flow

**Trigger**: `CAPTURE_SCREENSHOT=True` during article fetch

1. URL slug is generated: last path segment, non-alphanumeric replaced with `_`, truncated to 80 chars
2. Screenshot path: `output/{domain}/screenshots/{YYYYMMDD}/{slug}.{ext}`
3. `browser.get_with_screenshot(url, path, wait_for, screenshot_type)` is called
4. Playwright navigates to URL, waits for `domcontentloaded`
5. `page.screenshot(path=path, full_page=True, type=screenshot_type, quality=80)` is called
6. HTML is returned from `page.content()` simultaneously
7. If screenshot fails, the error is logged but the article extraction continues (non-fatal)

> **Note**: Enabling screenshots forces all articles through Playwright, bypassing the static fetch optimization entirely.

### 8.8 Persistence Flow

**Trigger**: `article_store.save(article)` after each successful extraction

1. **In-memory dedup guard**: Check if `article["url"]` is in `_seen_urls` set
   - If yes: log "duplicate skipped", return immediately
   - If no: add to `_seen_urls` set, continue
2. **PostgreSQL persistence** (if `db_ok`):
   a. Call `save_article(article)` from `shared/db.py`
   b. Executes `INSERT INTO scraped_articles (...) ON CONFLICT (url) DO NOTHING`
   c. If DB error: log error, continue (non-fatal)
3. **NDJSON persistence** (always, as fallback):
   a. Serialize `article` dict to JSON
   b. Append as one line to the `.ndjson` file

### 8.9 Deduplication Flow

**Trigger**: Before article URL processing in `scrape_website()`

1. All collected article URLs are passed through `canonicalize_url()` to strip tracking parameters
2. Python's `dict.fromkeys()` removes in-run URL duplicates (preserves order)
3. If `db_ok`: `filter_unscraped_urls(article_urls)` queries `scraped_urls` table:
   - Batch `SELECT url FROM scraped_urls WHERE url = ANY($1)` finds already-scraped URLs
   - Only URLs not in the result are returned
4. The filtered URL list is truncated to `max_articles`
5. After processing: `mark_urls_scraped(domain, scraped_urls)` batch-inserts into `scraped_urls` table using `INSERT ... ON CONFLICT DO NOTHING`

### 8.10 Site Knowledge Update Flow

**Trigger**: After each article fetch (success or failure)

1. `knowledge.record_article_fetched(domain, method, latency_ms, word_count, success, block_signals)`:
   - Increments `total_scraped` or `total_failed` counter
   - Updates rolling average latency
   - Records WAF signal types from `block_signals`
   - If many consecutive successes with static: marks `preferred_fetch_method = static`
2. `knowledge.record_metadata_signals(domain, has_jsonld, has_og_meta)`:
   - Updates boolean flags for metadata format
3. After all articles: knowledge is persisted via `upsert_site_knowledge(domain, profile_dict)`

### 8.11 Shutdown and Export Flow

**Trigger**: After all article tasks complete

1. `article_store.close()` — closes NDJSON file handle
2. `selector_client.close()` — closes Redis connection pool
3. If `db_ok`: `close_pool()` — closes PostgreSQL connection pool
4. `export_results(articles, domain, output_dir)` generates:
   - `output/{domain}/{timestamp}.json` — full article list with metadata
   - `output/{domain}/{timestamp}.csv` — tabular summary with key fields

---

## 9. Extraction Strategies

### 9.1 Static Fetch Strategy

**Implementation**: `scraper/fetchers/static_fetcher.py`
**Primary library**: `curl-cffi` with `impersonate="chrome124"`
**Fallback library**: `requests`

**When used**: When the site's `preferred_fetch_method` is `static`, or when the site is unknown and static fetch is attempted first.

**Strengths**:
- Fast: 150–400ms typical latency (including anti-bot jitter)
- No Chromium process overhead
- TLS fingerprint spoofing bypasses many WAF fingerprinting checks
- Very low resource consumption

**Limitations**:
- Cannot execute JavaScript
- Cannot handle SPA frameworks that render content client-side
- Cannot handle anti-bot challenges that require JavaScript execution

**Failure Scenarios**:
- HTTP 403/429/503: Returns `block_signals` indicating rate limiting or blocking
- Short HTML (< 500 chars): Indicates empty or error page
- Cloudflare JS challenge: Returns challenge page HTML; `is_blocked()` detects it

**Fallback**: Playwright browser fetch

### 9.2 Playwright Browser Strategy

**Implementation**: `scraper/engines/browser_engine.py`
**Browser**: Chromium (managed by Playwright)

**When used**: When static fetch is blocked, returns insufficient content, or the site is known to require JavaScript.

**Strengths**:
- Handles any website, including full SPAs
- Can execute JavaScript, handle redirects, wait for dynamic content
- Overlay and cookie banner dismissal
- Infinite scroll simulation
- Screenshot capture capability

**Limitations**:
- Slow: 2–15s per page depending on site complexity
- High resource usage (CPU, memory for Chromium process)
- Requires Playwright and Chromium to be installed
- Some advanced fingerprinting systems detect headless browsers despite stealth patches

**Failure Scenarios**:
- Navigation timeout (`BROWSER_TIMEOUT` exceeded): Exception thrown; article skipped
- JavaScript errors on target page: Usually handled gracefully; HTML still extracted
- Page crash: Browser context is reset; next page starts fresh

**Fallback**: Article is skipped; error logged; knowledge records failure

### 9.3 Hybrid Strategy (Default)

**When used**: On first visit to an unknown domain.

The system tries static fetch first. If it succeeds (HTML > 500 chars, no block signals), it records static as the preferred method. If it fails, it falls back to Playwright and records Playwright as the preferred method. On subsequent runs, the recorded preferred method is used directly, skipping the probing step.

### 9.4 Strategy Decision Tree

```
New article URL
    │
    ├─► site_profile.recommend_fetch_method()
    │           │
    │    ┌──────┴──────┐
    │    │             │
    │  static      playwright
    │  or unknown   (forced)
    │    │
    │    ├─► fetch_static(url)
    │    │       │
    │    │  ┌────┴────┐
    │    │  │         │
    │    │ OK       blocked / short
    │    │  │         │
    │    │ use      fallback to
    │    │ HTML     Playwright
    │    │
    │    ├─► Playwright.get(url)
    │    │       │
    │    │  ┌────┴────┐
    │    │  │         │
    │    │ OK       exception
    │    │  │         │
    │    │ use      skip article
    │    │ HTML     log warning
    │
    └─► extract_main_content(html, url)
```

### 9.5 API/XHR Interception Strategy (Planned)

**Status**: Planned, not implemented.

Some sites load article content via API calls (XHR/fetch). A future strategy would intercept these network requests via Playwright's `page.route()` and capture JSON API responses directly, bypassing HTML parsing entirely. This would be faster and more reliable for API-first news sites.

---

## 10. Persistence Layer

### 10.1 PostgreSQL (Primary Persistence)

**Connection**: asyncpg connection pool managed in `shared/db.py`
**Schema creation**: `run_schema()` creates all tables on startup
**Pool size**: Default 5 connections (asyncpg default)

All writes use `ON CONFLICT DO NOTHING` or `ON CONFLICT DO UPDATE` for idempotency. Multiple concurrent runs can coexist without write conflicts.

### 10.2 NDJSON Files (Secondary / Fallback Persistence)

Each run creates a timestamped `.ndjson` file at `output/{domain}/{YYYYMMDD_HHMMSS}.ndjson`. Every article is appended as a JSON line immediately after extraction. This file persists regardless of DB availability and serves as an audit trail and recovery mechanism.

### 10.3 JSON and CSV Export Files

At run completion, two export files are created in `output/{domain}/`:
- `{timestamp}.json` — Full article list as a JSON object with `domain`, `scraped_at`, `total`, `articles` fields
- `{timestamp}.csv` — Tabular summary with 10 key fields for quick analysis

### 10.4 Screenshot Files

When `CAPTURE_SCREENSHOT=True`, PNG or JPEG images are saved at:
`output/{domain}/screenshots/{YYYYMMDD}/{slug}.{ext}`

The directory structure is created automatically. Screenshots are not persisted to the database — only the `screenshot_path` string is stored in the article record.

### 10.5 In-Memory Deduplication

`ArticleStore` maintains a `_seen_urls: set[str]` in memory for the duration of a run. This provides O(1) deduplication within a run before any DB write is attempted, preventing duplicate inserts when the same article URL appears via multiple section pages.

---

## 11. Database Schema Documentation

All tables are created by `shared/db.py:run_schema()` using `CREATE TABLE IF NOT EXISTS`. The schema is idempotent and can be run on every startup safely.

### 11.1 `sites` Table

```sql
CREATE TABLE IF NOT EXISTS sites (
    id          SERIAL PRIMARY KEY,
    domain      VARCHAR(255) UNIQUE NOT NULL,
    start_url   TEXT NOT NULL,
    name        VARCHAR(255),
    schedule    VARCHAR(50) DEFAULT '0 * * * *',  -- cron expression
    max_pages   INT DEFAULT 100,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

**Purpose**: Site registry. One row per scraped domain.
**Usage**: `upsert_site(domain, start_url)` inserts or updates on every run startup.
**Key field**: `domain` (unique constraint ensures one row per site).

### 11.2 `site_selectors` Table

```sql
CREATE TABLE IF NOT EXISTS site_selectors (
    id                       SERIAL PRIMARY KEY,
    domain                   VARCHAR(255) NOT NULL,
    page_type                VARCHAR(50) DEFAULT 'listing',
    article_links_selector   TEXT,
    pagination_next_selector TEXT,
    article_body_selector    TEXT,
    title_selector           TEXT,
    date_selector            TEXT,
    author_selector          TEXT,
    confidence               FLOAT DEFAULT 0.0,
    model_used               VARCHAR(100),
    created_at               TIMESTAMP DEFAULT NOW(),
    updated_at               TIMESTAMP DEFAULT NOW(),
    UNIQUE(domain, page_type)
);
```

**Purpose**: L2 (PostgreSQL) selector cache. Stores LLM-discovered CSS selectors per domain.
**TTL**: 30 days (checked by comparing `updated_at` with current timestamp in selector client).
**Key constraint**: `UNIQUE(domain, page_type)` — one selector set per domain per page type.

### 11.3 `scraped_urls` Table

```sql
CREATE TABLE IF NOT EXISTS scraped_urls (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT UNIQUE NOT NULL,
    domain      VARCHAR(255),
    scraped_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scraped_urls_domain ON scraped_urls(domain);
```

**Purpose**: Cross-run URL deduplication. Every successfully scraped URL is recorded here.
**Usage**: `filter_unscraped_urls(urls)` batch-queries this table to exclude already-scraped URLs.
**Dedup guarantee**: `UNIQUE` constraint on `url` prevents duplicate entries even with concurrent runs.

### 11.4 `scraped_articles` Table

```sql
CREATE TABLE IF NOT EXISTS scraped_articles (
    id                  BIGSERIAL PRIMARY KEY,
    url                 TEXT UNIQUE NOT NULL,
    canonical_url       TEXT,
    domain              VARCHAR(255),
    title               TEXT,
    author              TEXT,
    authors             JSONB,
    published_date      TIMESTAMP,
    updated_date        TIMESTAMP,
    language            VARCHAR(10),
    content             TEXT,
    summary             TEXT,
    top_image           TEXT,
    tags                JSONB,
    keywords            JSONB,
    publisher           JSONB,
    article_type        VARCHAR(100),
    word_count          INT,
    reading_time_minutes INT,
    scraped_at          TIMESTAMP DEFAULT NOW(),
    fetch_method        VARCHAR(50),
    fetch_latency_ms    INT,
    overall_score       FLOAT,
    title_score         FLOAT,
    content_score       FLOAT,
    date_score          FLOAT,
    author_score        FLOAT,
    likely_paywalled    BOOLEAN DEFAULT FALSE,
    likely_liveblog     BOOLEAN DEFAULT FALSE,
    field_sources       JSONB,
    field_confidence    JSONB,
    raw_json            JSONB,
    emails              JSONB,
    hashtags            JSONB,
    screenshot_path     TEXT
);
CREATE INDEX IF NOT EXISTS idx_scraped_articles_domain ON scraped_articles(domain);
CREATE INDEX IF NOT EXISTS idx_scraped_articles_scraped_at ON scraped_articles(scraped_at);
```

**Purpose**: Full persistent article storage. Every extracted article is stored here.
**Dedup**: `UNIQUE` on `url` with `ON CONFLICT DO NOTHING` prevents duplicates.
**JSONB fields**: `authors`, `tags`, `keywords`, `publisher`, `field_sources`, `field_confidence`, `emails`, `hashtags`, `raw_json` store variable-length structured data.
**`raw_json`**: The complete article dict is stored as JSONB, enabling future schema changes without data loss.

### 11.5 `site_knowledge` Table

```sql
CREATE TABLE IF NOT EXISTS site_knowledge (
    id                       SERIAL PRIMARY KEY,
    domain                   VARCHAR(255) UNIQUE NOT NULL,
    preferred_fetch_method   VARCHAR(50) DEFAULT 'playwright',
    requires_js              BOOLEAN DEFAULT FALSE,
    is_spa                   BOOLEAN DEFAULT FALSE,
    has_cloudflare           BOOLEAN DEFAULT FALSE,
    has_datadome             BOOLEAN DEFAULT FALSE,
    has_recaptcha            BOOLEAN DEFAULT FALSE,
    has_paywall              BOOLEAN DEFAULT FALSE,
    has_comments             BOOLEAN DEFAULT FALSE,
    has_infinite_scroll      BOOLEAN DEFAULT FALSE,
    has_jsonld               BOOLEAN DEFAULT FALSE,
    has_og_meta              BOOLEAN DEFAULT FALSE,
    avg_latency_ms           INT DEFAULT 0,
    avg_word_count           INT DEFAULT 0,
    total_scraped            INT DEFAULT 0,
    total_failed             INT DEFAULT 0,
    selector_failures        INT DEFAULT 0,
    block_rate               FLOAT DEFAULT 0.0,
    last_scraped_at          TIMESTAMP,
    created_at               TIMESTAMP DEFAULT NOW(),
    updated_at               TIMESTAMP DEFAULT NOW()
);
```

**Purpose**: Per-domain learning store. Accumulates behavioral knowledge across runs.
**Update pattern**: `upsert_site_knowledge()` uses `ON CONFLICT (domain) DO UPDATE` with rolling average calculations.
**Strategy learning**: `preferred_fetch_method` and `requires_js`/`is_spa` flags drive `SiteProfile.recommend_fetch_method()`.

### 11.6 `scrape_jobs` Table

```sql
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id          BIGSERIAL PRIMARY KEY,
    site_id     INT REFERENCES sites(id),
    status      VARCHAR(50) DEFAULT 'pending',
    started_at  TIMESTAMP,
    finished_at TIMESTAMP,
    pages_found INT DEFAULT 0,
    llm_calls   INT DEFAULT 0,
    errors      INT DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

**Purpose**: Job audit trail for distributed mode. Each scrape run creates a job record.
**Note**: Used primarily in distributed/scheduler mode, not the standalone CLI.

### 11.7 `scraper_nodes` Table

**Purpose**: Distributed node registry. Each scraper instance registers itself.
**Note**: Not used in standalone mode.

### 11.8 `robots_cache` Table

**Purpose**: Cache of fetched `robots.txt` content per domain.
**Note**: Populated but not enforced in current implementation.

### 11.9 `site_strategies` Table (Legacy)

```sql
CREATE TABLE IF NOT EXISTS site_strategies (
    id          SERIAL PRIMARY KEY,
    domain      VARCHAR(255) UNIQUE NOT NULL,
    strategy    VARCHAR(50),
    ...
);
```

**Purpose**: Legacy strategy storage from earlier project versions. Kept for backward compatibility.
**Current behavior**: `site_knowledge` supersedes this table for strategy decisions.

---

## 12. Selector Learning and Reuse

### 12.1 Why LLM-Based Selector Discovery?

Traditional scrapers hardcode CSS selectors like `.article-title a` or `#content .post h2`. These selectors:
- Break when the site updates its HTML structure
- Must be manually written for each new site
- Cannot adapt to site redesigns automatically

LLM-based discovery asks the model: "Given this HTML, what CSS selector would match article links?" The model acts as a domain expert, returning selectors based on semantic understanding of the DOM structure. These selectors are more stable than manually written ones because they tend to target semantic HTML elements and meaningful class names rather than structural quirks.

### 12.2 How Selectors Are Discovered

The LLM discovery process (in `selector_client.py:_call_llm()`) works as follows:

1. **DOM compaction** (`_compact_dom(html)`):
   - Remove `<script>`, `<style>`, `<svg>`, `<iframe>` elements
   - Remove Tailwind/utility class patterns (regex strips `flex`, `grid`, `px-*`, `py-*`, `text-*`, `bg-*`, `border-*`, `rounded-*`, etc.)
   - Remove class attributes that become empty after stripping
   - Truncate to 4,000 characters

2. **System prompt** enforces these rules on the LLM:
   - Prefer semantic HTML elements (`<article>`, `<main>`, `<header>`)
   - Prefer `id` attributes, `data-*` attributes, and descriptive class names
   - Use maximum 2 class names in any selector
   - Never use utility/Tailwind class names (colons, brackets, single characters)
   - Return `""` if a selector cannot be determined
   - Return a confidence float (0.0–1.0)

3. **User prompt** requests:
   ```
   For the site {domain} (listing page at {url}), return CSS selectors for:
   - article_links_selector
   - pagination_next_selector
   - article_body_selector
   - title_selector
   - date_selector
   - author_selector
   Respond with JSON only.
   ```

4. **Response parsing** (`parse_json_response()`):
   - Strips markdown code blocks (```json ... ```)
   - Handles trailing commas (malformed JSON cleanup)
   - Extracts JSON from prose if the model includes explanation text
   - Returns `SiteSelectors` Pydantic model

### 12.3 How Selectors Are Validated

After fetching any selector from any cache layer, the selector is validated against the actual HTML before being used. Validation logic in `_validate_selectors()`:

```python
if len(html) < 500:
    return True  # Too short to validate meaningfully; skip check

soup = BeautifulSoup(html, "html.parser")
elements = soup.select(selectors.article_links_selector)
return len(elements) >= MIN_ARTICLE_LINKS  # MIN_ARTICLE_LINKS = 1
```

If validation fails:
1. Redis key `selector:{domain}` is deleted
2. PostgreSQL `site_selectors` row for `(domain, page_type)` is deleted
3. LLM discovery is triggered again
4. This retry loop repeats up to `RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS` times (default 3)

### 12.4 Selector Cache Lifecycle

```
First run (no cache):
  Redis miss → PG miss → LLM call → store in PG + Redis → validate → use

Subsequent runs (within 1 hour):
  Redis hit → validate → use  (sub-millisecond)

After 1 hour (Redis TTL expired):
  Redis miss → PG hit → validate → write-back to Redis → use

After 30 days (PG TTL expired):
  Redis miss → PG miss → LLM call → store in PG + Redis → validate → use

On selector failure (site redesign):
  Redis hit → validate FAILS → delete Redis + PG → LLM call → new selectors
```

### 12.5 Fallback Selectors

If LLM discovery fails or returns unusable selectors, the system has hardcoded fallback selectors for pagination in `paginator.py`:

```python
FALLBACK_NEXT_SELECTORS = [
    "a[rel='next']",
    "a.next",
    "a.next-page",
    ".pagination a.next",
    ...  # 16 total patterns
]
```

These are tried in order when the LLM-discovered `pagination_next_selector` matches nothing.

### 12.6 RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS Behavior

This config value (default 3) controls how many LLM re-discovery attempts are made when selector validation repeatedly fails. The full retry loop:

```
Attempt 1: LLM call → validate → FAIL → delete cache
Attempt 2: LLM call → validate → FAIL → delete cache
Attempt 3: LLM call → validate → FAIL → return empty selectors
```

After exhausting retries, the system logs a warning and returns empty `SiteSelectors`. URL collection from that section will produce no results, but the run continues with other sections.

**Cost implication**: 3 LLM calls × ~5 seconds each = ~15 seconds delay on worst-case selector failure. For local Ollama models, this is acceptable. For cloud APIs (Claude/GPT-4), this could cost ~$0.03–0.15 per failure event.

---

## 13. Legacy Inspirations (Morpheu / Zenith)

### 13.1 Morpheu

Located at `/home/bogdan/workspace/dev/gen_scraper/morpheu`, Morpheu was an earlier generation scraper project. Key patterns borrowed:

- **Per-domain JSON knowledge files**: Morpheu stored scraped article metadata and site behavior in per-domain JSON files. This pattern inspired the `site_knowledge` PostgreSQL table, which serves the same purpose with transactional guarantees.

- **Strategy probing**: Morpheu tried multiple fetch strategies and recorded which worked. The current `SiteProfile.recommend_fetch_method()` and `preferred_fetch_method` field directly inherit this approach, formalized into a proper data model.

- **Section discovery from navigation**: The concept of crawling a site's nav elements to discover categories (rather than requiring a predefined sitemap) originated in Morpheu.

### 13.2 Zenith

Located at `/home/bogdan/workspace/dev/gen_scraper/zenith`, Zenith introduced:

- **Multi-source extraction**: The concept of running multiple independent extractors (JSON-LD, OG, Readability) and merging by confidence was pioneered in Zenith. The current `processing/scoring/merge.py` is a direct evolution.

- **Quality scoring**: Zenith had basic content quality signals (word count thresholds, title presence). The current `processing/scoring/quality.py` extends this with a formal per-field weighted score.

- **Block signal detection**: Zenith had primitive WAF detection. The current `scraper/detectors/anti_bot.py` expands this with 14 detection categories.

- **Trafilatura integration**: Zenith used trafilatura as the primary extraction library. The current system uses it as one of five sources with confidence-weighted merging.

### 13.3 Key Differences from Legacy Projects

| Feature | Morpheu/Zenith | Current System |
|---------|---------------|----------------|
| Site knowledge | Per-domain JSON files | PostgreSQL `site_knowledge` table |
| Selectors | Hardcoded or manual | LLM-discovered, three-tier cached |
| Extraction | Single library | Five-source confidence merge |
| Persistence | File-based | PostgreSQL + NDJSON fallback |
| Deduplication | Filename-based | URL-normalized + DB `scraped_urls` |
| Article schema | Variable | Canonical `ArticleRecord` |
| Monitoring | Print statements | structlog + Prometheus |

---

## 14. Error Handling and Resilience

### 14.1 Per-Article Failure Tolerance

Each article URL is processed independently in `fetch_and_extract()`. If any step raises an exception:
- Static fetch exception: caught, falls back to Playwright
- Playwright exception: caught, logged as `article_fetch_failed`, returns `None`
- Extraction returns empty: logged as `article_no_content`, returns `None`
- Title too short: logged as `article_title_too_short`, returns `None`
- DB save fails: logged as error but article dict is still returned (NDJSON still works)

`asyncio.gather()` collects all results; `None` values are filtered out. One failed article never blocks others.

### 14.2 Database Failure Tolerance

If PostgreSQL is unavailable:
1. `_init_db()` returns `False`
2. `db_ok=False` propagates to `ArticleStore`, `SiteKnowledgeRepository`, `SelectorClient`
3. `ArticleStore` uses NDJSON-only persistence
4. `SelectorClient` cannot use L2 cache (PG) but still tries Redis L1 and LLM L3
5. `SiteKnowledgeRepository` uses default `SiteProfile` (no historical knowledge)
6. URL deduplication is skipped (risk: re-scraping articles from previous runs)
7. Run completes normally; all articles saved to NDJSON file

### 14.3 LLM Failure Tolerance

If the LLM is unavailable or not configured:
1. `_build_llm_client()` returns `None` or raises an exception (caught)
2. `SelectorClient` is initialized with `llm_client=None`
3. On cache miss: `_call_llm()` logs a warning and returns empty `SiteSelectors`
4. Navigation from cached selectors still works if selectors exist in Redis or PG
5. First-time scraping of new sites degrades: no article links collected, zero articles returned

### 14.4 Redis Failure Tolerance

If Redis is unavailable:
1. `SelectorClient._redis` initialization fails silently; `_redis = None`
2. All L1 (Redis) operations are skipped
3. System falls back to PG (L2) + LLM (L3) for selector lookup
4. Performance impact: slightly slower selector lookup (PG query instead of Redis)
5. No functional degradation

### 14.5 Anti-Bot Blocking Handling

When a static fetch returns a blocked response:
1. `is_blocked(block_signals)` returns `True`
2. Static HTML is discarded
3. Playwright fetch is attempted instead
4. Block signals are passed to `knowledge.record_article_fetched()` for statistical tracking
5. If block rate exceeds 30% in `SiteProfile`, Playwright is set as preferred method for future runs

### 14.6 Timeout Handling

Playwright operations have a global timeout of `BROWSER_TIMEOUT` (default 45 seconds). If a page navigation exceeds this:
1. Playwright raises `TimeoutError`
2. `fetch_and_extract()` catches this as a generic exception
3. Article is marked as failed, `None` is returned
4. Run continues with remaining URLs

### 14.7 Partial Extraction Handling

If one extractor fails (e.g., trafilatura throws an exception on malformed HTML):
1. The exception is caught within `extractor.py`
2. That source's fields are empty/None
3. Other extractors continue independently
4. Field merging uses whatever non-empty values exist from other sources
5. Quality scores reflect missing fields naturally (date_score=0 if no date found)

---

## 15. Logging, Observability, and Debugging

### 15.1 Logging Structure

The system uses `structlog` configured in `shared/logging.py`. All log output is structured (key-value pairs), making it trivially parseable by log aggregation systems.

**Console format** (human-readable, development):
```
2026-03-08 10:15:23 [INFO] app: scrape_start domain=biziday.ro max_articles=100
2026-03-08 10:15:24 [DEBUG] selector_client: cache_hit domain=biziday.ro layer=redis
```

**JSON format** (machine-readable, production):
```json
{"timestamp": "2026-03-08T10:15:23", "level": "info", "logger": "app", "event": "scrape_start", "domain": "biziday.ro", "max_articles": 100}
```

### 15.2 Key Log Events

| Event | Logger | Level | Meaning |
|-------|--------|-------|---------|
| `scrape_start` | `app` | INFO | Run beginning |
| `site_knowledge_loaded` | `app` | INFO | Per-domain knowledge loaded |
| `collecting_article_urls` | `app` | INFO | Phase 1 starting |
| `article_urls_collected` | `app` | INFO | Phase 1 complete, count reported |
| `all_urls_already_scraped` | `app` | INFO | All URLs in `scraped_urls` table (normal) |
| `article_fetched_static` | `app` | DEBUG | Static fetch succeeded |
| `article_fetched_playwright` | `app` | DEBUG | Playwright fetch succeeded |
| `article_fetch_failed` | `app` | WARNING | Both fetch strategies failed |
| `article_saved` | `article_store` | DEBUG | Successful DB persistence |
| `scrape_done` | `app` | INFO | Run complete with count |
| `cache_hit` | `selector_client` | DEBUG | Redis/PG cache hit |
| `cache_miss` | `selector_client` | DEBUG | Cache miss, LLM called |
| `selector_validation_failed` | `selector_client` | WARNING | Selectors don't match live HTML |
| `no_llm_configured` | `app` | WARNING | No LLM API key found |
| `db_unavailable` | `app` | WARNING | PostgreSQL connection failed |

### 15.3 Prometheus Metrics

Metrics are exposed on `http://localhost:{METRICS_PORT}/metrics` (default port 9090).

**Selector cache performance**:
- `selector_cache_hits_total{domain}` — Cache hits (Redis + PG combined)
- `selector_cache_misses_total{domain}` — Cache misses (LLM called)

**Scraper performance**:
- `pages_fetched_total{domain, method}` — Total pages fetched
- `pages_blocked_total{domain}` — Pages blocked by anti-bot
- `fetch_duration_seconds{domain, method}` — Fetch latency histogram

**LLM performance**:
- `llm_requests_total{endpoint, model, status}` — LLM API call counts
- `llm_tokens_sent_total{endpoint}` — Approximate token counts
- `llm_duration_seconds{endpoint}` — LLM latency histogram

### 15.4 Debugging Failures

**Selector failures** (`selector_validation_failed`):
1. Set `LOG_LEVEL=DEBUG` to see compact DOM sent to LLM
2. Set `HEADLESS=False` to watch Playwright navigate
3. Check `site_selectors` table: `SELECT * FROM site_selectors WHERE domain='...'`
4. Reduce `RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS` to 1 to fail fast and inspect logs

**Anti-bot blocking** (`pages_blocked_total`):
1. Check `site_knowledge` for `has_cloudflare`, `has_datadome` flags
2. Try with `HEADLESS=False` to see if human interaction is needed
3. Check if site requires cookies: `NAVIGATION_STRATEGY=networkidle` gives more time for JS challenges

**Empty article extraction**:
1. Enable `CAPTURE_SCREENSHOT=True` to get visual evidence of what Playwright rendered
2. Check `article_no_content` log events for URL patterns
3. Lower `MIN_TITLE_LENGTH` temporarily to see what titles are being extracted

**Performance analysis**:
1. Watch `fetch_duration_seconds` metric in Prometheus/Grafana
2. Compare `selector_cache_hits` vs `selector_cache_misses` per domain
3. Check `site_knowledge.avg_latency_ms` in PostgreSQL for per-domain trends

---

## 16. Performance and Optimization

### 16.1 How the Scraper Becomes Faster Over Time

On the **first run** of a new domain, the system performs expensive operations:
- LLM selector discovery: 3–15 seconds per section (local) or 0.5–2 seconds (cloud)
- Static vs. Playwright probing: one extra fetch per article to determine best strategy
- No knowledge of WAF behavior or metadata format

On the **second run** (same day):
- Redis cache hits for selectors: sub-millisecond
- Preferred fetch method known: no probing
- WAF signals known: avoid strategies likely to fail

On the **third+ run** (after Redis TTL but within PG TTL):
- PostgreSQL cache hits: ~1–5ms
- Everything else same as second run

This progressive improvement is the core value proposition of the persistent knowledge architecture.

### 16.2 Static Fetch Cost vs. Playwright Cost

| Metric | Static (curl-cffi) | Playwright (Chromium) |
|--------|-------------------|----------------------|
| Latency | 150–750ms | 2,000–15,000ms |
| CPU | Minimal | High (JS engine) |
| Memory | ~50MB RSS | ~300–800MB RSS per page |
| Concurrency | Limited by jitter delay | Limited by Chromium processes |

For a 100-article run:
- All static: ~1–2 minutes
- All Playwright: ~5–25 minutes

The static-first strategy reduces average run time by 3–10x for sites that support it.

### 16.3 Concurrency Model

Articles are fetched concurrently using `asyncio.gather()` with a `asyncio.Semaphore(SCRAPER_CONCURRENCY)` (default 3). This means:
- Up to 3 article fetches proceed simultaneously
- Static fetches: limited by network I/O and artificial jitter
- Playwright fetches: limited by Chromium process count and memory

For Playwright-heavy sites, `SCRAPER_CONCURRENCY=1` or `2` is safer to avoid memory pressure.

### 16.4 LLM Cost Optimization

The three-tier cache ensures LLM is called at most:
- Once per domain per 30 days (PG TTL)
- Or once per domain per hour (Redis TTL, if PG is also unavailable)
- Or on selector validation failure (immediate re-discovery)

For a 100-domain scraping operation with daily runs, LLM calls are:
- Day 1: 100 calls (one per domain, cold start)
- Day 2–30: 0 calls (all cached in PG)
- Day 31: 100 calls (PG cache expiry)

With a local Ollama model, LLM cost is zero. With Claude Sonnet (~$0.003/call estimate), 100 calls = $0.30 per month.

### 16.5 Extraction Pipeline Performance

The five-source extraction pipeline runs each extractor sequentially on the same HTML string:
1. JSON-LD: regex scan for `<script>` tags — O(n) where n = HTML length
2. trafilatura: full document parsing — O(n) with NLP heuristics (~100–300ms)
3. Open Graph: BeautifulSoup tag scan — O(n)
4. htmldate: date pattern matching — O(n)
5. readability: DOM parsing + scoring — O(n), only if trafilatura < 100 chars

Total extraction time per article: ~100–500ms, dominated by trafilatura.

---

## 17. Security, Safety, and Compliance

### 17.1 Anti-Bot Considerations

The system spoofs TLS fingerprints and uses stealth browser patches. This is effective against:
- JA3 TLS fingerprinting (chrome124 impersonation defeats this)
- Basic headless detection (playwright-stealth patches navigator.webdriver)
- Simple UA-based blocking (realistic UA strings rotated)

This does NOT defeat:
- Advanced behavioral analysis (mouse movement, click patterns, scroll velocity)
- CAPTCHA solving requirements
- IP reputation blocking (shared hosting IPs often blocklisted)
- Advanced bot management platforms (PerimeterX, Kasada, F5 Distributed Cloud)

### 17.2 Rate Limiting and Politeness

The system applies a 150–750ms random delay between static fetches (jitter). Playwright navigation waits for `domcontentloaded` before proceeding. However:
- No explicit global rate limiting per domain is implemented
- `robots.txt` is fetched and cached but not enforced in the current codebase
- For high-volume production use, implement per-domain rate limiting in `paginator.py`

### 17.3 Credential Handling

- All credentials are stored in `.env` (not committed to version control)
- PostgreSQL password, Redis password, LLM API keys are read only via environment variables
- No credential is logged (structlog redacts nothing by default — avoid logging sensitive config values)
- The `.env` file should be in `.gitignore`

### 17.4 Stored Content Safety

- Article text content is stored in PostgreSQL in a `TEXT` column (XSS-safe for web display if escaped)
- HTML is not stored directly (trafilatura returns plaintext)
- `raw_json JSONB` stores the full article dict — contains no raw HTML
- Screenshots are stored as files in `output/`; ensure this directory is not publicly web-accessible

### 17.5 Database Security

- asyncpg uses parameterized queries throughout; no string interpolation for user-controlled values
- The only user-controlled input is the `--website` argument, which is:
  - Stripped of protocol prefix
  - Used only as a string value in parameterized queries
  - Never passed to shell commands

---

## 18. Extensibility Guide

### 18.1 Adding a New Extractor

1. Create `processing/extractors/myextractor.py` following the pattern of `jsonld.py` or `og_meta.py`
2. Implement `extract(html: str, url: str) -> dict` returning any subset of the standard field keys
3. Define a confidence level for each field (0.0–1.0)
4. Add your extractor to `processing/filters/extractor.py:extract_main_content()`:
   ```python
   from processing.extractors.myextractor import extract as extract_mine
   mine_data = extract_mine(html, url)
   sources["mine"] = {"data": mine_data, "confidence": 0.80}
   ```
5. Add your source to `processing/scoring/merge.py:FIELD_PRIORITY` for each field you provide:
   ```python
   FIELD_PRIORITY = {
       "title": ["jsonld", "mine", "trafilatura", "og", "readability"],
       ...
   }
   ```
6. Add unit tests in `tests/unit/test_extractor.py`

### 18.2 Adding a New Enrichment

1. Create `processing/enrichers/myenricher.py` with a function `enrich(text: str, html: str) -> Any`
2. Add a config toggle in `scraper/config.py`:
   ```python
   extract_mydata: bool = Field(False, alias="EXTRACT_MYDATA")
   ```
3. Add the enrichment call in `app.py:_enrich_article()`:
   ```python
   if config.extract_mydata:
       from processing.enrichers.myenricher import enrich
       article["mydata"] = enrich(text, html)
   ```
4. Add the field to `scraped_articles` table in `shared/db.py` schema
5. Handle the field in `shared/db.py:save_article()` INSERT statement

### 18.3 Adding a New Fetch Strategy

1. Create `scraper/fetchers/mymethod_fetcher.py` implementing `async fetch_mymethod(url: str) -> dict` returning the standard dict with `html`, `block_signals`, `latency_ms`, `method` keys
2. Add a strategy constant in `scraper/knowledge/site_knowledge.py`:
   ```python
   STRATEGY_MYMETHOD = "mymethod"
   ```
3. Add strategy recommendation logic in `SiteProfile.recommend_fetch_method()`
4. Add the strategy branch in `app.py:fetch_and_extract()` after the static fetch block

### 18.4 Adding New Site Knowledge Fields

1. Add columns to `site_knowledge` table in `shared/db.py:run_schema()`
2. Add the field to `SiteProfile` dataclass in `scraper/knowledge/site_knowledge.py`
3. Add `record_*` method to `SiteKnowledgeRepository` if the field requires computed updates
4. Update `upsert_site_knowledge()` SQL in `shared/db.py` to include the new column

### 18.5 Adding a New Output Format

1. Add an export function in `app.py` following the pattern of `export_results()`
2. Write to `output/{domain}/{timestamp}.{ext}`
3. Add the new format to the returned `exported` dict
4. Consider adding an `--output-format` CLI argument for selection

### 18.6 Adding New Observability

Prometheus metrics are defined in `shared/metrics.py`. To add a new metric:
```python
my_counter = Counter("my_metric_total", "Description", ["label1", "label2"])
```
Import and increment it where needed:
```python
from shared.metrics import my_counter
my_counter.labels(label1="val", label2="val2").inc()
```

---

## 19. Deployment and Operation

### 19.1 Prerequisites

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Runtime |
| Playwright + Chromium | Latest | Browser rendering |
| PostgreSQL | 14+ | Primary persistence |
| Redis | 7+ | L1 selector cache |
| Ollama | Latest | Local LLM (or use cloud API) |

### 19.2 Local Development Setup

```bash
# 1. Clone and create virtual environment
cd llm-scraper
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -e .

# 3. Install Playwright browsers
playwright install chromium

# 4. Start infrastructure
docker-compose -f docker/docker-compose.yml up -d postgres redis ollama

# 5. Pull the LLM model
docker exec docker-ollama-1 ollama pull qwen2.5-coder:7b

# 6. Configure environment
cp .env.example .env
# Edit .env with your settings

# 7. Run
python3 app.py --website biziday.ro --pages 2 --articles 10
```

### 19.3 Command Reference

```bash
# Basic scrape
python3 app.py --website adevarul.ro

# Limit pages and articles
python3 app.py --website biziday.ro --pages 5 --articles 30

# Custom output directory
python3 app.py --website euronews.ro --output /data/scrapes/

# With screenshots (slow — forces Playwright for all articles)
CAPTURE_SCREENSHOT=True python3 app.py --website site.ro

# Debug mode
LOG_LEVEL=DEBUG HEADLESS=False python3 app.py --website site.ro --pages 1 --articles 3

# Run all unit tests
python -m pytest tests/unit/ -q

# Run single test file
python -m pytest tests/unit/test_article_store.py -v

# Run specific test
python -m pytest tests/unit/test_extractor.py::test_jsonld_extraction -v
```

### 19.4 Docker Deployment

The `docker/docker-compose.yml` provides a full development stack:

```bash
# Start all services
docker-compose -f docker/docker-compose.yml up -d

# Check service health
docker-compose ps

# View scraper logs
docker-compose logs -f scraper

# Access pgAdmin
open http://localhost:5050  # admin@admin.com / admin

# Access Kafka UI
open http://localhost:8090

# Access Kibana
open http://localhost:5601
```

### 19.5 Operational Troubleshooting Checklist

| Symptom | Investigation | Resolution |
|---------|---------------|------------|
| Zero articles scraped | Check `no_article_urls_found` log | Selectors may be wrong; check `site_selectors` table |
| All URLs already scraped | Check `scraped_urls` table count for domain | Normal; use `--skip-dedup` (planned) or clear `scraped_urls` |
| LLM not called | Check Redis/PG cache for domain | Cache valid; use `DELETE FROM site_selectors WHERE domain=X` to force re-discovery |
| Cloudflare blocking | Check `site_knowledge.has_cloudflare` | Use proxies or increase jitter |
| Playwright timeout | Check `BROWSER_TIMEOUT` | Increase to 60000–90000ms |
| Low content quality scores | Check `content_score` distribution | Site may have paywall; check `likely_paywalled` flag |

---

## 20. Known Limitations

### 20.1 LLM Selector Quality

`qwen2.5-coder:7b` (local Ollama model) produces incorrect selectors for approximately 10–20% of sites. Common failure modes:
- Returns Tailwind utility class names despite prompt instructions
- Returns overly generic selectors that match navigation elements, not articles
- Generates selectors that match elements present on the wrong page type

Mitigations in place: DOM compaction removes Tailwind classes; system prompt includes negative examples; validation rejects selectors with zero matches.

Better results are obtained with Claude Sonnet or GPT-4o, but at higher cost per call.

### 20.2 JavaScript-Heavy Single-Page Applications

Sites that load all content via API calls (React/Vue SPAs without SSR) may return minimal HTML even with Playwright if the hydration logic is complex or slow. `NAVIGATION_STRATEGY=networkidle` can help by waiting for all network requests to complete, but adds 5–10 seconds per page.

### 20.3 CAPTCHA-Protected Sites

Sites requiring CAPTCHA solving (reCAPTCHA v3, hCaptcha, Cloudflare Turnstile) are not supported. The system detects them and logs a warning, but cannot automatically solve them.

### 20.4 Infinite Scroll Limitations

Infinite scroll simulation scrolls up to `SCRAPER_SCROLL_MAX` (default 20) times, waiting `SCRAPER_SCROLL_WAIT_MS` between scrolls. Sites with thousands of items require many scrolls; the `20` limit may leave many articles undiscovered on very deep listing pages.

### 20.5 Robots.txt Not Enforced

The `robots_cache` table stores fetched robots.txt content, but the scraper does not parse or enforce it. Operators must manually check `robots.txt` compliance for their use case.

### 20.6 Selector Drift Risk

If a site redesigns between the 30-day PG cache expiry, old selectors return zero matches for one run. The validation system detects this and triggers LLM re-discovery, but the first run after a redesign will always have one round of LLM calls. This is expected behavior.

---

## 21. Future Improvements

### 21.1 Short-Term (High Priority)

- **`--force-rediscover` CLI flag**: Invalidate selector cache for a domain and force LLM re-discovery
- **`--skip-dedup` CLI flag**: Ignore `scraped_urls` table for re-scraping all URLs
- **Graceful SIGINT shutdown**: Complete in-progress articles before exiting
- **SPA hydration detection**: Auto-detect `domcontentloaded` vs `networkidle` based on page JS activity

### 21.2 Medium-Term

- **API XHR interception**: Intercept Playwright network requests to capture JSON API responses directly, bypassing HTML parsing
- **Adaptive concurrency**: Auto-tune `SCRAPER_CONCURRENCY` based on measured latency and error rate per domain
- **Stronger selector confidence scoring**: Score selectors based on number of matches, element semantic quality, and historical accuracy
- **Dockerfile.app**: Containerized standalone scraper image for one-command deployment

### 21.3 Long-Term

- **ML-based extraction quality scoring**: Train a classifier on extracted articles to predict content quality without relying on heuristic word count thresholds
- **Distributed execution**: Multi-node scraping with Redis-based work queue for large-scale operations
- **Site capability classifier**: Classify sites by type (news, blog, magazine, SPA) to select optimal scraping strategy before any probing
- **Better LLM prompt pipelines**: Chain-of-thought prompting or few-shot examples for improved selector accuracy
- **Automatic selector repair**: When a selector fails, use LLM to analyze the diff between old and new DOM and suggest a targeted fix

---

## 22. Glossary

| Term | Definition |
|------|-----------|
| **ArticleRecord** | The canonical output data structure for a scraped article; same schema regardless of site or extraction method |
| **block signal** | A WAF or anti-bot indicator detected in HTTP response headers or body (e.g., CF-Ray header, "Attention Required" page) |
| **compact DOM** | A stripped version of page HTML sent to the LLM; scripts, styles, and utility CSS classes removed; capped at 4,000 chars |
| **confidence score** | A float (0.0–1.0) indicating how reliable a field value is from a given extraction source |
| **curl-cffi** | A Python HTTP library that spoofs TLS fingerprints of real browsers; used for "static fetch" |
| **DOM** | Document Object Model; the parsed HTML tree of a web page |
| **field_sources** | Dict mapping field names to the extraction source that provided the winning value (e.g., `{"title": "jsonld"}`) |
| **field_confidence** | Dict mapping field names to the confidence score of the winning value |
| **htmldate** | Python library specialized in extracting publication dates from web pages via multiple strategies |
| **JSON-LD** | JavaScript Object Notation for Linked Data; semantic markup embedded in `<script type="application/ld+json">` tags |
| **L1/L2/L3 cache** | Three-tier selector cache: Redis (L1, hot), PostgreSQL (L2, persistent), LLM (L3, source of truth) |
| **liveblog** | An article type that updates in real-time with rolling coverage of an event; detected by keyword heuristics |
| **Ollama** | Local LLM inference server; provides an OpenAI-compatible API for locally-run models |
| **Open Graph** | Protocol for representing web page metadata via `<meta property="og:*">` tags; used by Facebook/social media |
| **paywall** | Content gate requiring payment or subscription; detected by keyword heuristics |
| **Playwright** | Browser automation library; used for full headless Chromium control |
| **qwen2.5-coder:7b** | The default local LLM model for selector discovery; 7-billion parameter code-specialized model |
| **readability** | Mozilla's content extraction algorithm (readability-lxml Python implementation); fallback extractor |
| **scraped_urls** | PostgreSQL table storing every URL that has been successfully scraped; used for cross-run deduplication |
| **selector** | A CSS selector string used to locate HTML elements matching a pattern |
| **selector drift** | When a previously-valid CSS selector no longer matches elements on a redesigned site |
| **SiteProfile** | In-memory Python dataclass holding per-domain knowledge loaded from `site_knowledge` table |
| **stealth mode** | Browser configuration that masks headless browser fingerprints (navigator.webdriver, Chrome runtime, etc.) |
| **strategy** | The fetch method used for a domain: `static`, `playwright`, or `api_intercept` |
| **structlog** | Python structured logging library; all log output is key-value pairs |
| **trafilatura** | Python library for extracting main content from web pages using heuristics; primary body extractor |
| **TTL** | Time To Live; duration before a cached value is considered expired |
| **WAF** | Web Application Firewall; a security system that blocks bot traffic |

---

## 23. Appendix

### A. Sample `.env` Configuration

```ini
# LLM Configuration
# Option A: Local Ollama (free, requires local GPU/CPU)
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5-coder:7b

# Option B: Anthropic Claude (best quality, costs money)
# ANTHROPIC_API_KEY=sk-ant-...

# Option C: OpenAI (good quality, costs money)
# OPENAI_API_KEY=sk-...

# Database
POSTGRES_DSN=postgresql://scraper:scraper@localhost:5432/scraperdb
REDIS_URL=redis://localhost:6379/0

# Runtime limits
SCRAPE_LIMIT=100
SCRAPER_MAX_PAGES=5
SCRAPER_CONCURRENCY=3

# Browser settings
HEADLESS=True
BROWSER_TIMEOUT=45000
USE_STEALTH=True
NAVIGATION_STRATEGY=domcontentloaded

# Selector settings
RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS=3

# Content quality
MIN_TITLE_LENGTH=20

# Enrichments (all off by default for performance)
CAPTURE_SCREENSHOT=False
SCREENSHOT_TYPE=jpeg
EXTRACT_EMAILS=False
EXTRACT_HASHTAGS=False

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=console

# Output
OUTPUT_DIR=output
```

### B. Sample `ArticleRecord` JSON

```json
{
  "url": "https://biziday.ro/article/tech-company-raises-series-b",
  "canonical_url": "https://biziday.ro/article/tech-company-raises-series-b",
  "domain": "biziday.ro",
  "title": "Tech Company Raises $50M Series B",
  "author": "Ion Popescu",
  "authors": ["Ion Popescu"],
  "published_date": "2026-03-07T14:30:00",
  "updated_date": null,
  "language": "ro",
  "content": "O companie de tehnologie românească a anunțat...",
  "summary": "Compania a strâns 50 de milioane de dolari...",
  "top_image": "https://biziday.ro/images/tech-company.jpg",
  "tags": ["tech", "funding", "startup"],
  "keywords": ["series B", "investment"],
  "publisher": {"@type": "Organization", "name": "Biziday"},
  "article_type": "NewsArticle",
  "word_count": 487,
  "reading_time_minutes": 3,
  "scraped_at": "2026-03-08T10:15:47",
  "fetch_method": "static",
  "fetch_latency_ms": 284,
  "overall_score": 0.87,
  "title_score": 1.0,
  "content_score": 0.81,
  "date_score": 1.0,
  "author_score": 1.0,
  "likely_paywalled": false,
  "likely_liveblog": false,
  "field_sources": {
    "title": "jsonld",
    "author": "jsonld",
    "date": "jsonld",
    "content": "trafilatura",
    "top_image": "og"
  },
  "field_confidence": {
    "title": 0.97,
    "author": 0.96,
    "date": 0.98,
    "content": 0.92,
    "top_image": 0.85
  }
}
```

### C. Sample `site_knowledge` Record

```
domain              = "biziday.ro"
preferred_method    = "static"
requires_js         = false
is_spa              = false
has_cloudflare      = false
has_datadome        = false
has_recaptcha       = false
has_paywall         = false
has_jsonld          = true
has_og_meta         = true
avg_latency_ms      = 312
avg_word_count      = 523
total_scraped       = 847
total_failed        = 12
block_rate          = 0.014
last_scraped_at     = "2026-03-08T10:00:00"
```

### D. Sample `site_selectors` Record

```
domain                   = "biziday.ro"
page_type                = "listing"
article_links_selector   = "article.post a.entry-title-link"
pagination_next_selector = "a.next.page-numbers"
article_body_selector    = "div.entry-content"
title_selector           = "h1.entry-title"
date_selector            = "time.entry-date"
author_selector          = "span.author.vcard a"
confidence               = 0.91
model_used               = "qwen2.5-coder:7b"
updated_at               = "2026-03-01T08:30:00"
```

### E. Runtime Lifecycle Walkthrough (biziday.ro, known domain)

```
10:00:00  python3 app.py --website biziday.ro --pages 3 --articles 50
10:00:00  .env loaded → ScraperConfig initialized
10:00:00  asyncpg pool connected → run_schema() (no-op, tables exist)
10:00:01  upsert_site("biziday.ro") → sites table updated
10:00:01  SiteKnowledgeRepository.load("biziday.ro") → SiteProfile(preferred=static, total_scraped=847)
10:00:01  LLMClient initialized (Ollama at localhost:11434)
10:00:01  SelectorClient initialized with Redis L1 cache
10:00:01  ArticleStore initialized → NDJSON file: output/biziday.ro/20260308_100001.ndjson

10:00:01  BrowserEngine starts (Chromium, headless, stealth)
10:00:02  SiteNavigator.collect_all_article_urls("https://biziday.ro", "biziday.ro")
10:00:02  → Render homepage with Playwright
10:00:04  → Discover 8 section URLs from nav elements
10:00:04  → Section 1: https://biziday.ro/tech/
10:00:04    selector_client.get_or_discover("biziday.ro", ...) → Redis HIT (age: 23min)
10:00:04    → article_links_selector validated against live HTML: 18 matches ✓
10:00:05    → 18 article URLs collected
10:00:05  → [repeat for 7 more sections]
10:00:25  → Total: 134 article URLs collected
10:00:25  filter_unscraped_urls(134 URLs) → 51 new URLs (83 already scraped)
10:00:25  Truncate to 50 (max_articles)

10:00:25  Processing 50 articles (concurrency=3):
10:00:25  [1] fetch_and_extract("https://biziday.ro/tech/ai-startup-raises-30m")
10:00:25    recommend_fetch_method() → "static" (biziday.ro known good)
10:00:25    fetch_static() → HTML 48KB, latency 312ms, no block signals
10:00:25    extract_main_content() → jsonld+trafilatura: title✓ author✓ date✓ content✓
10:00:26    quality_score=0.87, word_count=523
10:00:26    article_store.save() → INSERT INTO scraped_articles ✓ → NDJSON append ✓
10:00:26    knowledge.record_article_fetched("biziday.ro", "static", 312, 523, success=True)
...
10:08:47  All 50 articles processed: 48 saved, 2 failed (quality gate)
10:08:47  mark_urls_scraped("biziday.ro", [48 URLs]) → scraped_urls updated
10:08:47  upsert_site_knowledge("biziday.ro", {...total_scraped=895...})

10:08:47  article_store.close() → NDJSON file closed
10:08:47  selector_client.close() → Redis connection closed
10:08:47  close_pool() → asyncpg pool closed

10:08:48  export_results() → output/biziday.ro/20260308_100001.json (48 articles)
10:08:48  export_results() → output/biziday.ro/20260308_100001.csv

  Scraped 48 articles from biziday.ro
  [JSON] output/biziday.ro/20260308_100001.json
  [CSV]  output/biziday.ro/20260308_100001.csv
```
