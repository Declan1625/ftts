from __future__ import annotations

import math
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime,
    Float, ForeignKey, Index, Integer, Numeric, SmallInteger,
    String, Text, UniqueConstraint, func,
)
import os
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB

# PostgreSQL URL이면 JSONB, 그 외(SQLite 등)이면 JSON
_db_url = os.getenv("DATABASE_URL", "")
JSONB = _PG_JSONB if _db_url.startswith("postgresql") else JSON  # type: ignore[assignment]
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── 1. sources ────────────────────────────────────────────────
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        info={"check": "type IN ('blog','news','report','sns','official')"},
    )
    grade: Mapped[str] = mapped_column(String(1), nullable=False, default="C")
    grade_weight: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.40)
    total_predictions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_predictions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.0)
    consecutive_d_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events: Mapped[list["Event"]] = relationship("Event", back_populates="source")

    __table_args__ = (
        CheckConstraint("grade IN ('S','A','B','C','D')", name="ck_sources_grade"),
        CheckConstraint("type IN ('blog','news','report','sns','official')", name="ck_sources_type"),
        Index("idx_sources_grade", "grade"),
        Index("idx_sources_active", "is_active"),
    )

    def recalculate_grade(self, grade_thresholds: dict, grade_weights: dict, min_preds: int, neutral_weight: float) -> None:
        if self.total_predictions < min_preds:
            self.grade_weight = neutral_weight
            return
        acc = self.accuracy
        if acc >= grade_thresholds["S"]:
            self.grade = "S"
        elif acc >= grade_thresholds["A"]:
            self.grade = "A"
        elif acc >= grade_thresholds["B"]:
            self.grade = "B"
        elif acc >= grade_thresholds["C"]:
            self.grade = "C"
        else:
            self.grade = "D"
        self.grade_weight = grade_weights[self.grade]


# ── 2. industries ─────────────────────────────────────────────
class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    companies: Mapped[list["Company"]] = relationship("Company", back_populates="industry")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="industry")

    __table_args__ = (
        Index("idx_industries_sector", "sector"),
    )


# ── 3. companies ──────────────────────────────────────────────
class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    industry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("industries.id", ondelete="SET NULL"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    industry: Mapped[Optional["Industry"]] = relationship("Industry", back_populates="companies")
    stock_prices: Mapped[list["StockPrice"]] = relationship("StockPrice", back_populates="company")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="company")
    decisions: Mapped[list["Decision"]] = relationship("Decision", back_populates="company")
    positions: Mapped[list["Position"]] = relationship("Position", back_populates="company")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="company")

    __table_args__ = (
        CheckConstraint("market IN ('KOSPI','KOSDAQ','NYSE','NASDAQ','OTHER')", name="ck_companies_market"),
        Index("idx_companies_industry", "industry_id"),
        Index("idx_companies_market", "market"),
        Index("idx_companies_active", "is_active"),
    )


# ── 4. stock_prices ───────────────────────────────────────────
class StockPrice(Base):
    __tablename__ = "stock_prices"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    high: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    low: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    close: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    adj_close: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="stock_prices")

    __table_args__ = (
        UniqueConstraint("company_id", "price_date", name="uq_stock_prices_company_date"),
        Index("idx_sp_company_date", "company_id", "price_date"),
        Index("idx_sp_date", "price_date"),
    )


# ── 5. events ─────────────────────────────────────────────────
class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    industry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("industries.id", ondelete="SET NULL"))
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    event_type: Mapped[Optional[str]] = mapped_column(String(50))
    sentiment: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    raw_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped["Source"] = relationship("Source", back_populates="events")
    industry: Mapped[Optional["Industry"]] = relationship("Industry", back_populates="events")
    company: Mapped[Optional["Company"]] = relationship("Company", back_populates="events")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('policy','earnings','macro','geopolitical','supply_chain','rate','commodity','other')",
            name="ck_events_type",
        ),
        Index("idx_events_source", "source_id"),
        Index("idx_events_industry", "industry_id"),
        Index("idx_events_company", "company_id"),
        Index("idx_events_occurred", "occurred_at"),
        Index("idx_events_type", "event_type"),
    )

    def recency_decay(self, days_since: float, lam: float = 0.05) -> float:
        return math.exp(-lam * days_since)


# ── 6. causal_edges ───────────────────────────────────────────
class CausalEdge(Base):
    __tablename__ = "causal_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_id: Mapped[int] = mapped_column(Integer, nullable=False)
    to_type: Mapped[str] = mapped_column(String(20), nullable=False)
    to_id: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.5)
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_triggered: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("from_type IN ('event','industry','company')", name="ck_causal_from_type"),
        CheckConstraint("to_type IN ('event','industry','company')", name="ck_causal_to_type"),
        CheckConstraint("direction IN (1,-1)", name="ck_causal_direction"),
        Index("idx_causal_from", "from_type", "from_id"),
        Index("idx_causal_to", "to_type", "to_id"),
        Index("idx_causal_weight", "weight"),
    )

    def update_weight(self, error: float, learning_rate: float, confidence_factor: float) -> float:
        """W_new = W_old + α × ε × confidence_factor"""
        new_weight = float(self.weight) + learning_rate * error * confidence_factor
        self.weight = max(0.0, min(1.0, new_weight))
        return float(self.weight)


