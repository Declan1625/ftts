"""자체 모의투자 시뮬레이터

포트폴리오 구성: 위험 30% / 중간 40% / 안정 30%
실제 KIS 주가 기반, 매수/청산은 내부 처리
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session
from butterfly.db.models import Signal, Trade, Portfolio
from butterfly.trading.kis_client import KISPaperClient
from butterfly import config

logger = logging.getLogger(__name__)

# 티어별 설정: position_pct=포지션 크기, target=목표수익률, stop=손절률
TIER = {
    "HIGH":   {"position_pct": 0.08, "target": 0.08, "stop": 0.05, "alloc": 0.30},
    "MEDIUM": {"position_pct": 0.10, "target": 0.05, "stop": 0.03, "alloc": 0.40},
    "STABLE": {"position_pct": 0.12, "target": 0.03, "stop": 0.02, "alloc": 0.30},
}


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
        logger.warning("KIS 주가 조회 불가: %s", e)
        return None


def _price(kis, ticker: str) -> float | None:
    if not kis:
        return None
    try:
        return kis.get_price(ticker)
    except Exception:
        return None


def _tier_invested(session: Session, tier: str) -> float:
    rows = session.query(Trade).filter_by(status="open", risk_tier=tier).all()
    return sum((t.price_at_entry or 0) * t.quantity for t in rows)


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
        t.pnl = (price - t.price_at_entry) * t.quantity
        t.pnl_pct = (price - t.price_at_entry) / t.price_at_entry * 100

        if t.target_price and price >= t.target_price:
            _close(t, price, True, portfolio)
            logger.info("🎯 목표 청산: %s +%.1f%% (+%,.0f원)", t.ticker, t.pnl_pct, t.pnl)
        elif t.stop_loss_price and price <= t.stop_loss_price:
            _close(t, price, False, portfolio)
            logger.info("🛑 손절 청산: %s %.1f%% (%,.0f원)", t.ticker, t.pnl_pct, t.pnl)

    session.commit()

    # ── 2. 새 BUY 신호 실행 ──────────────────────────────────────────
    signals = session.query(Signal).filter_by(executed=False).all()
    executed = 0

    for sig in signals:
        if sig.direction != "BUY":
            sig.executed = True
            continue

        tier = sig.risk_tier or "MEDIUM"
        cfg = TIER[tier]
        tier_budget = portfolio.initial_cash * cfg["alloc"]
        position_budget = portfolio.initial_cash * cfg["position_pct"]

        # 티어 한도 체크
        if _tier_invested(session, tier) >= tier_budget:
            logger.info("💼 %s 티어 한도 도달 (%.0f원) - %s 스킵", tier, tier_budget, sig.ticker)
            sig.executed = True
            continue

        # 현금 체크
        if portfolio.cash < position_budget * 0.5:
            logger.info("💸 현금 부족 (%.0f원) - %s 스킵", portfolio.cash, sig.ticker)
            sig.executed = True
            continue

        price = _price(kis, sig.ticker)
        if not price:
            logger.warning("주가 조회 실패 - %s 스킵", sig.ticker)
            sig.executed = True
            continue

        # 주가 > 포지션 예산이면 살 수 없음
        if price > position_budget:
            logger.info("💰 1주 가격(%,.0f원) > 예산(%,.0f원) - %s 스킵",
                        price, position_budget, sig.ticker)
            sig.executed = True
            continue

        qty = int(position_budget / price)
        if qty < 1:
            sig.executed = True
            continue

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
            risk_tier=tier,
            quantity=qty,
            price_at_entry=price,
            current_price=price,
            target_price=round(price * (1 + cfg["target"])),
            stop_loss_price=round(price * (1 - cfg["stop"])),
            pnl=0.0,
            pnl_pct=0.0,
            status="open",
        )
        session.add(trade)
        sig.executed = True
        executed += 1

        logger.info(
            "📈 [%s] 매수: %s %d주 @%,.0f원 | 목표%+.0f%% %,.0f | 손절-%0.f%% %,.0f | 잔액%,.0f원",
            tier, sig.ticker, qty, price,
            cfg["target"] * 100, trade.target_price,
            cfg["stop"] * 100, trade.stop_loss_price,
            portfolio.cash,
        )

    portfolio.updated_at = datetime.now(timezone.utc)
    session.commit()

    _log_portfolio_summary(session, portfolio)
    return executed


def _close(trade: Trade, price: float, is_correct: bool, portfolio: Portfolio):
    trade.status = "closed"
    trade.price_at_exit = price
    trade.is_correct = is_correct
    trade.exited_at = datetime.now(timezone.utc)
    portfolio.cash += price * trade.quantity
    portfolio.realized_pnl = (portfolio.realized_pnl or 0) + trade.pnl


def _log_portfolio_summary(session: Session, portfolio: Portfolio):
    open_trades = session.query(Trade).filter_by(status="open").all()
    invested = sum((t.price_at_entry or 0) * t.quantity for t in open_trades)
    cur_val = sum((t.current_price or t.price_at_entry or 0) * t.quantity for t in open_trades)
    total = portfolio.cash + cur_val
    pnl_pct = (total - portfolio.initial_cash) / portfolio.initial_cash * 100

    tier_counts = {}
    for t in open_trades:
        tier_counts[t.risk_tier] = tier_counts.get(t.risk_tier, 0) + 1

    logger.info(
        "💼 포트폴리오 | 총평가 %,.0f원 | 현금 %,.0f원 | 투자 %,.0f원 | 수익률 %+.2f%% | 포지션 %s",
        total, portfolio.cash, cur_val, pnl_pct,
        " ".join(f"{k}:{v}건" for k, v in tier_counts.items()) or "없음",
    )
