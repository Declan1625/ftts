"""tests/test_api_server.py — FastAPI 서버 테스트"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("api.server.get_session"), \
         patch("api.server.EventProcessor"), \
         patch("api.server.WeightEngine"), \
         patch("api.server.CausalGraph"):
        from api.server import app
        return TestClient(app)


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_analyze_short_text(client):
    res = client.post("/analyze", json={"text": "짧음", "source_name": "test"})
    assert res.status_code == 400


def test_analyze_success():
    mock_session = MagicMock()
    mock_processor = MagicMock()
    mock_processor.process_event.return_value = {
        "events": [],
        "industry_edges": 0,
        "company_edges": 1,
        "sentiment": 0.5,
    }
    mock_processor.graph = MagicMock()
    mock_processor.sync_graph_to_db.return_value = 0

    mock_engine = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []

    with patch("api.server.get_session") as mock_get_session, \
         patch("api.server.EventProcessor", return_value=mock_processor), \
         patch("api.server.WeightEngine", return_value=mock_engine):

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        from api.server import app
        client = TestClient(app)

        res = client.post("/analyze", json={
            "text": "미국 연준이 기준금리를 0.25% 인상하기로 결정했다. 이는 인플레이션 억제를 위한 조치다.",
            "source_name": "Fed",
            "title": "FOMC 금리 결정",
        })

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["source_name"] == "Fed"
    assert "summary" in data
    assert "Fed" in data["summary"]


def test_discord_summary_has_sentiment():
    from api.server import _build_discord_summary
    summary = _build_discord_summary(
        title="테스트 제목",
        url="https://example.com",
        source_name="메르블로그",
        sentiment=0.7,
        signals=[],
        event_count=2,
    )
    assert "메르블로그" in summary
    assert "감성 점수" in summary
    assert "관망" in summary


def test_discord_summary_buy_signal():
    from api.server import _build_discord_summary, SignalResult
    signals = [
        SignalResult(ticker="005930", company_name="삼성전자", signal="BUY", score=0.75, confidence=0.9),
    ]
    summary = _build_discord_summary(
        title=None,
        url=None,
        source_name="DART",
        sentiment=-0.1,
        signals=signals,
        event_count=1,
    )
    assert "BUY" in summary
    assert "삼성전자" in summary
    assert "🟢" in summary
