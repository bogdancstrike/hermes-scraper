"""Tests for anti-bot block detection."""
from scraper.detectors.anti_bot import detect_block_signals, is_blocked


def test_detects_cloudflare_html():
    html = "<html><body>Checking your browser before accessing...</body></html>"
    signals = detect_block_signals(html)
    assert "cloudflare" in signals


def test_detects_http_403():
    signals = detect_block_signals("", status_code=403)
    assert "http_403" in signals


def test_detects_http_429():
    signals = detect_block_signals("", status_code=429)
    assert "http_429" in signals


def test_detects_captcha():
    html = "<html><body>Please complete the reCAPTCHA to continue</body></html>"
    signals = detect_block_signals(html)
    assert "captcha" in signals


def test_detects_datadome_header():
    signals = detect_block_signals("", headers={"x-datadome": "1"})
    assert "datadome" in signals


def test_clean_page_no_signals():
    html = "<html><body><article>This is a real article about Python.</article></body></html>"
    signals = detect_block_signals(html, status_code=200)
    assert signals == []


def test_is_blocked_cloudflare():
    assert is_blocked(["cloudflare"]) is True


def test_is_blocked_paywall_not_hard_block():
    assert is_blocked(["paywall_block"]) is False


def test_is_blocked_empty():
    assert is_blocked([]) is False
