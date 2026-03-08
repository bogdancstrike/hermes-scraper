"""Unit tests for user-agent rotator."""
import pytest
from scraper.anti_bot.ua_rotator import next_ua, USER_AGENTS


def test_returns_string():
    ua = next_ua()
    assert isinstance(ua, str)
    assert len(ua) > 20


def test_returns_known_ua():
    ua = next_ua()
    assert ua in USER_AGENTS


def test_randomness():
    """Should not always return the same UA (with high probability)."""
    uas = {next_ua() for _ in range(20)}
    assert len(uas) > 1  # At least 2 different UAs in 20 tries


def test_contains_mozilla():
    """All real browser UAs start with Mozilla."""
    for _ in range(10):
        ua = next_ua()
        assert ua.startswith("Mozilla/")
