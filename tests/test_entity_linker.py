"""tests/test_entity_linker.py"""

from unittest.mock import MagicMock, patch

from nlp.entity_linker import (
    _clean,
    _similarity,
    link_companies,
    link_industries,
    normalize_ticker,
)


class TestNormalizeTicker:
    def test_kospi_zero_pads(self):
        assert normalize_ticker("5930", "KOSPI") == "005930"

    def test_kosdaq_zero_pads(self):
        assert normalize_ticker("35720", "KOSDAQ") == "035720"

    def test_nasdaq_uppercases(self):
        assert normalize_ticker("aapl", "NASDAQ") == "AAPL"

    def test_full_6digit_unchanged(self):
        assert normalize_ticker("005930", "KOSPI") == "005930"


class TestCleanAndSimilarity:
    def test_clean_removes_spaces(self):
        assert _clean("삼성 전자") == "삼성전자"

    def test_clean_removes_parentheses(self):
        assert _clean("삼성전자(주)") == "삼성전자주"

    def test_similarity_exact(self):
        assert _similarity("삼성전자", "삼성전자") == 1.0

    def test_similarity_partial(self):
        score = _similarity("삼성전자", "삼성")
        assert 0.0 < score < 1.0


class TestLinkCompanies:
    def _make_company(self, name, ticker):
        c = MagicMock()
        c.name = name
        c.ticker = ticker
        c.is_active = True
        return c

    def test_exact_match(self):
        session = MagicMock()
        samsung = self._make_company("삼성전자", "005930")
        session.query.return_value.filter.return_value.all.return_value = [samsung]

        result = link_companies(session, ["삼성전자"])
        assert result["삼성전자"] is samsung

    def test_no_match_returns_none(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        result = link_companies(session, ["존재하지않는회사XYZ123"])
        assert result["존재하지않는회사XYZ123"] is None

    def test_fuzzy_match(self):
        session = MagicMock()
        sk = self._make_company("SK하이닉스", "000660")
        session.query.return_value.filter.return_value.all.return_value = [sk]

        result = link_companies(session, ["SK 하이닉스"])
        assert result["SK 하이닉스"] is sk
