"""KIS 모의투자 실행기"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Signal, Trade
from butterfly.trading.kis_client import KISPaperClient, KISError
from butterfly import config

logger = logging.getLogger(__name__)


def execute_pending(session: Session) -> int:
    signals = session.query(Signal).filter_by(executed=False).all()
    if not signals:
        logger.info("실행 대기 신호 없음")
        return 0

    logger.info("신호 %d건 KIS 모의투자 실행 시작", len(signals))
    try:
        kis = KISPaperClient()
        kis.authenticate()
    except Exception as e:
        logger.error("KIS 인증 실패: %s", e)
        return 0

    executed = 0
    for signal in signals:
        try:
            price = kis.get_price(signal.ticker)
            if not price:
                logger.warning("주가 0: %s 스킵", signal.ticker)
                continue

            budget = config.PAPER_INITIAL_CASH * config.POSITION_SIZE_RATIO
            qty = int(budget / price)
            if qty < 1:
                logger.warning("수량 부족: %s (예산 %.0f, 주가 %.0f)", signal.ticker, budget, price)
                continue

            if signal.direction == "BUY":
                kis.buy(signal.ticker, qty)
            else:
                logger.info("SELL 신호 %s - 포지션 없어 스킵", signal.ticker)
                signal.executed = True
                session.commit()
                continue

            session.add(Trade(
                signal_id=signal.id,
                ticker=signal.ticker,
                direction=signal.direction,
                quantity=qty,
                price_at_entry=price,
            ))
            signal.executed = True
            executed += 1

        except KISError as e:
            logger.error("주문 실패 [%s]: %s", signal.ticker, e)
        except Exception as e:
            logger.error("예상치 못한 오류 [%s]: %s", signal.ticker, e)

    session.commit()
    logger.info("모의투자 완료: %d건 실행", executed)
    return executed
