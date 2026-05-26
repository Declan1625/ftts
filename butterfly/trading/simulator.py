"""자체 모의투자 시뮬레이터 - KIS 주가만 사용, 주문은 내부 처리"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from butterfly.db.models import Signal, Trade, Portfolio
from butterfly.trading.kis_client import KISPaperClient, KISError
from butterfly import config

logger = logging.getLogger(__name__)

TARGET_PCT = 0.05    # 목표 수익률 +5%
STOP_PCT = 0.03      # 손절 -3%


def _portfolio(session: Session) -> Portfolio:
    p = session.query(Portfolio).first()
    if not p:
        p = Portfolio(
            cash=config.PAPER_INITIAL_CASH,
            initial_cash=config.PAPER_INITIAL_CASH,
            realized_pnl=0.0,
        )
        session.add(p)
        session.commit()
    return p


def _kis() -> KISPaperClient | None:
    try:
        k = KISPaperClient()
        k.authenticate()
        return k
    except Exception as e:
        logger.warning("KIS 주가 조회 불가 (시뮬레이션 가격 업데이트 생략): %s", e)
        return None


def _price(kis: KISPaperClient | None, ticker: str) -> float | None:
    if not kis:
        return None
    try:
        return kis.get_price(ticker)
    except Exception:
        return None


def run_simulation(session: Session) -> int:
    portfolio = _portfolio(session)
    kis = _kis()

    # ── 1. 오픈 포지션 현재가 업데이트 및 청산 체크 ─────────────────
    open_trades = session.query(Trade).filter_by(status="open").all()
    for t in open_trades:
        price = _price(kis, t.ticker)
        if not price:
            continue

        t.current_price = price
        cost = t.price_at_entry * t.quantity
        t.pnl = (price - t.price_at_entry) * t.quantity
        t.pnl_pct = (price - t.price_at_entry) / t.price_at_entry * 100

        if price >= t.target_price:
            _close(t, price, True, portfolio)
            logger.info("🎯 목표 달성 청산: %s +%.1f%% (%.0f원)", t.ticker, t.pnl_pct, t.pnl)
        elif price <= t.stop_loss_price:
            _close(t, price, False, portfolio)
            logger.info("🛑 손절 청산: %s %.1f%% (%.0f원)", t.ticker, t.pnl_pct, t.pnl)

    session.commit()

    # ── 2. 새 BUY 신호 실행 ──────────────────────────────────────────
    signals = session.query(Signal).filter_by(executed=False).all()
    executed = 0

    for sig in signals:
        if sig.direction != "BUY":
            sig.executed = True
            continue

        budget = config.PAPER_INITIAL_CASH * config.POSITION_SIZE_RATIO
        if portfolio.cash < budget * 0.5:
            logger.info("현금 부족 (%.0f원) - %s 스킵", portfolio.cash, sig.ticker)
            sig.executed = True
            continue

        price = _price(kis, sig.ticker)
        if not price:
            logger.warning("주가 조회 실패 - %s 스킵", sig.ticker)
            sig.executed = True
            continue

        qty = max(1, int(budget / price))
        cost = price * qty

        if portfolio.cash < cost:
            sig.executed = True
            continue

        portfolio.cash -= cost

        trade = Trade(
            signal_id=sig.id,
            ticker=sig.ticker,
            company_name=sig.company_name,
            direction="BUY",
            quantity=qty,
            price_at_entry=price,
            current_price=price,
            target_price=round(price * (1 + TARGET_PCT)),
            stop_loss_price=round(price * (1 - STOP_PCT)),
            pnl=0.0,
            pnl_pct=0.0,
            status="open",
        )
        session.add(trade)
        sig.executed = True
        executed += 1

        logger.info(
            "📈 매수 체결: %s %d주 @%,.0f원 | 목표 %,.0f | 손절 %,.0f | 잔액 %,.0f원",
            sig.ticker, qty, price, trade.target_price, trade.stop_loss_price, portfolio.cash,
        )

    portfolio.updated_at = datetime.now(timezone.utc)
    session.commit()

    total_value = _total_value(session, portfolio, kis)
    pnl_pct = (total_value - portfolio.initial_cash) / portfolio.initial_cash * 100
    logger.info(
        "💼 포트폴리오: 현금 %,.0f원 | 평가총액 %,.0f원 | 누적손익 %+.1f%%",
        portfolio.cash, total_value, pnl_pct,
    )
    return executed


def _close(trade: Trade, price: float, is_correct: bool, portfolio: Portfolio):
    trade.status = "closed"
    trade.price_at_exit = price
    trade.is_correct = is_correct
    trade.exited_at = datetime.now(timezone.utc)
    proceeds = price * trade.quantity
    portfolio.cash += proceeds
    portfolio.realized_pnl = (portfolio.realized_pnl or 0) + trade.pnl


def _total_value(session: Session, portfolio: Portfolio, kis) -> float:
    open_trades = session.query(Trade).filter_by(status="open").all()
    invested_value = sum(
        (t.current_price or t.price_at_entry) * t.quantity for t in open_trades
    )
    return portfolio.cash + invested_value
