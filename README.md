<div align="center">

# 🕷️ Hermes — Intelligent Web Scraper

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
| **Batch mode** | GNU Parallel execution across 90+ sites with `docs/run_local.sh` |

## Quickstart (Docker)

```bash
# Clone and start
git clone git@github.com:bogdancstrike/hermes-scraper.git && cd hermes-scraper
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

## Batch Validation Report (2026-03-09)

Tested **99 sites** with `docs/run_local.sh` — 8 parallel jobs, `--pages 1 --articles 10`, 300s timeout per site.

**Summary: 57 ✓ SUCCESS · 30 ⏱ TIMEOUT · 12 ✗ FAILED**

### Romanian News — National

| Site | Status | Articles |
|------|--------|----------|
| adevarul.ro | ✓ SUCCESS | 10 |
| mediafax.ro | ✓ SUCCESS | 10 |
| gandul.ro | ✓ SUCCESS | 8 |
| evz.ro | ✓ SUCCESS | 10 |
| agerpres.ro | ✓ SUCCESS | 10 |
| observatornews.ro | ✓ SUCCESS | 10 |
| romaniatv.net | ✓ SUCCESS | 10 |
| realitatea.net | ✓ SUCCESS | 10 |
| b1tv.ro | ✓ SUCCESS | 10 |
| economica.net | ✓ SUCCESS | 10 |
| cursdeguvernare.ro | ✓ SUCCESS | 10 |
| news.ro | ✓ SUCCESS | 10 |
| g4media.ro | ✓ SUCCESS | 10 |
| capital.ro | ✓ SUCCESS | 10 |
| ziare.com | ✓ SUCCESS | 10 |
| euronews.ro | ✓ SUCCESS | 7 |
| gov.ro | ✓ SUCCESS | 4 |
| pressone.ro | ✓ SUCCESS | 10 |
| bizlawyer.ro | ✓ SUCCESS | 10 |
| wall-street.ro | ✓ SUCCESS | 3 |
| inpolitics.ro | ✓ SUCCESS | 4 |
| agrointel.ro | ✓ SUCCESS | 10 |
| stiripesurse.ro | ✓ SUCCESS | 10 |
| stirilekanald.ro | ✓ SUCCESS | 10 |
| kanald.ro | ✓ SUCCESS | 10 |
| curentul.info | ✓ SUCCESS | 10 |
| hotnews.ro | ⏱ TIMEOUT | — |
| stirileprotv.ro | ⏱ TIMEOUT | — |
| antena3.ro | ⏱ TIMEOUT | — |
| libertatea.ro | ⏱ TIMEOUT | — |
| jurnalul.ro | ⏱ TIMEOUT | — |
| profit.ro | ⏱ TIMEOUT | — |
| spotmedia.ro | ⏱ TIMEOUT | — |
| romania-insider.com | ⏱ TIMEOUT | — |
| forbes.ro | ⏱ TIMEOUT | — |
| dcnews.ro | ⏱ TIMEOUT | — |
| activenews.ro | ⏱ TIMEOUT | — |
| adevarulfinanciar.ro | ⏱ TIMEOUT | — |
| puterea.ro | ⏱ TIMEOUT | — |
| biziday.ro | ✗ FAILED | — (all URLs deduped from prior run) |
| romania.europalibera.org | ✗ FAILED | 0 (dedup / short titles) |
| digi24.ro | ✗ FAILED | 0 (live/ radio URLs as articles — fixed in code) |
| romaniajournal.ro | ✗ FAILED | 0 (LLM selector returns 0 matches) |
| stiri.tvr.ro | ✗ FAILED | 0 (Playwright browser timeout) |
| romanialibera.ro | ✗ FAILED | 0 |

### Romanian News — Regional

| Site | Status | Articles |
|------|--------|----------|
| ziarulunirea.ro | ✓ SUCCESS | 10 |
| ziaruldeiasi.ro | ✓ SUCCESS | 8 |
| banatulazi.ro | ✓ SUCCESS | 10 |
| brasov.net | ✓ SUCCESS | 10 |
| cluj24.ro | ✓ SUCCESS | 10 |
| timisplus.ro | ✓ SUCCESS | 10 |
| gds.ro | ✓ SUCCESS | 8 |
| ziarulargesul.ro | ✓ SUCCESS | 8 |
| observatorulph.ro | ✓ SUCCESS | 8 |
| mesagerulneamt.ro | ✓ SUCCESS | 10 |
| ziarulamprenta.ro | ✓ SUCCESS | 10 |
| botosaneanul.ro | ✓ SUCCESS | 10 |
| sibiu100.ro | ✓ SUCCESS | 9 |
| gorjeanul.ro | ✓ SUCCESS | 9 |
| oradesibiu.ro | ✓ SUCCESS | 10 |
| replicaonline.ro | ✓ SUCCESS | 10 |
| stiriagricole.ro | ✓ SUCCESS | 2 |
| gazetabt.ro | ✓ SUCCESS | 10 |
| gazetadambovitei.ro | ✓ SUCCESS | 10 |
| transilvaniareporter.ro | ✓ SUCCESS | 10 |
| stiridinbanat.ro | ✓ SUCCESS | 10 |
| aradon.ro | ✓ SUCCESS | 10 |
| actualdecluj.ro | ✓ SUCCESS | 10 |
| debanat.ro | ✓ SUCCESS | 10 |
| bihon.ro | ✓ SUCCESS | 10 |
| ziaruldevrancea.ro | ✓ SUCCESS | 3 |
| monitorulcj.ro | ⏱ TIMEOUT | — |
| monitorulsv.ro | ⏱ TIMEOUT | — |
| ziarullumina.ro | ⏱ TIMEOUT | — |
| telegrafonline.ro | ⏱ TIMEOUT | — |
| clujcapitala.ro | ⏱ TIMEOUT | — |
| mesagerul.ro | ✗ FAILED | 0 |
| sibiulindependent.ro | ✗ FAILED | 0 |
| adevaruldeseara.ro | ✗ FAILED | 0 |
| qmagazine.ro | ✗ FAILED | 0 |

### International

| Site | Status | Articles |
|------|--------|----------|
| bbc.co.uk | ✓ SUCCESS | 6 |
| axios.com | ✓ SUCCESS | 9 |
| wired.com | ✓ SUCCESS | 10 |
| techcrunch.com | ✓ SUCCESS | 10 |
| bloomberg.com | ✓ SUCCESS | 1 |
| theguardian.com | ⏱ TIMEOUT | — |
| ft.com | ⏱ TIMEOUT | — |
| economist.com | ⏱ TIMEOUT | — |
| apnews.com | ⏱ TIMEOUT | — |
| cnn.com | ⏱ TIMEOUT | — |
| nytimes.com | ⏱ TIMEOUT | — |
| politico.eu | ⏱ TIMEOUT | — |
| politico.com | ⏱ TIMEOUT | — |
| theatlantic.com | ⏱ TIMEOUT | — |
| theverge.com | ⏱ TIMEOUT | — |
| businessinsider.com | ⏱ TIMEOUT | — |
| forbes.com | ⏱ TIMEOUT | — |
| reuters.com | ✗ FAILED | 0 (JS-rendered / anti-bot) |
| washingtonpost.com | ✗ FAILED | 0 (paywall) |

> **Timeout note**: Most timeouts are Playwright-heavy sites needing JS rendering. Increase `HERMES_TIMEOUT` or use `--jobs 4` for resource-constrained environments. Many sites that timeout would succeed with a 600s budget.

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
