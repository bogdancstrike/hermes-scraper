"""Unit tests for LLM client JSON parsing."""
import pytest
from llm_api.llm_client import LLMClient


class TestParseJsonResponse:
    def test_clean_json(self):
        text = '{"title": "Hello", "author": "Alice"}'
        result = LLMClient.parse_json_response(text)
        assert result["title"] == "Hello"
        assert result["author"] == "Alice"

    def test_json_in_code_block(self):
        text = '```json\n{"title": "Hello"}\n```'
        result = LLMClient.parse_json_response(text)
        assert result["title"] == "Hello"

    def test_json_with_preamble(self):
        text = 'Here is the JSON:\n{"title": "Test"}'
        result = LLMClient.parse_json_response(text)
        assert result["title"] == "Test"

    def test_json_with_code_block_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        result = LLMClient.parse_json_response(text)
        assert result["key"] == "value"

    def test_invalid_json_returns_empty(self):
        text = "This is not JSON at all"
        result = LLMClient.parse_json_response(text)
        assert result == {}

    def test_nested_json(self):
        text = '{"entities": ["Apple", "Google"], "sentiment": "positive"}'
        result = LLMClient.parse_json_response(text)
        assert result["entities"] == ["Apple", "Google"]
        assert result["sentiment"] == "positive"

    def test_json_with_nulls(self):
        text = '{"title": null, "author": null}'
        result = LLMClient.parse_json_response(text)
        assert result["title"] is None
