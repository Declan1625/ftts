from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Event(Base):
    """수집된 실제 사건"""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)       # reuters / dart / fed / eia 등
    title = Column(String(500), nullable=False)
    body = Column(Text)
    url = Column(String(1000))
    published_at = Column(DateTime(timezone=True))
    collected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed = Column(Boolean, default=False)

    chains = relationship("ButterflyChain", back_populates="event")


class ButterflyChain(Base):
    """나비효과 체인: 사건 → 파장 경로 → 종목 영향"""
    __tablename__ = "butterfly_chains"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    chain_json = Column(Text, nullable=False)          # [{step, description, affected}]
    final_tickers = Column(Text)                       # "005930,000660" 콤마 구분
    direction = Column(String(10))                     # BUY / SELL
    confidence = Column(Float, default=0.5)
    validated = Column(Boolean, default=False)         # 과거 데이터로 검증됐는지
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    event = relationship("Event", back_populates="chains")
    signals = relationship("Signal", back_populates="chain")


class Signal(Base):
    """매매 신호"""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, ForeignKey("butterfly_chains.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(100))
    direction = Column(String(10), nullable=False)     # BUY / SELL
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    executed = Column(Boolean, default=False)

    chain = relationship("ButterflyChain", back_populates="signals")
    trade = relationship("Trade", back_populates="signal", uselist=False)


class Trade(Base):
    """모의투자 실행 기록"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_at_entry = Column(Float)
    price_at_exit = Column(Float)
    entered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    exited_at = Column(DateTime(timezone=True))
    pnl = Column(Float)                               # 손익
    is_correct = Column(Boolean)

    signal = relationship("Signal", back_populates="trade")
