"""시드 데이터 삽입 + 주가 수집 스크립트.

실행:
    python -m scripts.seed_data            # 종목 삽입 + 주가 2년치 수집
    python -m scripts.seed_data --no-price # 종목만 삽입 (주가 수집 스킵)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import get_session, init_db
from database.models import Company, Industry, Source
from data_collection.stock_price_fetcher import fetch_prices_bulk

logger = logging.getLogger(__name__)

# ── 시드: 산업 ────────────────────────────────────────────────
INDUSTRIES = [
    {"code": "SEMICONDUCTOR", "name": "반도체",       "sector": "IT"},
    {"code": "BATTERY",       "name": "2차전지",      "sector": "소재/에너지"},
    {"code": "FINANCE",       "name": "금융",          "sector": "금융"},
    {"code": "PHARMA",        "name": "바이오/제약",   "sector": "헬스케어"},
    {"code": "AUTO",          "name": "자동차",        "sector": "산업재"},
    {"code": "TECH_US",       "name": "미국 빅테크",   "sector": "IT"},
]

# ── 시드: 기업 ────────────────────────────────────────────────
# (ticker, name, market, industry_code)
COMPANIES = [
    # 반도체
    ("005930", "삼성전자",      "KOSPI",  "SEMICONDUCTOR"),
    ("000660", "SK하이닉스",    "KOSPI",  "SEMICONDUCTOR"),
    # 2차전지
    ("373220", "LG에너지솔루션", "KOSPI", "BATTERY"),
    ("006400", "삼성SDI",       "KOSPI",  "BATTERY"),
    # 금융
    ("105560", "KB금융",        "KOSPI",  "FINANCE"),
    # 바이오
    ("207940", "삼성바이오로직스","KOSPI", "PHARMA"),
    # 자동차
    ("005380", "현대차",        "KOSPI",  "AUTO"),
    # 미국 빅테크
    ("AAPL",   "Apple",         "NASDAQ", "TECH_US"),
    ("NVDA",   "NVIDIA",        "NASDAQ", "TECH_US"),
    ("MSFT",   "Microsoft",     "NASDAQ", "TECH_US"),
]

# ── 시드: 정보원 ──────────────────────────────────────────────
SOURCES = [
    {"name": "메르 블로그",       "type": "blog",     "grade": "A", "grade_weight": 0.8},
    {"name": "연합인포맥스",      "type": "news",     "grade": "B", "grade_weight": 0.6},
    {"name": "한국경제",          "type": "news",     "grade": "B", "grade_weight": 0.6},
    {"name": "Bloomberg",         "type": "news",     "grade": "A", "grade_weight": 0.8},
    {"name": "SEC EDGAR",         "type": "official", "grade": "S", "grade_weight": 1.0},
    {"name": "금융감독원 공시",   "type": "official", "grade": "S", "grade_weight": 1.0},
]


def seed_industries(session) -> dict[str, Industry]:
    ind_map: dict[str, Industry] = {}
    for data in INDUSTRIES:
        existing = session.query(Industry).filter_by(code=data["code"]).first()
        if existing:
            ind_map[data["code"]] = existing
            continue
        ind = Industry(**data)
        session.add(ind)
        session.flush()
        ind_map[data["code"]] = ind
        logger.info("산업 추가: %s", data["name"])
    return ind_map


def seed_companies(session, ind_map: dict[str, Industry]) -> list[Company]:
    companies: list[Company] = []
    for ticker, name, market, ind_code in COMPANIES:
        existing = session.query(Company).filter_by(ticker=ticker).first()
        if existing:
            companies.append(existing)
            continue
        comp = Company(
            ticker=ticker,
            name=name,
            market=market,
            industry_id=ind_map[ind_code].id,
        )
        session.add(comp)
        session.flush()
        companies.append(comp)
        logger.info("기업 추가: %s (%s)", name, ticker)
    return companies


def seed_sources(session) -> list[Source]:
    sources: list[Source] = []
    for data in SOURCES:
        existing = session.query(Source).filter_by(name=data["name"]).first()
        if existing:
            sources.append(existing)
            continue
        src = Source(**data)
        session.add(src)
        session.flush()
        sources.append(src)
        logger.info("정보원 추가: %s", data["name"])
    return sources


def main(fetch_price: bool = True) -> None:
    init_db()

    with get_session() as session:
        logger.info("=== 산업 시드 ===")
        ind_map = seed_industries(session)

        logger.info("=== 기업 시드 ===")
        companies = seed_companies(session, ind_map)

        logger.info("=== 정보원 시드 ===")
        seed_sources(session)

        if fetch_price:
            logger.info("=== 주가 수집 (2년치) ===")
            start = date.today() - timedelta(days=730)
            results = fetch_prices_bulk(session, companies, start=start)
            total = sum(len(v) for v in results.values())
            logger.info("주가 수집 완료 — 종목 %d개, 총 %d건", len(results), total)
        else:
            logger.info("주가 수집 스킵 (--no-price)")

    logger.info("=== 시드 완료 ===")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-price", action="store_true", help="주가 수집 스킵")
    args = parser.parse_args()
    main(fetch_price=not args.no_price)
