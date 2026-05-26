from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)
    title = Column(String(500), nullable=False)
    body = Column(Text)
    url = Column(String(1000))
    published_at = Column(DateTime(timezone=True))
    collected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed = Column(Boolean, default=False)

    chains = relationship("ButterflyChain", back_populates="event")


class ButterflyChain(Base):
    __tablename__ = "butterfly_chains"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    chain_json = Column(Text, nullable=False)
    final_tickers = Column(Text)
    direction = Column(String(10))
    confidence = Column(Float, default=0.5)
    validated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    event = relationship("Event", back_populates="chains")
    signals = relationship("Signal", back_populates="chain")


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, ForeignKey("butterfly_chains.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(100))
    direction = Column(String(10), nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    executed = Column(Boolean, default=False)

    chain = relationship("ButterflyChain", back_populates="signals")
    trade = relationship("Trade", back_populates="signal", uselist=False)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(100))
    direction = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_at_entry = Column(Float)
    current_price = Column(Float)
    target_price = Column(Float)
    stop_loss_price = Column(Float)
    price_at_exit = Column(Float)
    entered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    exited_at = Column(DateTime(timezone=True))
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    status = Column(String(10), default="open")   # open / closed
    is_correct = Column(Boolean)

    signal = relationship("Signal", back_populates="trade")


class Portfolio(Base):
    """자체 모의투자 포트폴리오 상태"""
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True)
    cash = Column(Float, nullable=False)
    initial_cash = Column(Float, nullable=False)
    realized_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
