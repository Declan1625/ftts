"""data_collection/stock_price_fetcher.py — yfinance 주가 데이터 수집"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import os

import yfinance as yf
from sqlalchemy.orm import Session

from database.models import Company, StockPrice

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2  # seconds


def fetch_prices(
    session: Session,
    company: Company,
    start: date,
    end: date | None = None,
) -> list[StockPrice]:
    """단일 종목 OHLCV를 yfinance로 수집 후 DB upsert. 재시도 3회."""
    end = end or date.today()
    ticker_str = _to_yfinance_ticker(company.ticker, company.market)

    raw = None
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            ticker = yf.Ticker(ticker_str)
            raw = ticker.history(start=str(start), end=str(end), auto_adjust=True)
            break
        except Exception as exc:
            last_error = exc
            logger.warning("yfinance 재시도 %d/%d — %s: %s", attempt, _MAX_RETRIES, ticker_str, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)

    if raw is None or raw.empty:
        logger.error("주가 수집 실패 — %s: %s", ticker_str, last_error)
        raise RuntimeError(f"주가 수집 실패: {ticker_str}") from last_error

    records: list[StockPrice] = []
    for price_date, row in raw.iterrows():
        records.append(
            StockPrice(
                company_id=company.id,
                price_date=price_date.date(),
                open=float(row["Open"]) if row["Open"] else None,
                high=float(row["High"]) if row["High"] else None,
                low=float(row["Low"]) if row["Low"] else None,
                close=float(row["Close"]),
                volume=int(row["Volume"]) if row["Volume"] else None,
                adj_close=float(row["Close"]),
            )
        )

    _upsert_prices(session, records)
    logger.info("주가 저장 — %s: %d건", ticker_str, len(records))
    return records


def fetch_prices_bulk(
    session: Session,
    companies: list[Company],
    start: date,
    end: date | None = None,
) -> dict[str, list[StockPrice]]:
    """여러 종목 일괄 수집. 실패 종목은 로그 후 스킵."""
    results: dict[str, list[StockPrice]] = {}
    for company in companies:
        try:
            results[company.ticker] = fetch_prices(session, company, start, end)
        except RuntimeError:
            logger.error("스킵 — %s", company.ticker)
    return results


def get_latest_price(session: Session, company_id: int) -> StockPrice | None:
    return (
        session.query(StockPrice)
        .filter(StockPrice.company_id == company_id)
        .order_by(StockPrice.price_date.desc())
        .first()
    )


def _upsert_prices(session: Session, records: list[StockPrice]) -> None:
    """DB 종류에 무관하게 동작하는 upsert (PostgreSQL JSONB / SQLite JSON 공용)."""
    if not records:
        return

    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql"):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(StockPrice).values(
            [{"company_id": r.company_id, "price_date": r.price_date,
              "open": r.open, "high": r.high, "low": r.low, "close": r.close,
              "volume": r.volume, "adj_close": r.adj_close} for r in records]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "price_date"],
            set_={"open": stmt.excluded.open, "high": stmt.excluded.high,
                  "low": stmt.excluded.low, "close": stmt.excluded.close,
                  "volume": stmt.excluded.volume, "adj_close": stmt.excluded.adj_close},
        )
        session.execute(stmt)
    else:
        # SQLite: 기존 행은 업데이트, 없으면 삽입
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(StockPrice).values(
            [{"company_id": r.company_id, "price_date": r.price_date,
              "open": r.open, "high": r.high, "low": r.low, "close": r.close,
              "volume": r.volume, "adj_close": r.adj_close} for r in records]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "price_date"],
            set_={"open": stmt.excluded.open, "high": stmt.excluded.high,
                  "low": stmt.excluded.low, "close": stmt.excluded.close,
                  "volume": stmt.excluded.volume, "adj_close": stmt.excluded.adj_close},
        )
        session.execute(stmt)


def _to_yfinance_ticker(ticker: str, market: str) -> str:
    """KOSPI/KOSDAQ 종목은 .KS / .KQ 접미사 추가."""
    if market == "KOSPI":
        return f"{ticker}.KS"
    if market == "KOSDAQ":
        return f"{ticker}.KQ"
    return ticker
