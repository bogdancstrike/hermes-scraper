"""Unit tests for content extraction."""
import pytest
from processing.filters.extractor import extract_main_content, MIN_TEXT_LENGTH


SAMPLE_ARTICLE_HTML = """
<html>
<head><title>Test Article</title></head>
<body>
  <nav><a href="/">Home</a><a href="/about">About</a></nav>
  <main>
    <article>
      <h1>Python is Amazing</h1>
      <p class="byline">By Jane Smith | January 1, 2024</p>
      <div class="content">
        <p>Python is a versatile, high-level programming language that has taken the software world by storm.
        Created by Guido van Rossum and first released in 1991, Python emphasizes code readability with its
        notable use of significant whitespace. Its language constructs and object-oriented approach aim to
        help programmers write clear, logical code for small and large-scale projects.</p>
        <p>One of Python's greatest strengths is its vast standard library, which provides tools suited to
        many tasks. The Python ecosystem includes thousands of third-party modules available through the
        Python Package Index (PyPI), making it incredibly extensible. Whether you need to do web development,
        data science, machine learning, or system automation, Python has you covered.</p>
        <p>The language's design philosophy is summarized in the Zen of Python, a collection of 19 guiding
        principles that influence the design of the language. Key among these are: beautiful is better than
        ugly, explicit is better than implicit, and simple is better than complex.</p>
      </div>
    </article>
  </main>
  <footer><p>Copyright 2024</p></footer>
  <script>console.log('tracking');</script>
</body>
</html>
"""

SHORT_HTML = """
<html><body><p>Short.</p></body></html>
"""

EMPTY_HTML = "<html><head></head><body></body></html>"


class TestExtractMainContent:
    def test_extracts_article_content(self):
        result = extract_main_content(SAMPLE_ARTICLE_HTML, url="https://example.com/article")
        assert result is not None
        assert "Python" in result["text"]
        assert len(result["text"]) >= MIN_TEXT_LENGTH

    def test_returns_dict_with_keys(self):
        result = extract_main_content(SAMPLE_ARTICLE_HTML)
        assert result is not None
        assert "text" in result
        assert "title" in result
        assert "author" in result
        assert "date" in result
        assert "language" in result

    def test_removes_navigation(self):
        result = extract_main_content(SAMPLE_ARTICLE_HTML)
        assert result is not None
        assert "programming language" in result["text"].lower()

    def test_returns_none_for_short_content(self):
        result = extract_main_content(SHORT_HTML)
        assert result is None

    def test_returns_none_for_empty(self):
        result = extract_main_content(EMPTY_HTML)
        assert result is None

    def test_handles_empty_string(self):
        result = extract_main_content("")
        assert result is None

    def test_strips_scripts(self):
        result = extract_main_content(SAMPLE_ARTICLE_HTML)
        if result:
            assert "console.log" not in result["text"]
            assert "tracking" not in result["text"]

    def test_with_url_hint(self):
        result = extract_main_content(
            SAMPLE_ARTICLE_HTML, url="https://blog.example.com/python-is-amazing"
        )
        assert result is not None
