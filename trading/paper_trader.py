"""모의 투자 실행기 (Paper Trader).

WeightEngine이 생성한 DecisionResult를 받아:
1. positions / trades 테이블에 기록
2. 현금 잔고를 관리 (PAPER_INITIAL_CASH 기준)
3. 결정 결과를 decisions 테이블에 저장

매수 수량 결정:
    가용 현금 × confidence × 0.2 ÷ 현재가  (최대 20% 포지션)

수수료:
    매수/매도 각 0.015% (한국 기본 수수료)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from core.weight_engine import DecisionResult
from database.models import Company, Decision, Position, Trade

logger = logging.getLogger(__name__)

FEE_RATE = 0.00015  # 0.015%
MAX_POSITION_RATIO = 0.20  # 가용 현금의 최대 20%


class InsufficientCashError(Exception):
    pass


class PaperTrader:
    """모의 투자 엔진. 하나의 인스턴스가 하나의 모의 계좌를 관리한다."""

    def __init__(self, session: Session, *, initial_cash: Optional[float] = None) -> None:
        self._session = session
        self.cash = float(initial_cash or settings.PAPER_INITIAL_CASH)
        self._peak_cash = self.cash  # MDD 계산용

    # ── 공개 API ─────────────────────────────────────────────────

    def execute(
        self,
        result: DecisionResult,
        current_price: float,
        *,
        company_db_id: int,
        decision_db_id: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> Optional[Trade]:
        """매매 결정을 실행하고 Trade 레코드를 반환한다.

        HOLD 신호이면 None 반환.
        """
        now = now or datetime.now(timezone.utc)

        if result.signal == "HOLD":
            logger.debug("HOLD — 종목 %d 미체결", company_db_id)
            return None

        if result.signal == "BUY":
            return self._buy(company_db_id, current_price, result, decision_db_id, now)
        else:
            return self._sell(company_db_id, current_price, result, decision_db_id, now)

    def portfolio_value(self, price_map: dict[int, float]) -> float:
        """현금 + 보유 포지션 평가액 합계.

        price_map: {company_id: current_price}
        """
        positions = (
            self._session.query(Position)
            .filter_by(mode="paper", is_open=True)
            .all()
        )
        stock_value = sum(
            price_map.get(p.company_id, float(p.avg_buy_price or 0)) * p.quantity
            for p in positions
        )
        return self.cash + stock_value

    def open_positions(self) -> list[Position]:
        return (
            self._session.query(Position)
            .filter_by(mode="paper", is_open=True)
            .all()
        )

    def total_return(self, price_map: dict[int, float]) -> float:
        """총 수익률 (0.10 = +10%)."""
        initial = settings.PAPER_INITIAL_CASH
        current = self.portfolio_value(price_map)
        return (current - initial) / initial

    # ── 내부 ─────────────────────────────────────────────────────

    def _buy(
        self,
        company_id: int,
        price: float,
        result: DecisionResult,
        decision_id: Optional[int],
        now: datetime,
    ) -> Optional[Trade]:
        qty = self._calc_buy_quantity(price, result.confidence)
        if qty <= 0:
            logger.warning("매수 수량 0 — 현금 부족 또는 신뢰도 낮음 (현금=%.0f, 가격=%.0f)", self.cash, price)
            return None

        cost = price * qty
        fee = cost * FEE_RATE
        total_cost = cost + fee

        if total_cost > self.cash:
            raise InsufficientCashError(f"잔고 부족: 필요 {total_cost:.0f}, 보유 {self.cash:.0f}")

        self.cash -= total_cost
        self._peak_cash = max(self._peak_cash, self.cash + cost)

        position = self._get_or_create_position(company_id, now)
        self._update_position_on_buy(position, qty, price)

        trade = Trade(
            position_id=position.id,
            decision_id=decision_id,
            company_id=company_id,
            mode="paper",
            side="BUY",
            quantity=qty,
            price=price,
            fee=fee,
            executed_at=now,
        )
        self._session.add(trade)
        self._session.flush()

        logger.info(
            "매수 체결 — 종목=%d, 수량=%d, 가격=%.0f, 수수료=%.0f, 잔고=%.0f",
            company_id, qty, price, fee, self.cash,
        )
        return trade

    def _sell(
        self,
        company_id: int,
        price: float,
        result: DecisionResult,
        decision_id: Optional[int],
        now: datetime,
    ) -> Optional[Trade]:
        position = (
            self._session.query(Position)
            .filter_by(company_id=company_id, mode="paper", is_open=True)
            .first()
        )
        if position is None or position.quantity <= 0:
            logger.debug("매도 불가 — 보유 포지션 없음 (종목=%d)", company_id)
            return None

        qty = position.quantity
        revenue = price * qty
        fee = revenue * FEE_RATE
        net_revenue = revenue - fee

        avg_price = float(position.avg_buy_price or price)
        realized_pnl = (price - avg_price) * qty - fee

        self.cash += net_revenue

        position.quantity = 0
        position.is_open = False
        position.closed_at = now

        trade = Trade(
            position_id=position.id,
            decision_id=decision_id,
            company_id=company_id,
            mode="paper",
            side="SELL",
            quantity=qty,
            price=price,
            fee=fee,
            realized_pnl=realized_pnl,
            executed_at=now,
        )
        self._session.add(trade)
        self._session.flush()

        logger.info(
            "매도 체결 — 종목=%d, 수량=%d, 가격=%.0f, 실현손익=%.0f, 잔고=%.0f",
            company_id, qty, price, realized_pnl, self.cash,
        )
        return trade

    def _calc_buy_quantity(self, price: float, confidence: float) -> int:
        """가용 현금의 confidence × MAX_POSITION_RATIO 만큼 매수."""
        if price <= 0:
            return 0
        invest_amount = self.cash * confidence * MAX_POSITION_RATIO
        return int(invest_amount // price)

    def _get_or_create_position(self, company_id: int, now: datetime) -> Position:
        position = (
            self._session.query(Position)
            .filter_by(company_id=company_id, mode="paper", is_open=True)
            .first()
        )
        if position is None:
            position = Position(
                company_id=company_id,
                mode="paper",
                quantity=0,
                opened_at=now,
            )
            self._session.add(position)
            self._session.flush()
        return position

    def _update_position_on_buy(self, position: Position, qty: int, price: float) -> None:
        old_qty = position.quantity
        old_avg = float(position.avg_buy_price or 0)
        new_qty = old_qty + qty
        new_avg = ((old_avg * old_qty) + (price * qty)) / new_qty
        position.quantity = new_qty
        position.avg_buy_price = new_avg
