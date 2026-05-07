"""tests/test_sentiment_analyzer.py"""

import json
from unittest.mock import MagicMock, patch

import pytest

from nlp.sentiment_analyzer import _parse, analyze, analyze_with_detail


class TestParse:
    def test_parses_valid_response(self):
        raw = json.dumps({"score": 0.8, "label": "positive", "reasoning": "호재"})
        result = _parse(raw)
        assert result["score"] == 0.8
        assert result["label"] == "positive"

    def test_clamps_score_above_1(self):
        raw = json.dumps({"score": 2.0, "label": "positive", "reasoning": ""})
        result = _parse(raw)
        assert result["score"] == 1.0

    def test_clamps_score_below_minus1(self):
        raw = json.dumps({"score": -3.0, "label": "negative", "reasoning": ""})
        result = _parse(raw)
        assert result["score"] == -1.0

    def test_returns_neutral_on_invalid_json(self):
        result = _parse("not json")
        assert result["score"] == 0.0
        assert result["label"] == "neutral"


class TestAnalyze:
    def _mock_claude_response(self, score: float):
        content = json.dumps({"score": score, "label": "positive", "reasoning": "테스트"})
        mock_message = MagicMock()
        mock_message.text = content
        mock_resp = MagicMock()
        mock_resp.content = [mock_message]
        return mock_resp

    @patch("nlp.sentiment_analyzer.Anthropic")
    def test_returns_float_score(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_claude_response(0.6)
        mock_anthropic_cls.return_value = mock_client

        result = analyze("금리 인하 발표")
        assert result == 0.6

    @patch("nlp.sentiment_analyzer.Anthropic")
    def test_retries_on_failure_and_returns_neutral(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = ConnectionError("API 오류")
        mock_anthropic_cls.return_value = mock_client

        result = analyze_with_detail("테스트")

        assert result["score"] == 0.0
        assert result["label"] == "neutral"

    @patch("nlp.sentiment_analyzer.Anthropic")
    def test_analyze_with_detail_has_all_keys(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_claude_response(-0.3)
        mock_anthropic_cls.return_value = mock_client

        result = analyze_with_detail("악재 뉴스")
        assert "score" in result
        assert "label" in result
        assert "reasoning" in result
