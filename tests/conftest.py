"""
Shared test fixtures.
"""
import os
import pytest

# Set test environment variables before any imports
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test_scraperdb")
os.environ.setdefault("KAFKA_BROKERS", "localhost:9092")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:8000")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_FORMAT", "console")


@pytest.fixture
def sample_html():
    return """
    <html>
    <head><title>Test Article</title></head>
    <body>
      <nav><a href="/">Home</a></nav>
      <article>
        <h1>Test Article Headline</h1>
        <p class="author">By Test Author</p>
        <div class="content">
          <p>This is the first paragraph of a test article with substantial content about 
          technology and programming. Python is a great language for automation tasks.</p>
          <p>This is the second paragraph with more content about web scraping, data extraction,
          and the importance of respecting robots.txt files and rate limits.</p>
          <p>Final paragraph discussing LLM integration for intelligent content understanding 
          and structured data extraction at scale across many websites simultaneously.</p>
        </div>
      </article>
      <div class="comments">
        <div class="comment"><span class="user">alice</span><p>Great article!</p></div>
        <div class="comment"><span class="user">bob</span><p>Very informative.</p></div>
      </div>
      <script>tracking();</script>
    </body>
    </html>
    """


@pytest.fixture
def sample_domain():
    return "example.com"


@pytest.fixture
def sample_url():
    return "https://example.com/article/test"
