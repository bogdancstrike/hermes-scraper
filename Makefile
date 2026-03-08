.PHONY: help infra-up infra-down db-setup dev test test-int test-cov lint format clean build

PYTHON := python3
PIP := pip3
COMPOSE := docker compose -f docker/docker-compose.yml

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Infrastructure ────────────────────────────────────────────
infra-up: ## Start all infrastructure services (Kafka, Postgres, ES, MinIO, Redis)
	$(COMPOSE) up -d kafka postgres elasticsearch minio redis kafka-ui
	@echo "⏳ Waiting for services to be ready..."
	@sleep 10
	@echo "✅ Infrastructure ready"

infra-down: ## Stop all infrastructure services
	$(COMPOSE) down

infra-clean: ## Stop and remove all volumes
	$(COMPOSE) down -v --remove-orphans

# ── Database ──────────────────────────────────────────────────
db-setup: ## Run migrations and seed initial data
	$(PYTHON) scripts/db_migrate.py
	$(PYTHON) scripts/seed_sites.py
	@echo "✅ Database ready"

db-migrate: ## Run Alembic migrations only
	alembic upgrade head

db-rollback: ## Rollback last migration
	alembic downgrade -1

# ── Development ───────────────────────────────────────────────
dev: ## Start all application services in development mode
	$(COMPOSE) up scraper processing llm_api scheduler

dev-scraper: ## Start only the scraper node
	$(PYTHON) -m scraper.main

dev-processing: ## Start only the processing service
	$(PYTHON) -m processing.main

dev-llm: ## Start only the LLM API service
	uvicorn llm_api.main:app --reload --host 0.0.0.0 --port 8000

dev-scheduler: ## Start only the scheduler
	$(PYTHON) -m scheduler.main

# ── Testing ───────────────────────────────────────────────────
test: ## Run unit tests
	pytest tests/unit/ -v

test-int: ## Run integration tests (requires running infra)
	pytest tests/integration/ -v --timeout=60

test-cov: ## Run tests with coverage report
	pytest tests/ --cov=. --cov-report=html --cov-report=term-missing

# ── Code Quality ──────────────────────────────────────────────
lint: ## Run ruff linter
	ruff check .

format: ## Format code with ruff
	ruff format .

typecheck: ## Run mypy type checking
	mypy scraper/ processing/ llm_api/ scheduler/ shared/

# ── Docker ────────────────────────────────────────────────────
build: ## Build all Docker images
	docker build -f docker/Dockerfile.scraper -t llm-scraper/scraper:latest .
	docker build -f docker/Dockerfile.processing -t llm-scraper/processing:latest .
	docker build -f docker/Dockerfile.llm_api -t llm-scraper/llm_api:latest .
	docker build -f docker/Dockerfile.scheduler -t llm-scraper/scheduler:latest .

# ── Utilities ─────────────────────────────────────────────────
smoke-test: ## Quick end-to-end smoke test
	$(PYTHON) scripts/test_scraper.py --url https://news.ycombinator.com --pages 2

scrape-ro: ## Scrape biziday.ro and adevarul.ro on-demand (requires ANTHROPIC_API_KEY in .env)
	$(PYTHON) scripts/scrape_sites.py --sites biziday adevarul

scrape-ro-fast: ## Scrape biziday.ro and adevarul.ro without LLM (no API key needed)
	$(PYTHON) scripts/scrape_sites.py --sites biziday adevarul --no-llm

scrape-biziday: ## Scrape only biziday.ro
	$(PYTHON) scripts/scrape_sites.py --sites biziday

scrape-adevarul: ## Scrape only adevarul.ro
	$(PYTHON) scripts/scrape_sites.py --sites adevarul

benchmark: ## Run throughput benchmark
	$(PYTHON) scripts/benchmark.py

install: ## Install Python dependencies
	$(PIP) install -r requirements-dev.txt
	playwright install chromium

install-playwright: ## Install Playwright browsers
	playwright install chromium --with-deps

clean: ## Remove Python cache files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache/ htmlcov/ .coverage
