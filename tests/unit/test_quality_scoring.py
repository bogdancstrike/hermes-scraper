"""Tests for quality scoring and field merge."""
from processing.scoring.quality import compute_quality
from processing.scoring.merge import pick_field, merge_fields


# ── Quality scoring ────────────────────────────────────────────────────────────

def test_perfect_article_scores_high():
    content = " ".join(["word"] * 700)
    result = compute_quality("Great Title", content, "2026-01-01", "Jane Doe")
    assert result["overall_score"] >= 0.9
    assert result["title_score"] == 1.0
    assert result["date_score"] == 1.0
    assert result["author_score"] == 1.0


def test_missing_author_lowers_score():
    content = " ".join(["word"] * 700)
    with_author = compute_quality("Title", content, "2026-01-01", "Author")
    without_author = compute_quality("Title", content, "2026-01-01", None)
    assert with_author["overall_score"] > without_author["overall_score"]


def test_short_content_low_content_score():
    result = compute_quality("Title", "short text", "2026-01-01", "Author")
    assert result["content_score"] < 0.1


def test_paywall_detection():
    result = compute_quality("Article", "Subscribe to continue reading this premium content", None, None)
    assert result["likely_paywalled"] is True


def test_liveblog_detection():
    result = compute_quality("LIVE: War updates", "Follow live updates as they happen", None, None)
    assert result["likely_liveblog"] is True


def test_reading_time_minimum_one():
    result = compute_quality("Title", "just a few words", None, None)
    assert result["reading_time_minutes"] >= 1


def test_word_count_accurate():
    content = "one two three four five"
    result = compute_quality("T", content, None, None)
    assert result["word_count"] == 5


# ── Field merge ────────────────────────────────────────────────────────────────

def test_pick_field_prefers_jsonld():
    sources = {
        "jsonld": {"title": "JSON-LD Title"},
        "trafilatura": {"title": "Traf Title"},
        "og": {"title": "OG Title"},
    }
    value, source, conf = pick_field("title", sources)
    assert value == "JSON-LD Title"
    assert source == "jsonld"
    assert conf == 0.98


def test_pick_field_falls_back():
    sources = {
        "jsonld": {"title": None},
        "trafilatura": {"title": "Traf Title"},
    }
    value, source, conf = pick_field("title", sources)
    assert value == "Traf Title"
    assert source == "trafilatura"


def test_pick_field_returns_none_if_all_empty():
    sources = {"jsonld": {"title": None}, "trafilatura": {"title": ""}}
    value, source, conf = pick_field("title", sources)
    assert value is None


def test_merge_fields_returns_three_dicts():
    sources = {
        "jsonld": {"title": "T", "author": "A", "date": "2026-01-01", "content": None},
        "trafilatura": {"content": "Long article content here"},
    }
    merged, fsources, fconf = merge_fields(sources)
    assert merged["title"] == "T"
    assert merged["content"] == "Long article content here"
    assert fsources["title"] == "jsonld"
    assert fsources["content"] == "trafilatura"
