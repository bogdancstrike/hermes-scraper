"""Tests for URL canonicalization utilities."""
from shared.url_utils import canonicalize_url, extract_domain


def test_strips_utm_params():
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=123"
    result = canonicalize_url(url)
    assert "utm_source" not in result
    assert "utm_medium" not in result
    assert "id=123" in result


def test_strips_fbclid():
    url = "https://example.com/article?fbclid=IwAR123abc"
    result = canonicalize_url(url)
    assert "fbclid" not in result
    assert result == "https://example.com/article"


def test_strips_gclid():
    url = "https://example.com/article?gclid=abc&page=2"
    result = canonicalize_url(url)
    assert "gclid" not in result
    assert "page=2" in result


def test_preserves_meaningful_params():
    url = "https://example.com/search?q=python&page=2"
    result = canonicalize_url(url)
    assert "q=python" in result
    assert "page=2" in result


def test_strips_fragment():
    url = "https://example.com/article#section-3"
    result = canonicalize_url(url)
    assert "#" not in result


def test_trailing_slash_normalized():
    url1 = "https://example.com/article/"
    url2 = "https://example.com/article"
    assert canonicalize_url(url1) == canonicalize_url(url2)


def test_empty_url():
    assert canonicalize_url("") == ""


def test_extract_domain_strips_www():
    assert extract_domain("https://www.adevarul.ro/article") == "adevarul.ro"


def test_extract_domain_no_www():
    assert extract_domain("https://biziday.ro/article") == "biziday.ro"


def test_extract_domain_empty():
    assert extract_domain("") == ""
