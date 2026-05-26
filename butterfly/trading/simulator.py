"""자체 모의투자 시뮬레이터

포트폴리오: 위험30% / 중간40% / 안정30%
실제 KIS 주가 사용, 드로우다운 가드 + 거래비용 반영
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from butterfly.db.models import Signal, Trade, Portfolio
from butterfly.trading.kis_client import KISPaperClient
from butterfly.trading.drawdown_guard import assess as dd_assess
from butterfly import config

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 티어별 설정
TIER = {
    "HIGH":   {"position_pct": 0.08, "target": 0.08, "stop": 0.05, "alloc": 0.30},
    "MEDIUM": {"position_pct": 0.10, "target": 0.05, "stop": 0.03, "alloc": 0.40},
    "STABLE": {"position_pct": 0.12, "target": 0.03, "stop": 0.02, "alloc": 0.30},
}

# 왕복 거래비용 추정 (증권거래세 + 수수료 + 슬리피지)
ROUND_TRIP_COST = 0.005   # 약 0.5%
BUY_COST = ROUND_TRIP_COST / 2  # 매수 시 절반


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


def _portfolio_value(session: Session, portfolio: Portfolio) -> float:
    open_trades = session.query(Trade).filter_by(status="open").all()
    cur_val = sum((t.current_price or t.price_at_entry or 0) * t.quantity for t in open_trades)
    return portfolio.cash + cur_val


def _tier_invested(session: Session, tier: str) -> float:
    rows = session.query(Trade).filter_by(status="open", risk_tier=tier).all()
    return sum((t.price_at_entry or 0) * t.quantity for t in rows)


def _is_market_hours() -> bool:
    """KST 09:00-15:30 평일만"""
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    return (9, 0) <= (h, m) <= (15, 30)


def run_simulation(session: Session) -> int:
    portfolio = _portfolio(session)

    # ── 0. 드로우다운 체크 ───────────────────────────────────────────
    dd = dd_assess(session)
    if not dd.trading_allowed:
        logger.warning("거래 중단: %s", dd.message)
        return 0
    if dd.level != "GREEN":
        logger.warning("포트폴리오 경보: %s", dd.message)

    if not _is_market_hours():
        logger.info("장외 시간 — 가격 업데이트/신규 매수 스킵")
        _log_summary(session, portfolio)
        return 0

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

        # 드로우다운 티어 제한
        if tier not in dd.allowed_tiers:
            logger.info("DD제한으로 %s 티어 스킵: %s", tier, sig.ticker)
            sig.executed = True
            continue

        cfg = TIER[tier]

        # 현재 포트폴리오 가치 기준 포지션 계산 (initial_cash 고정 버그 수정)
        pv = _portfolio_value(session, portfolio)
        position_budget = pv * cfg["position_pct"]
        tier_budget = pv * cfg["alloc"]

        # 티어 한도 체크
        if _tier_invested(session, tier) >= tier_budget:
            logger.info("💼 %s 티어 한도 도달 - %s 스킵", tier, sig.ticker)
            sig.executed = True
            continue

        # 현금 최소 체크
        if portfolio.cash < position_budget * 0.5:
            sig.executed = True
            continue

        # 중복 포지션 차단
        if session.query(Trade).filter_by(ticker=sig.ticker, status="open").first():
            logger.info("중복 포지션 차단: %s", sig.ticker)
            sig.executed = True
            continue

        price = _price(kis, sig.ticker)
        if not price:
            sig.executed = True
            continue

        # 1주 가격이 예산 초과면 스킵
        if price > position_budget:
            logger.info("💰 1주(%,.0f원) > 예산(%,.0f원) - %s 스킵", price, position_budget, sig.ticker)
            sig.executed = True
            continue

        qty = int(position_budget / price)
        if qty < 1:
            sig.executed = True
            continue

        # 거래비용 포함 실질 비용
        cost = price * qty
        cost_with_fee = cost * (1 + BUY_COST)

        if portfolio.cash < cost_with_fee:
            sig.executed = True
            continue

        portfolio.cash -= cost_with_fee

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
            "📈 [%s] 매수: %s %d주 @%,.0f원 | 목표%+.0f%% | 손절-%0.f%% | 잔액%,.0f원",
            tier, sig.ticker, qty, price,
            cfg["target"] * 100, cfg["stop"] * 100, portfolio.cash,
        )

    portfolio.updated_at = datetime.now(timezone.utc)
    session.commit()

    _log_summary(session, portfolio)
    return executed


def _close(trade: Trade, price: float, is_correct: bool, portfolio: Portfolio):
    trade.status = "closed"
    trade.price_at_exit = price
    trade.is_correct = is_correct
    trade.exited_at = datetime.now(timezone.utc)
    # 매도 시 거래비용 차감
    proceeds = price * trade.quantity * (1 - ROUND_TRIP_COST / 2)
    portfolio.cash += proceeds
    portfolio.realized_pnl = (portfolio.realized_pnl or 0) + trade.pnl


def _log_summary(session: Session, portfolio: Portfolio):
    open_trades = session.query(Trade).filter_by(status="open").all()
    cur_val = sum((t.current_price or t.price_at_entry or 0) * t.quantity for t in open_trades)
    total = portfolio.cash + cur_val
    pnl_pct = (total - portfolio.initial_cash) / portfolio.initial_cash * 100
    tier_cnt = {}
    for t in open_trades:
        tier_cnt[t.risk_tier] = tier_cnt.get(t.risk_tier, 0) + 1
    logger.info(
        "💼 포트폴리오 | 총평가 %,.0f원 | 현금 %,.0f원 | 수익률 %+.2f%% | 포지션 %s",
        total, portfolio.cash, pnl_pct,
        " ".join(f"{k}:{v}건" for k, v in tier_cnt.items()) or "없음",
    )