# ── 7. decisions ──────────────────────────────────────────────
class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)
    event_score: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    predicted_weight: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    logic_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="decisions")
    outcome: Mapped[Optional["Outcome"]] = relationship("Outcome", back_populates="decision", uselist=False)
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="decision")

    __table_args__ = (
        CheckConstraint("signal IN ('BUY','SELL','HOLD')", name="ck_decisions_signal"),
        Index("idx_decisions_company", "company_id"),
        Index("idx_decisions_signal", "signal"),
        Index("idx_decisions_decided", "decided_at"),
    )


# ── 8. outcomes ───────────────────────────────────────────────
class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id", ondelete="RESTRICT"), nullable=False, unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    price_at_decision: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    price_at_outcome: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    actual_return: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    actual_weight: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    evaluation_note: Mapped[Optional[str]] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    decision: Mapped["Decision"] = relationship("Decision", back_populates="outcome")
    weight_histories: Mapped[list["WeightHistory"]] = relationship("WeightHistory", back_populates="trigger_outcome")

    __table_args__ = (
        Index("idx_outcomes_decision", "decision_id"),
        Index("idx_outcomes_company", "company_id"),
        Index("idx_outcomes_correct", "is_correct"),
        Index("idx_outcomes_evaluated", "evaluated_at"),
    )


# ── 9. weight_history ─────────────────────────────────────────
class WeightHistory(Base):
    __tablename__ = "weight_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_before: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    weight_after: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    # delta는 DB에서 GENERATED ALWAYS AS 컬럼이므로 ORM에서는 읽기 전용
    delta: Mapped[Optional[float]] = mapped_column(Numeric(6, 4), server_default=None)
    learning_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    error: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    confidence_factor: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    trigger_outcome_id: Mapped[Optional[int]] = mapped_column(ForeignKey("outcomes.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trigger_outcome: Mapped[Optional["Outcome"]] = relationship("Outcome", back_populates="weight_histories")

    __table_args__ = (
        CheckConstraint("entity_type IN ('causal_edge','source')", name="ck_wh_entity_type"),
        Index("idx_wh_entity", "entity_type", "entity_id"),
        Index("idx_wh_changed", "changed_at"),
        Index("idx_wh_outcome", "trigger_outcome_id"),
    )


# ── 10. positions ─────────────────────────────────────────────
class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_buy_price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="positions")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="position")

    __table_args__ = (
        CheckConstraint("mode IN ('paper','live')", name="ck_positions_mode"),
        Index("idx_positions_company", "company_id"),
        Index("idx_positions_mode", "mode"),
        Index("idx_positions_open", "is_open"),
    )

    def unrealized_pnl(self, current_price: float) -> float:
        if self.avg_buy_price is None:
            return 0.0
        return (current_price - float(self.avg_buy_price)) * self.quantity


# ── 11. trades ────────────────────────────────────────────────
class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    decision_id: Mapped[Optional[int]] = mapped_column(ForeignKey("decisions.id", ondelete="SET NULL"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    side: Mapped[str] = mapped_column(String(5), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(14, 4))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    position: Mapped[Optional["Position"]] = relationship("Position", back_populates="trades")
    decision: Mapped[Optional["Decision"]] = relationship("Decision", back_populates="trades")
    company: Mapped["Company"] = relationship("Company", back_populates="trades")

    __table_args__ = (
        CheckConstraint("mode IN ('paper','live')", name="ck_trades_mode"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_trades_side"),
        Index("idx_trades_company", "company_id"),
        Index("idx_trades_mode", "mode"),
        Index("idx_trades_executed", "executed_at"),
        Index("idx_trades_position", "position_id"),
        Index("idx_trades_decision", "decision_id"),
    )


# ── 12. backtest_sessions ─────────────────────────────────────
class BacktestSession(Base):
    __tablename__ = "backtest_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    sim_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    sim_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_cash: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    final_cash: Mapped[Optional[float]] = mapped_column(Numeric(16, 2))
    total_return: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    benchmark_return: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    alpha: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    total_trades: Mapped[Optional[int]] = mapped_column(Integer)
    win_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    meta: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    backtest_trades: Mapped[list["BacktestTrade"]] = relationship("BacktestTrade", back_populates="session")

    __table_args__ = (
        Index("idx_bt_sessions_date", "sim_start_date", "sim_end_date"),
    )


# ── 13. backtest_trades ───────────────────────────────────────
class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("backtest_sessions.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    side: Mapped[str] = mapped_column(String(5), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(14, 4))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["BacktestSession"] = relationship("BacktestSession", back_populates="backtest_trades")

    __table_args__ = (
        CheckConstraint("side IN ('BUY','SELL')", name="ck_bt_trades_side"),
        Index("idx_bt_trades_session", "session_id"),
        Index("idx_bt_trades_company", "company_id"),
        Index("idx_bt_trades_date", "trade_date"),
    )
