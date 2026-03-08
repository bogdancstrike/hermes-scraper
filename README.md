<div align="center">

# ⚡ Hermes — Intelligent Web Scraper

**Self-discovering, zero-config news scraper powered by LLMs and Playwright.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Playwright](https://img.shields.io/badge/Playwright-1.44-45BA4B?logo=playwright&logoColor=white)](https://playwright.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![Ollama](https://img.shields.io/badge/Ollama-LLM-black?logo=ollama&logoColor=white)](https://ollama.ai)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*No site-specific configuration. No manual CSS selectors. Just point at a domain and scrape.*

</div>

---

## What is Hermes?

Hermes scrapes structured article content from any news or content website — without requiring you to write a single line of site-specific code. On first contact with a new domain, it uses a local LLM to discover the right CSS selectors automatically. Those selectors are cached and reused on subsequent runs, with live validation that detects silent site redesigns.

## How it works

```
Homepage → discover sections → collect article URLs → fetch & extract → persist to DB
              (nav menus)        (CSS selectors         (Playwright +      (PostgreSQL +
                                  + LLM discovery)       trafilatura)        NDJSON)
```

1. **Section discovery** — renders the homepage with Playwright, extracts category/section links from nav menus
2. **Selector discovery** — sends a compact DOM snapshot to the LLM; result cached in Redis (1h) → PostgreSQL (30d)
3. **Article collection** — follows pagination and infinite scroll across all sections
4. **Extraction** — merges metadata from JSON-LD, Open Graph, htmldate, trafilatura, and readability by confidence score
5. **Persistence** — saves to PostgreSQL immediately; idempotent (deduplicates across runs)

## Key Features

| Feature | Details |
|---------|---------|
| **Zero config** | LLM discovers CSS selectors on first run per domain |
| **3-layer selector cache** | Redis (1h) → PostgreSQL (30d) → LLM on miss/failure |
| **Dual-engine fetch** | Static (`curl-cffi` Chrome124 TLS) → Playwright fallback |
| **Heuristic fallback** | When LLM selector fails, falls back to text-length heuristics |
| **Infinite scroll** | Auto-scrolls listing pages to load dynamic content |
| **Domain memory** | Learns best fetch strategy per domain across runs |
| **Anti-bot evasion** | Stealth Playwright, randomised UA, GDPR overlay dismissal |
| **Quality scoring** | Detects paywalled and liveblog content |
| **Validated on 11 sites** | Romanian news sites across different tech stacks |

## Quickstart (Docker)

```bash
# Clone and start
git clone <repo-url> && cd hermes
docker compose up -d --build

# Scrape a site
docker compose exec scraper python app.py --website biziday.ro --pages 3 --articles 50

# Or run all configured sites at once
./docs/run.sh
```

> **Note:** On first start, Ollama downloads `qwen2.5-coder:7b` (~4.5 GB). This only happens once.

## Quickstart (local)

```bash
# Prerequisites: Python 3.12, PostgreSQL, Redis, Ollama with qwen2.5-coder:7b
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium

cp .env.example .env  # edit connection strings if needed
python3 app.py --website adevarul.ro --pages 2 --articles 20
```

## CLI Reference

```bash
python3 app.py --website <domain> [--pages N] [--articles N] [--output DIR]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--website` / `-w` | required | Domain to scrape (e.g. `adevarul.ro`) |
| `--pages` / `-p` | `5` | Max listing pages per section |
| `--articles` / `-a` | `100` | Max total articles to scrape |
| `--output` / `-o` | `output/` | Output directory |

## Output

Results are written to `output/{domain}/`:

```
output/adevarul.ro/
├── 20260308_221500.json   # full article data (ArticleRecord)
├── 20260308_221500.csv    # summary table
└── screenshots/           # (if CAPTURE_SCREENSHOT=True)
```

Each article includes: `url`, `title`, `author`, `published_date`, `content`, `language`, `word_count`, quality scores, and extraction provenance.

## Configuration

Key `.env` variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama or OpenAI-compatible endpoint |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Model for selector discovery |
| `POSTGRES_DSN` | `postgresql://scraper:scraper@localhost:5432/scraperdb` | Database |
| `REDIS_URL` | `redis://localhost:6379/0` | L1 selector cache |
| `SCRAPE_LIMIT` | `100` | Max articles per run |
| `HEADLESS` | `True` | Playwright headless mode |
| `MIN_TITLE_LENGTH` | `20` | Quality gate: skip short-title pages |
| `CAPTURE_SCREENSHOT` | `False` | Save full-page screenshots |
| `EXTRACT_EMAILS` | `False` | Extract emails from content |

## Architecture

```
app.py (CLI)
├── SiteNavigator          — section discovery, pagination, infinite scroll
│   └── Paginator          — per-section URL collection + next-page following
├── SelectorClient         — Redis → PG → LLM selector cache
├── BrowserEngine          — Playwright (stealth, overlays, scroll)
├── StaticFetcher          — curl-cffi Chrome124 TLS fingerprint
├── ArticleExtractor       — JSON-LD + OG + htmldate + trafilatura + readability
└── ArticleStore           — idempotent PostgreSQL persistence + NDJSON fallback
```

## Validated Sites

| Site | Status | Notes |
|------|--------|-------|
| biziday.ro | ✓ | Static fetch, ~200ms |
| hotnews.ro | ✓ | |
| adevarul.ro | ✓ | |
| stirileprotv.ro | ✓ | |
| digi24.ro | ✓ | |
| euronews.ro | ✓ | |
| mediafax.ro | ✓ | Heuristic fallback |
| gandul.ro | ✓ | Heuristic fallback |
| romania.europalibera.org | ✓ | |
| antena3.ro | ⚠ | Partial |
| gov.ro | ⚠ | Partial |

## Tech Stack

- **Python 3.12** · asyncio, Pydantic v2, asyncpg
- **Playwright** — headless Chromium with stealth patches
- **curl-cffi** — Chrome124 TLS fingerprint for static fetches
- **trafilatura + readability** — main content extraction
- **Ollama / Claude / OpenAI** — LLM backend (pluggable)
- **PostgreSQL** — article storage + selector cache
- **Redis** — hot selector cache (L1)
- **structlog** — structured logging
- **Docker Compose** — one-command local stack

---

<div align="center">

**[Documentation](docs/Documentation.md)** · **[Architecture](docs/C4_Architecture.md)** · **[Flows](docs/Flows.md)**

</div>
