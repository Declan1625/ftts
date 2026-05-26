"""드로우다운 가드 - 계좌 폭파 방지 3단계 브레이커"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from butterfly.db.models import Trade, Portfolio

logger = logging.getLogger(__name__)

# 드로우다운 단계별 설정
_LEVELS = [
    # (임계값, 레벨명, 허용 티어, 메시지)
    (-0.20, "BLACK",  [],                   "전면 거래 중단 — 긴급 점검 필요"),
    (-0.15, "RED",    ["STABLE"],           "위험: STABLE만 허용"),
    (-0.10, "YELLOW", ["MEDIUM", "STABLE"], "경보: HIGH 거래 중단"),
    (-0.05, "GREEN",  ["HIGH", "MEDIUM", "STABLE"], "정상"),
]


@dataclass
class DDState:
    level: str
    current_dd: float
    allowed_tiers: list[str]
    trading_allowed: bool
    message: str


def assess(session: Session) -> DDState:
    p = session.query(Portfolio).first()
    if not p:
        return DDState("GREEN", 0.0, ["HIGH", "MEDIUM", "STABLE"], True, "포트폴리오 초기화 전")

    open_trades = session.query(Trade).filter_by(status="open").all()
    cur_val = sum((t.current_price or t.price_at_entry or 0) * t.quantity for t in open_trades)
    total = p.cash + cur_val
    dd = (total - p.initial_cash) / p.initial_cash if p.initial_cash else 0.0

    level, allowed, msg = "GREEN", ["HIGH", "MEDIUM", "STABLE"], "정상"
    for threshold, lvl, tiers, message in _LEVELS:
        if dd <= threshold:
            level, allowed, msg = lvl, tiers, f"{message} (DD: {dd:.1%})"
            break

    if level in ("RED", "BLACK"):
        logger.warning("🚨 드로우다운 %s: %s", level, msg)

    if level == "BLACK":
        _emergency_close(session, p)

    return DDState(
        level=level,
        current_dd=dd,
        allowed_tiers=allowed,
        trading_allowed=len(allowed) > 0,
        message=msg,
    )


def _emergency_close(session: Session, portfolio: Portfolio):
    """BLACK 레벨: 손실 포지션 최대 3개 강제 청산"""
    losers = (
        session.query(Trade)
        .filter(Trade.status == "open", Trade.pnl_pct < -3.0)
        .order_by(Trade.pnl_pct)
        .limit(3)
        .all()
    )
    for t in losers:
        logger.warning("🚨 긴급 청산: %s (%.1f%%)", t.ticker, t.pnl_pct or 0)
        t.status = "closed"
        t.price_at_exit = t.current_price or t.price_at_entry
        t.exited_at = datetime.now(timezone.utc)
        proceeds = (t.current_price or t.price_at_entry or 0) * t.quantity
        portfolio.cash += proceeds
        portfolio.realized_pnl = (portfolio.realized_pnl or 0) + (t.pnl or 0)
    session.commit()
