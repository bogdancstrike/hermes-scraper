# Hermes — TODO / Session Log

## Session: 2026-03-08

### Completed

#### Infrastructure & Cleanup
- [x] Created `docker-compose.yml` with postgres, redis, ollama, scraper services
- [x] Created root `Dockerfile` (Python 3.12-slim + Playwright Chromium)
- [x] Rewrote `.env` — removed all Kafka, Elasticsearch, MinIO, Sentry variables
- [x] Rewrote `scraper/config.py` — removed all dead config fields
- [x] Rewrote `shared/metrics.py` — removed Kafka/ES metrics
- [x] Removed from `requirements.txt`: `aiokafka`, `elasticsearch`, `elastic-transport`, `minio`, `fastapi`, `fastapi-cli`, `uvicorn`, `starlette`, `APScheduler`, `SQLAlchemy`, `greenlet`
- [x] Added `.claude/`, `CLAUDE.md`, `TODO.md` to `.gitignore`
- [x] `docker-compose.yml` Ollama port changed to 11435 (host 11434 conflict)

#### Code Fixes
- [x] `browser_engine.py` — inlined `_USER_AGENTS` / `_next_ua()` (removed `scraper.anti_bot` import after dir deleted)
- [x] `shared/models.py` — renamed `model_used` → `llm_model`; added `model_config = {"protected_namespaces": ()}` to avoid Pydantic warning
- [x] `app.py` — replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`
- [x] `paginator.py` — heuristic fallback when LLM selector returns 0 matches (critical fix for mediafax.ro, gandul.ro)
- [x] `paginator.py` — added `/live/`, `/emisiuni`, `/video/`, `/galerie`, `/foto/`, `/podcast` to `_SECTION_SKIP` (fix for digi24.ro visiting 31 sections incl. radio streams)
- [x] `paginator.py` — `_is_article_url`: require min 2 path segments (fix for stirileprotv.ro scraping section pages)

#### Deleted (dead distributed-mode code)
- [x] `shared/kafka.py`
- [x] `processing/main.py`, `processing/pipeline.py`
- [x] `llm_api/main.py`, `llm_api/routers/`
- [x] `scraper/main.py`
- [x] `scraper/storage/` (MinIO raw store)
- [x] `scraper/anti_bot/` (proxy_pool, ua_rotator, cookie_jar)
- [x] `scraper/engines/http_engine.py`
- [x] `scheduler/` directory
- [x] `docker/` directory (old Dockerfiles, old docker-compose)
- [x] `scripts/` directory

#### Documentation
- [x] Created `docs/Documentation.md` (full product docs)
- [x] Created `docs/C4_Architecture.md` (C4 diagrams in Mermaid)
- [x] Created `docs/Flows.md` (sequence diagrams for scrape flow)
- [x] Created `docs/run.sh` (batch scraper execution script, all 11 sites)
- [x] Created `CLAUDE.md`
- [x] Updated `docs/run.sh` with all 11 validated sites

### Site Validation Results (2026-03-08, local CLI)

| Site | Status | Notes |
|------|--------|-------|
| biziday.ro | ✓ Works | Static fetch, fast (190-370ms) |
| hotnews.ro | ✓ Works | |
| adevarul.ro | ✓ Works | |
| stirileprotv.ro | ✓ Works | Fixed: was collecting section pages as articles |
| digi24.ro | ✓ Works | Fixed: `/live/` sections now skipped; 24 news sections discovered |
| euronews.ro | ✓ Works | Collects from `/taguri/` and `/categorii/` sections |
| antena3.ro | ⚠ Partial | Collects URLs but some are sub-category pages, not articles |
| mediafax.ro | ✓ Works | Fixed: heuristic fallback when LLM generates wrong selector |
| gandul.ro | ✓ Works | Fixed: heuristic fallback; LLM always generates `.post-title a` |
| romania.europalibera.org | ✓ Works | 4 articles saved |
| gov.ro | ⚠ Partial | Scrapes gov pages; some are section pages, not news articles |

### Remaining / Next Session

#### Docker Testing
- [ ] Wait for `hermes-ollama` container to become healthy (model download ~4.5GB)
- [ ] Verify `hermes-scraper` container starts and connects to all services
- [ ] Test `docs/run.sh biziday.ro` end-to-end via Docker
- [ ] Full `docs/run.sh` test with all 11 sites via Docker

#### Test Report
- [ ] Create `docs/TestReport.md` with per-site results, root causes, fixes applied

#### Documentation
- [ ] Update `docs/Documentation.md`, `docs/C4_Architecture.md`, `docs/Flows.md` with Hermes branding
- [ ] Verify README.md is up to date with current feature set and badges

#### Quality Improvements
- [ ] antena3.ro: investigate why sub-category URLs pass `_is_article_url` (depth 3 paths like `/politica/alegeri-prezidentiale-2025` collected as articles)
- [ ] gov.ro: non-news pages being scraped (section pages like `/ro/prim-ministru/echipa-prim-ministrului` collected as articles)
- [ ] Add Romanian utility page patterns to `_SECTION_SKIP`: `/politica-de-cookies`, `/termeni-si-conditii`, `/politica-de-confidentialitate`
- [ ] LLM selector quality: qwen2.5-coder:7b reliably generates `.post-title a` for many sites — improve system prompt or switch to a better local model

#### Unit Tests
- [ ] Add tests for the heuristic fallback in `_extract_article_links`
- [ ] Add tests for new `_SECTION_SKIP` patterns (live, emisiuni, video)
- [ ] Run full test suite after changes: `python -m pytest tests/unit/ -q`
