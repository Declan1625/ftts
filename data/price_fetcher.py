"""실시간 주가 수집기 (Price Fetcher).

기능:
1. DB의 활성 기업들의 현재 가격 조회
2. stock_prices 테이블에 저장
3. 에러 처리 및 재시도 로직
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from data.kis_api import KISClient, KISAPIError
from database.db_manager import get_session
from database.models import Company, StockPrice

logger = logging.getLogger(__name__)


class PriceFetcher:
    """KIS API를 사용해 주가 정보를 DB에 저장한다."""

    def __init__(self, kis_client: KISClient, session: Session) -> None:
        self.kis = kis_client
        self._s = session

    def fetch_and_save(
        self,
        company_ids: Optional[list[int]] = None,
        *,
        price_date: Optional[date] = None,
    ) -> tuple[int, int]:
        """
        주가를 조회하고 저장.

        Args:
            company_ids: 조회할 기업 ID 리스트 (None이면 활성 기업 모두)
            price_date: 저장할 가격의 날짜 (None이면 오늘)

        Returns:
            (saved_count, error_count)
        """
        price_date = price_date or date.today()

        if company_ids is None:
            companies = self._s.query(Company).filter_by(is_active=True).all()
        else:
            companies = self._s.query(Company).filter(Company.id.in_(company_ids)).all()

        if not companies:
            logger.warning("조회할 기업이 없습니다")
            return 0, 0

        tickers = [c.ticker for c in companies]
        ticker_to_company = {c.ticker: c for c in companies}

        logger.info("KIS API에서 %d개 종목 조회 중...", len(tickers))
        prices = self.kis.get_prices_batch(tickers)

        saved = 0
        errors = 0
        for ticker, price_data in prices.items():
            if price_data is None:
                errors += 1
                continue

            company = ticker_to_company.get(ticker)
            if company is None:
                logger.warning("매핑되지 않은 티커: %s", ticker)
                errors += 1
                continue

            try:
                self._save_stock_price(
                    company.id,
                    price_date,
                    price_data,
                )
                saved += 1
            except Exception as e:
                logger.error("주가 저장 실패 (company_id=%d): %s", company.id, e)
                errors += 1

        logger.info("주가 저장 완료: %d 성공, %d 실패", saved, errors)
        return saved, errors

    def _save_stock_price(
        self,
        company_id: int,
        price_date: date,
        price_data: dict,
    ) -> None:
        """단일 주가를 DB에 저장 (중복 무시)."""
        existing = (
            self._s.query(StockPrice)
            .filter_by(company_id=company_id, price_date=price_date)
            .first()
        )
        if existing:
            logger.debug("중복 가격 데이터 (company_id=%d, date=%s), 스킵", company_id, price_date)
            return

        sp = StockPrice(
            company_id=company_id,
            price_date=price_date,
            open=price_data.get("price"),
            high=price_data.get("high"),
            low=price_data.get("low"),
            close=price_data.get("price"),
            volume=price_data.get("volume"),
            adj_close=price_data.get("price"),
        )
        self._s.add(sp)
        self._s.flush()

    def get_latest_price(self, company_id: int) -> Optional[float]:
        """특정 기업의 최신 주가 반환."""
        sp = (
            self._s.query(StockPrice)
            .filter_by(company_id=company_id)
            .order_by(StockPrice.price_date.desc())
            .first()
        )
        return float(sp.close) if sp else None

    def get_latest_prices(self, company_ids: list[int]) -> dict[int, Optional[float]]:
        """여러 기업의 최신 주가 반환."""
        result = {}
        for company_id in company_ids:
            result[company_id] = self.get_latest_price(company_id)
        return result
