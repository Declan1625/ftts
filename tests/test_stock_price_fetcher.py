"""tests/test_stock_price_fetcher.py"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_collection.stock_price_fetcher import (
    _to_yfinance_ticker,
    fetch_prices,
    get_latest_price,
)


class TestToYfinanceTicker:
    def test_kospi_appends_ks(self):
        assert _to_yfinance_ticker("005930", "KOSPI") == "005930.KS"

    def test_kosdaq_appends_kq(self):
        assert _to_yfinance_ticker("035720", "KOSDAQ") == "035720.KQ"

    def test_nasdaq_unchanged(self):
        assert _to_yfinance_ticker("AAPL", "NASDAQ") == "AAPL"

    def test_nyse_unchanged(self):
        assert _to_yfinance_ticker("BRK-A", "NYSE") == "BRK-A"


class TestFetchPrices:
    def _make_company(self, ticker="005930", market="KOSPI"):
        company = MagicMock()
        company.id = 1
        company.ticker = ticker
        company.market = market
        return company

    def _make_ohlcv_df(self):
        idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
        return pd.DataFrame(
            {"Open": [70000.0, 71000.0], "High": [72000.0, 73000.0],
             "Low": [69000.0, 70000.0], "Close": [71000.0, 72000.0],
             "Volume": [1000000, 1200000]},
            index=idx,
        )

    @patch("data_collection.stock_price_fetcher._upsert_prices")
    @patch("data_collection.stock_price_fetcher.yf.Ticker")
    def test_returns_stock_price_list(self, mock_ticker_cls, mock_upsert):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._make_ohlcv_df()
        mock_ticker_cls.return_value = mock_ticker

        session = MagicMock()
        company = self._make_company()
        result = fetch_prices(session, company, date(2024, 1, 1))

        assert len(result) == 2
        assert result[0].close == 71000.0
        mock_upsert.assert_called_once()

    @patch("data_collection.stock_price_fetcher.yf.Ticker")
    def test_raises_after_max_retries(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = ConnectionError("timeout")
        mock_ticker_cls.return_value = mock_ticker

        with patch("data_collection.stock_price_fetcher.time.sleep"):
            with pytest.raises(RuntimeError, match="주가 수집 실패"):
                fetch_prices(MagicMock(), self._make_company(), date(2024, 1, 1))

    @patch("data_collection.stock_price_fetcher.yf.Ticker")
    def test_raises_on_empty_dataframe(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(RuntimeError):
            fetch_prices(MagicMock(), self._make_company(), date(2024, 1, 1))


class TestGetLatestPrice:
    def test_returns_most_recent(self):
        session = MagicMock()
        mock_price = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_price

        result = get_latest_price(session, company_id=1)
        assert result is mock_price

    def test_returns_none_when_empty(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = get_latest_price(session, company_id=99)
        assert result is None
