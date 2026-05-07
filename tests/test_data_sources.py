"""tests/test_data_sources.py — P1 정보원 확장 통합 테스트"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from data_collection import dart_crawler, fed_crawler, sec_crawler, trump_scraper
from data_collection.source_manager import SourceManager
from database.models import Source


class TestDartCrawler:
    def test_fetch_recent_disclosures_returns_list(self):
        with patch("data_collection.dart_crawler.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "status": "000",
                "list": [
                    {
                        "crp_cd": "005930",
                        "report_nm": "반기보고서",
                        "disclosure_date": "2025-05-07",
                    }
                ],
            }
            mock_get.return_value = mock_resp

            result = dart_crawler.fetch_recent_disclosures(days_back=7)
            assert isinstance(result, list)

    def test_get_company_code_returns_code(self):
        with patch("data_collection.dart_crawler.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "status": "000",
                "list": [{"corp_code": "005930"}],
            }
            mock_get.return_value = mock_resp

            code = dart_crawler.get_company_code("삼성전자")
            assert code == "005930"


class TestFedCrawler:
    def test_fetch_recent_speeches_returns_list(self):
        with patch("data_collection.fed_crawler.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.content = b"<html></html>"
            mock_get.return_value = mock_resp

            result = fed_crawler.fetch_recent_speeches(days_back=30)
            assert isinstance(result, list)

    def test_fetch_fomc_minutes_returns_list(self):
        with patch("data_collection.fed_crawler.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.content = b"<html></html>"
            mock_get.return_value = mock_resp

            result = fed_crawler.fetch_fomc_minutes()
            assert isinstance(result, list)


class TestSecCrawler:
    def test_fetch_company_filings_returns_list(self):
        with patch("data_collection.sec_crawler.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "filings": {
                    "recent": {
                        "form": ["10-K", "10-Q"],
                        "accessionNumber": ["0001234567-25-000001", "0001234567-25-000002"],
                        "filingDate": ["2025-05-07", "2025-04-07"],
                    }
                }
            }
            mock_get.return_value = mock_resp

            result = sec_crawler.fetch_company_filings("AAPL", days_back=30)
            assert isinstance(result, list)


class TestTrumpScraper:
    def test_fetch_trump_posts_returns_list(self):
        with patch("data_collection.trump_scraper.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.text = "<html></html>"
            mock_get.return_value = mock_resp

            result = trump_scraper.fetch_trump_posts(days_back=7)
            assert isinstance(result, list)


class TestSourceManager:
    def test_ensure_sources_creates_all_sources(self, session):
        manager = SourceManager(session)

        sources = session.query(Source).all()
        assert len(sources) >= 6

        names = {s.name for s in sources}
        assert "메르 블로그" in names
        assert "DART 공시" in names
        assert "Fed 발표" in names

    def test_get_source_id_returns_id(self, session):
        manager = SourceManager(session)
        source_id = manager._get_source_id("메르 블로그")
        assert isinstance(source_id, int)
        assert source_id > 0

    def test_get_source_id_caching(self, session):
        manager = SourceManager(session)
        id1 = manager._get_source_id("메르 블로그")
        id2 = manager._get_source_id("메르 블로그")
        assert id1 == id2
