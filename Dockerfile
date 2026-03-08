# ── Hermes Scraper — Docker Image ─────────────────────────────────────────────
# Python 3.12 slim; installs Playwright Chromium with all OS-level dependencies.
FROM python:3.12-slim

# System packages needed by curl-cffi, Playwright, and lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl wget \
    # Playwright / Chromium runtime deps
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libglib2.0-0 libx11-6 libxext6 libxrender1 libxi6 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer-cached until requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (browser binary only, deps already installed above)
RUN playwright install chromium

# Copy application source
COPY app.py .
COPY scraper/   scraper/
COPY processing/ processing/
COPY llm_api/   llm_api/
COPY shared/    shared/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default: keep container alive so `docker compose exec` / `run.sh` can use it.
# Override with `docker compose run scraper python app.py --website ...`
CMD ["tail", "-f", "/dev/null"]
