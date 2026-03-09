# Hermes — TODO / Session Log

## Session: 2026-03-08 → 2026-03-09

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
- [x] `shared/models.py` — renamed `model_used` → `llm_model`; added `model_config = {"protected_namespaces": ()}`; fixed deprecated `datetime.utcnow()` → `_utcnow()` helper
- [x] `processing/enrichers/screenshot.py` — fixed `datetime.utcnow()` → `datetime.now(timezone.utc)`
- [x] `paginator.py` — heuristic fallback when LLM selector returns 0 matches (critical fix for mediafax.ro, gandul.ro)
- [x] `paginator.py` — added `/live/`, `/emisiuni`, `/video/`, `/galerie`, `/foto/`, `/podcast` to `_SECTION_SKIP` (fix for digi24.ro visiting radio streams as sections)
- [x] `paginator.py` — `_is_article_url`: 1-segment paths require a digit (article IDs like biziday.ro `/456748932-slug`)
- [x] `paginator.py` — `_is_article_url`: added `/live/`, `/video/`, `/foto/`, `/galerie/`, `/podcast/`, `/emisiuni/`, `/cdn-cgi/` to article URL skip list (fix for digi24.ro collecting live/ URLs as articles)

#### Deleted (dead distributed-mode code)
- [x] `shared/kafka.py`, `processing/main.py`, `processing/pipeline.py`
- [x] `llm_api/main.py`, `llm_api/routers/`
- [x] `scraper/main.py`, `scraper/storage/`, `scraper/anti_bot/`, `scraper/engines/http_engine.py`
- [x] `scheduler/`, `docker/`, `scripts/` directories

#### Documentation & Validation
- [x] Created `docs/Documentation.md`, `docs/C4_Architecture.md`, `docs/Flows.md`
- [x] Created/improved `docs/run_local.sh` — batch parallel runner for 99 sites (8 jobs, 300s timeout)
- [x] Updated `docs/run.sh` with all validated sites
- [x] Updated `README.md` with GitHub badges, validated sites table (99 sites batch report)
- [x] Updated `CLAUDE.md` with current architecture, known issues
- [x] Updated `memory/MEMORY.md` with project state

### Batch Run Results (2026-03-09, `docs/run_local.sh`)

**99 sites tested** — `--pages 1 --articles 10`, 300s timeout, 8 parallel jobs

| Result | Count | Sites |
|--------|-------|-------|
| ✓ SUCCESS | 57 | See README.md validated table |
| ⏱ TIMEOUT | 30 | Playwright-heavy or slow sites; increase HERMES_TIMEOUT |
| ✗ FAILED | 12 | See below |

#### FAILED root causes

| Site | Root Cause |
|------|------------|
| biziday.ro | All URLs already in DB dedup table (not a real failure) |
| romania.europalibera.org | All URLs deduped or `article_title_too_short` title gate |
| digi24.ro | `/live/` URLs collected as articles — fixed in code, will work next run |
| romaniajournal.ro | LLM selector returns 0 matches, heuristic also 0 (JS-only homepage?) |
| stiri.tvr.ro | Playwright timeout (45s) on section homepage load |
| qmagazine.ro | Needs investigation |
| mesagerul.ro | Needs investigation |
| sibiulindependent.ro | Needs investigation |
| adevaruldeseara.ro | Needs investigation |
| romanialibera.ro | Needs investigation |
| reuters.com | JS-rendered / anti-bot blocks |
| washingtonpost.com | Paywall blocks content |

#### TIMEOUT root causes

Most timeouts are caused by:
1. Playwright rendering large JS-heavy homepages (300s too tight)
2. LLM selector discovery taking long per section
3. Sites with many sections × slow navigation

Solution: increase `HERMES_TIMEOUT` to 600s, or reduce `--pages` / `--articles` for batch runs.

### Remaining / Next Session

#### Immediate Bugs to Fix
- [ ] **digi24.ro** — re-test after `_is_article_url` fix (already applied to code)
- [ ] **biziday.ro dedup false-fail** — when `all_urls_already_scraped`, app exits with code 1; should exit 0 or add `--force` flag to re-scrape
- [ ] **romaniajournal.ro / stiri.tvr.ro** — investigate JS-only sites that return 0 URLs even with heuristic fallback
- [ ] **qmagazine.ro / mesagerul.ro / sibiulindependent.ro / adevaruldeseara.ro** — check logs, identify root cause
- [ ] **Romanian utility page patterns** — add `/politica-de-cookies`, `/termeni-si-conditii`, `/politica-de-confidentialitate` to both `_SECTION_SKIP` and `_is_article_url` skip list

#### LLM Quality
- [ ] Consider upgrading from `qwen2.5-coder:7b` to:
  - `qwen2.5-coder:14b` (better, needs ~8GB VRAM, use `HERMES_TIMEOUT` increase)
  - `claude-haiku-4-5` via Anthropic API (fastest, best accuracy, pay-per-use)
  - `gpt-4o-mini` via OpenAI API (cheap, fast, reliable)
- [ ] The 7B model frequently generates wrong selectors (e.g. `.post-title a` matches nothing); larger model would reduce LLM retries significantly

#### Testing
- [ ] Run full test suite after `_is_article_url` fix: `python -m pytest tests/unit/ -q`
- [ ] Add unit tests for: heuristic fallback, new `_is_article_url` media skips, `_SECTION_SKIP` patterns
- [ ] Full Docker test via `docs/run.sh` for all sites

#### Infrastructure
- [ ] Increase batch timeout from 300s to 600s in `docs/run_local.sh` for second run
- [ ] Test TIMEOUT sites with longer budget individually to confirm they work
- [ ] Docker Compose: verify Ollama model auto-pull works end-to-end on fresh machine
