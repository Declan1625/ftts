"""backtest/buffett_simulator.py 단위 테스트."""

from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    Base, Company, Industry, Source, StockPrice, BacktestSession, BacktestTrade,
)
from backtest.buffett_simulator import (
    BuffettSimulator, _sharpe, _max_drawdown, _win_rate,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()

    ind = Industry(code="T", name="테스트")
    s.add(ind)
    s.flush()

    comp = Company(ticker="T001", name="테스트기업", market="KOSPI", industry_id=ind.id)
    s.add(comp)
    s.flush()

    # 주가 데이터: 2024-01-02 ~ 2024-01-31 (20 거래일)
    start = date(2024, 1, 2)
    price = 10000.0
    cur = start
    while cur <= date(2024, 1, 31):
        if cur.weekday() < 5:
            s.add(StockPrice(
                company_id=comp.id,
                price_date=cur,
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1_000_000,
                adj_close=price,
            ))
            price *= 1.001  # 매일 0.1% 상승
        cur += timedelta(days=1)
    s.flush()

    yield s, comp
    s.close()


# ── 지표 함수 테스트 ──────────────────────────────────────────

def test_sharpe_flat_returns():
    assert _sharpe([0.0] * 10) == 0.0


def test_sharpe_positive():
    returns = [0.01] * 252
    s = _sharpe(returns)
    assert s > 0


def test_max_drawdown_no_drawdown():
    assert _max_drawdown([100, 110, 120, 130]) == 0.0


def test_max_drawdown_basic():
    curve = [100, 120, 80, 90]
    dd = _max_drawdown(curve)
    # 고점 120에서 80으로 → 33.3%
    assert abs(dd - (120 - 80) / 120) < 1e-6


def test_win_rate_all_win(session):
    s, comp = session
    trades = []
    for _ in range(3):
        bt = BacktestTrade(
            session_id=1, company_id=comp.id,
            side="SELL", quantity=10, price=12000,
            realized_pnl=2000, trade_date=date(2024, 1, 5),
        )
        trades.append(bt)
    assert _win_rate(trades) == 1.0


def test_win_rate_mixed(session):
    s, comp = session
    trades = [
        BacktestTrade(session_id=1, company_id=comp.id, side="SELL",
                      quantity=10, price=12000, realized_pnl=2000, trade_date=date(2024, 1, 5)),
        BacktestTrade(session_id=1, company_id=comp.id, side="SELL",
                      quantity=10, price=8000, realized_pnl=-2000, trade_date=date(2024, 1, 6)),
    ]
    assert _win_rate(trades) == 0.5


# ── 시뮬레이터 통합 테스트 ────────────────────────────────────

def test_run_creates_session(session):
    s, comp = session
    sim = BuffettSimulator(s, initial_cash=10_000_000)
    bt = sim.run(date(2024, 1, 2), date(2024, 1, 31))

    assert bt.id is not None
    assert bt.final_cash is not None
    assert bt.total_return is not None


def test_run_no_future_data(session):
    """sim_end 이후 주가를 참조하지 않는지 확인 (미래 참조 차단)."""
    s, comp = session
    # sim_end 이후 주가를 비정상적으로 높게 설정
    s.add(StockPrice(
        company_id=comp.id,
        price_date=date(2024, 2, 1),
        open=999999, high=999999, low=999999, close=999999,
        volume=1, adj_close=999999,
    ))
    s.flush()

    sim = BuffettSimulator(s, initial_cash=10_000_000)
    bt = sim.run(date(2024, 1, 2), date(2024, 1, 31))

    # 최종 현금이 비정상적으로 커지지 않아야 함
    assert bt.final_cash < 999999 * 1000


def test_run_no_events_stays_hold(session):
    """이벤트가 없으면 모든 결정이 HOLD → 거래 0건."""
    s, comp = session
    sim = BuffettSimulator(s, initial_cash=10_000_000)
    bt = sim.run(date(2024, 1, 2), date(2024, 1, 10))

    bt_trades = s.query(BacktestTrade).filter_by(session_id=bt.id).all()
    assert len(bt_trades) == 0
    # 현금 그대로 (거래 없음)
    assert abs(sim.cash - 10_000_000) < 1


def test_run_metrics_in_range(session):
    """성과 지표가 유효한 범위에 있는지 확인."""
    s, comp = session
    sim = BuffettSimulator(s, initial_cash=10_000_000)
    bt = sim.run(date(2024, 1, 2), date(2024, 1, 31))

    assert bt.max_drawdown is not None
    assert 0.0 <= float(bt.max_drawdown) <= 1.0
    assert bt.win_rate is None or 0.0 <= float(bt.win_rate) <= 1.0
