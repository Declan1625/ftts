"""Yahoo Finance rate limit 우회용 샘플 주가 생성기.

실제 데이터 대신 현실적인 랜덤워크로 2년치 주가를 만들어 DB에 넣는다.
버핏 시뮬레이터 개발/테스트 전용. 실제 운용 전 반드시 실제 데이터로 교체.

실행:
    python -m scripts.seed_sample_prices
"""

from __future__ import annotations

import logging
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import get_session
from database.models import Company, StockPrice

logger = logging.getLogger(__name__)

# 종목별 시작가 (대략적인 2023년 초 가격)
START_PRICES: dict[str, float] = {
    "005930": 60000,   # 삼성전자
    "000660": 80000,   # SK하이닉스
    "373220": 400000,  # LG에너지솔루션
    "006400": 600000,  # 삼성SDI
    "105560": 50000,   # KB금융
    "207940": 800000,  # 삼성바이오로직스
    "005380": 180000,  # 현대차
    "AAPL":   145.0,
    "NVDA":   150.0,
    "MSFT":   240.0,
}

# 연간 변동성 (σ) — 종목별 특성 반영
ANNUAL_VOL: dict[str, float] = {
    "005930": 0.25,
    "000660": 0.40,
    "373220": 0.45,
    "006400": 0.35,
    "105560": 0.20,
    "207940": 0.30,
    "005380": 0.25,
    "AAPL":   0.25,
    "NVDA":   0.60,
    "MSFT":   0.25,
}


def _trading_days(start: date, end: date) -> list[date]:
    """월~금 거래일만 반환."""
    days = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # 0=월 … 4=금
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _generate_prices(ticker: str, start: date, end: date) -> list[dict]:
    """GBM(기하 브라운 운동) 기반 OHLCV 생성."""
    days = _trading_days(start, end)
    if not days:
        return []

    price = START_PRICES.get(ticker, 10000.0)
    annual_vol = ANNUAL_VOL.get(ticker, 0.30)
    daily_vol = annual_vol / (252 ** 0.5)
    daily_drift = 0.00008  # 연 약 2% 기대수익

    records = []
    for d in days:
        ret = random.gauss(daily_drift, daily_vol)
        close = round(price * (1 + ret), 2)
        daily_range = close * random.uniform(0.005, 0.025)
        high = round(close + daily_range * random.uniform(0.3, 1.0), 2)
        low  = round(close - daily_range * random.uniform(0.3, 1.0), 2)
        open_ = round(price * (1 + random.gauss(0, daily_vol * 0.5)), 2)
        volume = int(random.randint(100_000, 10_000_000))

        records.append({
            "price_date": d,
            "open":  max(open_, 1.0),
            "high":  max(high, close),
            "low":   min(low, close),
            "close": max(close, 1.0),
            "volume": volume,
            "adj_close": max(close, 1.0),
        })
        price = close

    return records


def main() -> None:
    start = date(2023, 1, 2)
    end   = date.today() - timedelta(days=1)

    with get_session() as session:
        companies: list[Company] = session.query(Company).all()
        if not companies:
            logger.error("companies 테이블이 비어있음. seed_data --no-price 를 먼저 실행하세요.")
            return

        total = 0
        for comp in companies:
            records = _generate_prices(comp.ticker, start, end)
            if not records:
                continue

            for r in records:
                # 이미 있으면 스킵
                exists = (
                    session.query(StockPrice)
                    .filter_by(company_id=comp.id, price_date=r["price_date"])
                    .first()
                )
                if exists:
                    continue
                session.add(StockPrice(company_id=comp.id, **r))

            session.flush()
            logger.info("샘플 주가 추가: %s (%s) — %d건", comp.name, comp.ticker, len(records))
            total += len(records)

    logger.info("완료 — 총 %d건 삽입", total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    main()
