"""tests/test_event_extractor.py"""

import json
from unittest.mock import MagicMock, patch

import pytest

from nlp.event_extractor import ExtractedEvent, _parse_response, extract_events


class TestParseResponse:
    def test_parses_list_format(self):
        raw = json.dumps([
            {"event_type": "rate", "summary": "금리 인하",
             "affected_industries": ["금융"], "affected_companies": [],
             "sentiment": 0.7, "confidence": 0.9}
        ])
        result = _parse_response(raw)
        assert len(result) == 1
        assert result[0].event_type == "rate"
        assert result[0].sentiment == 0.7

    def test_parses_events_key_format(self):
        raw = json.dumps({"events": [
            {"event_type": "macro", "summary": "GDP 성장",
             "affected_industries": [], "affected_companies": [],
             "sentiment": 0.5, "confidence": 0.8}
        ]})
        result = _parse_response(raw)
        assert len(result) == 1

    def test_returns_empty_on_invalid_json(self):
        result = _parse_response("not json")
        assert result == []

    def test_returns_empty_on_empty_array(self):
        result = _parse_response("[]")
        assert result == []

    def test_clamps_sentiment(self):
        raw = json.dumps([
            {"event_type": "other", "summary": "x",
             "affected_industries": [], "affected_companies": [],
             "sentiment": 99.0, "confidence": 0.5}
        ])
        result = _parse_response(raw)
        assert result[0].sentiment == 99.0


class TestExtractEvents:
    def _mock_claude_response(self, content: str):
        mock_message = MagicMock()
        mock_message.text = content
        mock_response = MagicMock()
        mock_response.content = [mock_message]
        return mock_response

    @patch("nlp.event_extractor.Anthropic")
    def test_returns_extracted_events(self, mock_anthropic_cls):
        content = json.dumps([{
            "event_type": "policy", "summary": "정부 반도체 지원",
            "affected_industries": ["반도체"], "affected_companies": ["삼성전자"],
            "sentiment": 0.8, "confidence": 0.9
        }])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_claude_response(content)
        mock_anthropic_cls.return_value = mock_client

        result = extract_events("반도체 지원 정책 발표", "테스트")

        assert len(result) == 1
        assert isinstance(result[0], ExtractedEvent)
        assert result[0].event_type == "policy"

    @patch("nlp.event_extractor.Anthropic")
    def test_raises_after_max_retries(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = ConnectionError("API 오류")
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="이벤트 추출 실패"):
            extract_events("테스트 텍스트")
