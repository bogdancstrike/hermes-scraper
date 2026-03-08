# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

Always activate the virtual environment before running any Python commands:
```bash
source .venv/bin/activate
```

Infrastructure required: PostgreSQL (`docker-postgres-1`), Redis (`docker-redis-1`), Ollama (`localhost:11434`).

## Common Commands

```bash
# Run all unit tests
python -m pytest tests/unit/ -q

# Run a single test file
python -m pytest tests/unit/test_article_store.py -v

# Run a single test by name
python -m pytest tests/unit/test_extractor.py::test_name -v

# Integration test (requires live infra + LLM)
python3 app.py --website biziday.ro --pages 1 --articles 5

# Full scrape
python3 app.py --website domain.ro --pages 5 --articles 50 --output results/
```

## Architecture

The scraper operates in two phases via `app.py`:

**Phase 1 — URL Discovery**: `SiteNavigator` renders the homepage with Playwright, discovers section/category URLs from navigation menus, then collects article URLs from each section using LLM-discovered CSS selectors. Selectors are cached in a 3-layer hierarchy (L1=Redis 1hr TTL, L2=PostgreSQL 30-day TTL, L3=LLM on cache miss or validation failure).

**Phase 2 — Article Extraction**: For each URL, tries static fetch first (`curl-cffi` with Chrome124 TLS spoofing), falls back to Playwright. HTML goes through a 5-source extraction pipeline (JSON-LD, OG meta, htmldate, trafilatura, readability) that merges fields by confidence score. Articles are persisted to PostgreSQL immediately after extraction.

### Key Data Flows

**Selector discovery** (`scraper/selector_client.py`): `SelectorClient.get_or_discover(domain, url, html)` → checks Redis → checks PG → validates cached selectors against live HTML → if invalid, calls LLM (`llm_api/llm_client.py`) with compact DOM → stores result.

**Article extraction** (`processing/filters/extractor.py`): `extract_main_content(html, url)` returns a merged dict from all extraction sources. Quality scoring in `processing/scoring/` assigns confidence to each field and flags paywalled/liveblog content.

**Site knowledge** (`scraper/knowledge/site_knowledge.py`): `SiteKnowledgeRepository` tracks per-domain stats (WAF signals, preferred fetch method static/playwright, article counts) across runs. `SiteProfile.recommend_fetch_method()` decides whether to try static first.

**Persistence** (`shared/article_store.py`): `ArticleStore.save()` is idempotent — deduplicates in-memory and in DB. Falls back to NDJSON file if DB is unavailable.

### Module Map

| Path | Responsibility |
|------|----------------|
| `app.py` | CLI entry point, full pipeline orchestration |
| `scraper/config.py` | `ScraperConfig` (pydantic-settings), all env vars |
| `scraper/engines/browser_engine.py` | Playwright engine: stealth, overlay dismissal, infinite scroll, screenshots |
| `scraper/fetchers/static_fetcher.py` | curl-cffi static fetch with requests fallback, random jitter |
| `scraper/detectors/anti_bot.py` | Cloudflare/DataDome/captcha/429 detection from response signals |
| `scraper/navigation/paginator.py` | `SiteNavigator` (section discovery) + `Paginator` (pagination/infinite scroll) |
| `scraper/selector_client.py` | 3-layer selector cache: Redis → PG → LLM |
| `scraper/knowledge/site_knowledge.py` | Per-domain learning: strategy, WAF signals, stats |
| `llm_api/llm_client.py` | `LLMClient` wrapping Anthropic/OpenAI/Ollama APIs |
| `llm_api/prompts.py` | `SELECTOR_DISCOVERY_SYSTEM/USER` prompts |
| `processing/filters/extractor.py` | Multi-source extraction (JSON-LD + OG + htmldate + trafilatura + readability) |
| `processing/scoring/merge.py` | Confidence-based field merging across extraction sources |
| `processing/scoring/quality.py` | Quality scoring: overall score, paywalled/liveblog detection |
| `shared/db.py` | asyncpg pool, all DB helpers, schema auto-creation on startup |
| `shared/article_store.py` | `ArticleStore`: idempotent save, in-memory dedup, NDJSON fallback |
| `shared/models.py` | Pydantic models: `SiteSelectors`, `ArticleRecord` |
| `shared/url_utils.py` | `canonicalize_url` (strips tracking params), `extract_domain` |

## LLM Configuration

The LLM is used **only** for CSS selector discovery on cache miss or validation failure — not per-article.

Current backend: `qwen2.5-coder:7b` via Ollama OpenAI-compatible API at `http://localhost:11434/v1`.

DOM is compacted before sending to LLM (`_compact_dom()` strips Tailwind utility classes). The system prompt guards against utility CSS class names as selectors.

## Key Config (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama/OpenAI-compatible LLM endpoint |
| `LLM_MODEL` | `qwen2.5-coder:7b` | LLM model for selector discovery |
| `POSTGRES_DSN` | `postgresql://scraper:scraper@localhost:5432/scraperdb` | DB connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis L1 cache |
| `SCRAPE_LIMIT` | `100` | Max articles per run |
| `HEADLESS` | `True` | Playwright headless mode |
| `NAVIGATION_STRATEGY` | `domcontentloaded` | Playwright wait strategy |
| `RETRY_DEEP_ANALYSIS_WEBSITE_SELECTORS` | `3` | LLM retry attempts on selector failure |
| `MIN_TITLE_LENGTH` | `20` | Quality gate: skip articles with short titles |
| `CAPTURE_SCREENSHOT` | `False` | Save full-page screenshots |
| `EXTRACT_EMAILS` | `False` | Extract emails from article content |
| `EXTRACT_HASHTAGS` | `False` | Extract hashtags from article content |

## DB Tables

- `sites` — site registry
- `site_selectors` — CSS selector cache (30-day TTL)
- `scraped_urls` — URL deduplication
- `scraped_articles` — full article persistence (JSONB raw + key fields)
- `site_knowledge` — per-domain learning: strategy, WAF signals, stats

Schema is auto-created via `run_schema()` on every startup.

## Testing

121 unit tests, no live infrastructure required:
```bash
python -m pytest tests/unit/ -q
```

Integration tests in `tests/integration/` require PostgreSQL, Redis, Ollama, and live network access.

## Known Issues

- `qwen2.5-coder:7b` occasionally generates Tailwind/generic selectors that match nothing on some sites — the `_compact_dom()` DOM preprocessing and system prompt guards mitigate this but don't eliminate it.
- When all URLs for a domain are already in `scraped_urls`, the scraper exits early with "all_urls_already_scraped" (expected behavior, not a bug).
