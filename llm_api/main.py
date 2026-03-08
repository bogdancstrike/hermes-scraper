"""
LLM Inference API — FastAPI application.

Exposes OpenAI-compatible-style endpoints for:
- CSS selector discovery
- Structured content extraction

Runs on GPU servers. Scraper nodes call this API.

Run with:
  uvicorn llm_api.main:app --host 0.0.0.0 --port 8000 --workers 4
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from llm_api.routers import selectors
from shared.logging import configure_logging, get_logger
from shared.metrics import start_metrics_server

configure_logging("llm_api")
logger = get_logger("llm_api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("llm_api_starting")
    metrics_port = int(os.getenv("METRICS_PORT", "9092"))
    start_metrics_server(metrics_port)
    yield
    logger.info("llm_api_stopping")


app = FastAPI(
    title="LLM Scraping Inference API",
    description="GPU-backed LLM service for CSS selector discovery",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration = time.monotonic() - start
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=int(duration * 1000),
    )
    return response


# Register routers
app.include_router(selectors.router, prefix="/v1", tags=["selectors"])


@app.get("/health")
async def health():
    """Health check endpoint for load balancers."""
    return {"status": "ok", "service": "llm_api"}


@app.get("/")
async def root():
    return {
        "service": "LLM Scraping Inference API",
        "version": "1.0.0",
        "endpoints": [
            "POST /v1/analyze-selectors",
            "GET /health",
        ],
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
