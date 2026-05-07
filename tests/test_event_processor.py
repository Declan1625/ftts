"""tests/test_event_processor.py — EventProcessor 통합 테스트"""

from unittest.mock import MagicMock, patch

import pytest

from core.event_processor import EventProcessor


class TestEventProcessor:
    @patch("core.event_processor.extract_events")
    @patch("core.event_processor.analyze_with_detail")
    @patch("core.event_processor.link_industries")
    @patch("core.event_processor.link_companies")
    def test_process_event_with_extracted_data(
        self,
        mock_link_companies,
        mock_link_industries,
        mock_analyze,
        mock_extract,
        session,
    ):
        processor = EventProcessor(session)

        # 모킹 설정
        from nlp.event_extractor import ExtractedEvent

        mock_event = ExtractedEvent(
            event_type="policy",
            summary="정부 반도체 지원 발표",
            affected_industries=["반도체"],
            affected_companies=["삼성전자"],
            sentiment=0.8,
            confidence=0.9,
        )
        mock_extract.return_value = [mock_event]
        mock_analyze.return_value = {"score": 0.8, "label": "positive", "reasoning": "호재"}
        mock_link_industries.return_value = {"반도체": None}
        mock_link_companies.return_value = {"삼성전자": None}

        result = processor.process_event("정부 반도체 지원", source_name="테스트")

        assert len(result["events"]) == 1
        assert result["sentiment"] == 0.8
        assert result["industry_edges"] == 0  # 엔티티 미매핑
        assert result["company_edges"] == 0

    @patch("core.event_processor.extract_events")
    def test_process_event_no_events(self, mock_extract, session):
        processor = EventProcessor(session)
        mock_extract.return_value = []

        result = processor.process_event("텍스트", source_name="테스트")

        assert result["events"] == []
        assert result["industry_edges"] == 0
        assert result["company_edges"] == 0

    def test_apply_industry_hierarchy_creates_edges(self, session):
        from database.models import Industry, Company

        # 테스트 데이터 생성
        industry = Industry(code="SEMI", name="반도체")
        session.add(industry)
        session.flush()

        company1 = Company(ticker="SSNLF", name="삼성전자", market="KOSPI", industry_id=industry.id)
        company2 = Company(ticker="SK000660", name="SK하이닉스", market="KOSPI", industry_id=industry.id)
        session.add_all([company1, company2])
        session.commit()

        processor = EventProcessor(session)
        edges = processor.apply_industry_hierarchy()

        assert edges == 2
        assert processor.graph.edge_count == 2
