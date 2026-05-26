"""KIS 모의투자 실행기"""
from __future__ import annotations
import logging
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlalchemy.orm import Session
from butterfly.db.models import Signal, Trade
from butterfly import config

logger = logging.getLogger(__name__)


def _get_kis():
    from data.kis_api import KISClient
    client = KISClient(
        app_key=config.KIS_APP_KEY,
        app_secret=config.KIS_APP_SECRET,
        account_no=config.KIS_ACCOUNT,
        mock=True,
    )
    client.authenticate()
    return client


def execute_pending(session: Session) -> int:
    signals = session.query(Signal).filter_by(executed=False).all()
    if not signals:
        return 0

    try:
        kis = _get_kis()
    except Exception as e:
        logger.error("KIS 인증 실패: %s", e)
        return 0

    executed = 0
    for signal in signals:
        try:
            price_data = kis.get_price(signal.ticker)
            price = price_data["price"]
            if not price:
                continue

            budget = config.PAPER_INITIAL_CASH * config.POSITION_SIZE_RATIO
            qty = int(budget / price)
            if qty < 1:
                continue

            if signal.direction == "BUY":
                kis.place_buy_order(signal.ticker, qty)
            # SELL은 보유 포지션 없으면 스킵 (모의투자 초기)

            session.add(Trade(
                signal_id=signal.id,
                ticker=signal.ticker,
                direction=signal.direction,
                quantity=qty,
                price_at_entry=price,
            ))
            signal.executed = True
            executed += 1
            logger.info("모의투자 실행: %s %s %d주 @%.0f", signal.direction, signal.ticker, qty, price)
        except Exception as e:
            logger.error("주문 실패 [%s]: %s", signal.ticker, e)

    session.commit()
    return executed
