# LLM-Augmented Web Scraper (`llm-scraper`)

A self-improving, configuration-driven web scraping platform that extracts structured article content from any news or content website without requiring manual, site-specific CSS selectors.

## 🚀 Key Features

- **Zero Site-Specific Code**: Uses an LLM (Claude/Ollama) to discover CSS selectors (title, author, content, etc.) on first contact.
- **Smart Caching**: Discovered selectors are cached in PostgreSQL/Redis and reused, calling the LLM only when selectors fail or expire.
- **Dual-Engine Fetching**: Attempts lightweight static HTTP fetch first; falls back to full Playwright browser rendering only when blocked or needed.
- **Advanced Navigation**: Automatically discovers sections/categories from homepages and handles infinite scrolling.
- **Robust Extraction**: Merges metadata from multiple sources (JSON-LD, Trafilatura, Open Graph, Readability) using confidence scoring.
- **Domain Learning**: Remembers the best fetch strategy (Static vs. Browser) and anti-bot signals for every domain it visits.

## 🛠️ Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd llm-scraper
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Configure Environment**:
   Create a `.env` file in the root directory (see [Configuration](#-configuration) for details).

## 📖 Usage

Run the scraper using `app.py`:

```bash
# Basic usage
python3 app.py --website adevarul.ro

# Limit pages and articles
python3 app.py --website biziday.ro --pages 3 --articles 20

# Specify output directory
python3 app.py --website euronews.ro --output results/
```

### CLI Arguments
- `--website`, `-w`: Domain to scrape (required).
- `--pages`, `-p`: Max listing pages to traverse per section (default: 5).
- `--articles`, `-a`: Max articles to scrape in total (default: 100).
- `--output`, `-o`: Output directory (default: `output/`).

## ⚙️ Configuration

Key environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key for selector discovery | (Optional) |
| `POSTGRES_DSN` | PostgreSQL connection string | `postgresql://scraper:scraper@localhost:5432/scraperdb` |
| `REDIS_URL` | Redis for L1 selector cache | `redis://localhost:6379/0` |
| `SCRAPE_LIMIT` | Max articles per run | `100` |
| `HEADLESS` | Run browser in headless mode | `True` |
| `CAPTURE_SCREENSHOT` | Save full-page screenshots | `False` |

## 📂 Output

Scraped data is saved in the `output/{domain}/` directory:
- `{timestamp}.json`: Full article data including content and metadata.
- `{timestamp}.csv`: Summary of scraped articles.
- `screenshots/`: (If enabled) Full-page screenshots of articles.

## 🏗️ Project Structure

- `app.py`: Main entry point and CLI.
- `scraper/`: Core logic (engines, fetchers, navigation, selector discovery).
- `processing/`: Content extraction, filtering, and scoring.
- `shared/`: Database models, logging, and utilities.
- `docs/`: Detailed technical documentation.

---
For more detailed information, see [docs/Documentation.md](docs/Documentation.md).
