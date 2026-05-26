"""모의투자 실행기"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Signal, Trade
from butterfly.config import PAPER_INITIAL_CASH, POSITION_SIZE_RATIO

logger = logging.getLogger(__name__)


class PaperTrader:
    def __init__(self, session: Session):
        self.session = session
        self.cash = PAPER_INITIAL_CASH

    def execute_pending(self, price_fn) -> int:
        """미실행 신호 처리. price_fn(ticker) → 현재가"""
        signals = self.session.query(Signal).filter_by(executed=False).all()
        executed = 0
        for signal in signals:
            price = price_fn(signal.ticker)
            if not price:
                logger.warning("주가 없음: %s", signal.ticker)
                continue

            budget = self.cash * POSITION_SIZE_RATIO
            qty = int(budget / price)
            if qty < 1:
                continue

            trade = Trade(
                signal_id=signal.id,
                ticker=signal.ticker,
                direction=signal.direction,
                quantity=qty,
                price_at_entry=price,
            )
            self.session.add(trade)
            signal.executed = True
            if signal.direction == "BUY":
                self.cash -= price * qty
            executed += 1
            logger.info("모의투자: %s %s %d주 @%d", signal.direction, signal.ticker, qty, price)

        self.session.commit()
        return executed
