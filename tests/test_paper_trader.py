"""trading/paper_trader.py 단위 테스트."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from core.weight_engine import DecisionResult
from trading.paper_trader import PaperTrader, InsufficientCashError
from database.models import Base, Company, Position, Trade, Industry

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    # 테스트용 industry + company 삽입
    ind = Industry(code="TEST", name="테스트산업")
    s.add(ind)
    s.flush()
    company = Company(ticker="TEST001", name="테스트기업", market="KOSPI", industry_id=ind.id)
    s.add(company)
    s.flush()
    yield s
    s.close()


def _make_result(signal: str, confidence: float = 0.8) -> DecisionResult:
    return DecisionResult(
        company_node=("company", 1),
        signal=signal,
        event_score=0.7 if signal == "BUY" else -0.4,
        predicted_weight=0.5,
        confidence=confidence,
    )


def test_buy_reduces_cash(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()
    result = _make_result("BUY", confidence=0.8)

    trade = trader.execute(result, current_price=50_000, company_db_id=company.id)

    assert trade is not None
    assert trade.side == "BUY"
    assert trade.quantity > 0
    assert trader.cash < 10_000_000


def test_buy_creates_open_position(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()
    result = _make_result("BUY")

    trader.execute(result, current_price=10_000, company_db_id=company.id)

    positions = session.query(Position).filter_by(is_open=True).all()
    assert len(positions) == 1
    assert positions[0].quantity > 0


def test_sell_closes_position(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()

    # 먼저 매수
    buy_result = _make_result("BUY")
    trader.execute(buy_result, current_price=10_000, company_db_id=company.id)
    cash_after_buy = trader.cash

    # 그 다음 매도
    sell_result = _make_result("SELL")
    trade = trader.execute(sell_result, current_price=12_000, company_db_id=company.id)

    assert trade is not None
    assert trade.side == "SELL"
    assert trade.realized_pnl > 0  # 12000 > 10000 이므로 이익
    assert trader.cash > cash_after_buy

    pos = session.query(Position).filter_by(company_id=company.id).first()
    assert pos.is_open is False


def test_hold_returns_none(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()
    result = _make_result("HOLD")

    trade = trader.execute(result, current_price=10_000, company_db_id=company.id)
    assert trade is None


def test_sell_without_position_returns_none(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()
    result = _make_result("SELL")

    trade = trader.execute(result, current_price=10_000, company_db_id=company.id)
    assert trade is None


def test_portfolio_value(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()

    buy_result = _make_result("BUY", confidence=1.0)
    trader.execute(buy_result, current_price=10_000, company_db_id=company.id)

    pos = session.query(Position).filter_by(is_open=True).first()
    price_map = {company.id: 12_000}  # 현재가 상승 가정
    value = trader.portfolio_value(price_map)

    expected = trader.cash + 12_000 * pos.quantity
    assert abs(value - expected) < 1


def test_double_buy_averages_price(session):
    trader = PaperTrader(session, initial_cash=10_000_000)
    company = session.query(Company).first()

    buy = _make_result("BUY", confidence=0.5)
    trader.execute(buy, current_price=10_000, company_db_id=company.id)
    qty1 = session.query(Position).filter_by(is_open=True).first().quantity

    trader.execute(buy, current_price=20_000, company_db_id=company.id)
    pos = session.query(Position).filter_by(is_open=True).first()

    assert pos.quantity > qty1
    assert 10_000 < float(pos.avg_buy_price) < 20_000
