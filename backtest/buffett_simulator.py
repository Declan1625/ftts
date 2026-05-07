"""버핏 블라인드 테스트 시뮬레이터 (Buffett Simulator).

핵심 원칙:
    "해당 시점에 실제로 알 수 있었던 정보만" 사용한다.
    → stock_prices에서 sim_date 이전 데이터만 조회 (미래 참조 차단)

흐름:
    1. BacktestSession 생성
    2. sim_start_date ~ sim_end_date를 하루씩 진행 (타임머신)
    3. 각 날짜에 대해:
       a. 해당 날짜 이전 이벤트로 WeightEngine.decide() 호출
       b. DecisionResult → PaperTrader.execute()
       c. BacktestTrade 기록
    4. 세션 종료 시 성과 지표 계산 (수익률, 샤프, MDD, 승률)

사용:
    python -m backtest.buffett_simulator --start 2024-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from core.causal_graph import CausalGraph
from core.weight_engine import EventInput, WeightEngine
from database.db_manager import get_session
from database.models import (
    BacktestSession, BacktestTrade, Company, Event, StockPrice,
)

logger = logging.getLogger(__name__)


# ── 성과 지표 계산 ─────────────────────────────────────────────

def _sharpe(daily_returns: list[float], risk_free_daily: float = 0.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    var = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean - risk_free_daily) / std * math.sqrt(252)


def _max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _win_rate(trades: list[BacktestTrade]) -> float:
    sells = [t for t in trades if t.side == "SELL" and t.realized_pnl is not None]
    if not sells:
        return 0.0
    wins = sum(1 for t in sells if float(t.realized_pnl) > 0)
    return wins / len(sells)


# ── 시뮬레이터 ────────────────────────────────────────────────

class BuffettSimulator:
    """날짜 순서대로 과거를 재생하며 매매 결정을 내리는 블라인드 테스트 엔진."""

    def __init__(
        self,
        session: Session,
        *,
        initial_cash: float = settings.PAPER_INITIAL_CASH,
        max_depth: int = 3,
    ) -> None:
        self._s = session
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.max_depth = max_depth
        # 보유 포지션: {company_id: {"qty": int, "avg_price": float}}
        self._positions: dict[int, dict] = {}

    def run(
        self,
        sim_start: date,
        sim_end: date,
        *,
        name: Optional[str] = None,
        rebalance_days: int = 5,  # N 거래일마다 포지션 재평가
    ) -> BacktestSession:
        """시뮬레이션을 실행하고 BacktestSession을 반환한다."""
        bt_session = BacktestSession(
            name=name or f"Buffett_{sim_start}_{sim_end}",
            sim_start_date=sim_start,
            sim_end_date=sim_end,
            initial_cash=self.initial_cash,
        )
        self._s.add(bt_session)
        self._s.flush()

        companies: list[Company] = self._s.query(Company).filter_by(is_active=True).all()
        graph = self._build_graph()
        engine = WeightEngine(graph, max_propagation_depth=self.max_depth)

        trading_days = self._trading_days(sim_start, sim_end)
        equity_curve: list[float] = []
        all_bt_trades: list[BacktestTrade] = []

        logger.info("시뮬레이션 시작: %s ~ %s (%d 거래일)", sim_start, sim_end, len(trading_days))

        for i, sim_date in enumerate(trading_days):
            now = datetime(sim_date.year, sim_date.month, sim_date.day, 9, 0, tzinfo=timezone.utc)

            # 가격 맵 (해당 날짜 종가) — 미래 참조 차단
            price_map = self._price_map(companies, sim_date)
            if not price_map:
                continue

            # N일마다 또는 마지막 날에만 매매 결정
            if i % rebalance_days == 0 or sim_date == trading_days[-1]:
                events = self._events_before(sim_date)
                for comp in companies:
                    if comp.id not in price_map:
                        continue
                    price = price_map[comp.id]
                    event_inputs = self._build_event_inputs(events, comp, now)
                    result = engine.decide(("company", comp.id), event_inputs, now=now)

                    if result.signal == "BUY":
                        self._sim_buy(bt_session, comp, price, result.confidence, sim_date, all_bt_trades)
                    elif result.signal == "SELL":
                        self._sim_sell(bt_session, comp, price, sim_date, all_bt_trades)

            # 자산 평가
            equity = self._portfolio_value(price_map)
            equity_curve.append(equity)

        # ── 마지막 날 전량 청산
        final_date = trading_days[-1] if trading_days else sim_end
        price_map = self._price_map(companies, final_date)
        for comp_id, pos in list(self._positions.items()):
            if pos["qty"] > 0 and comp_id in price_map:
                comp = next((c for c in companies if c.id == comp_id), None)
                if comp:
                    self._sim_sell(bt_session, comp, price_map[comp_id], final_date, all_bt_trades, force=True)

        # ── 최종 현금
        final_cash = self.cash
        total_return = (final_cash - self.initial_cash) / self.initial_cash

        # ── 일별 수익률 (equity_curve 기반)
        daily_returns: list[float] = []
        for j in range(1, len(equity_curve)):
            if equity_curve[j - 1] > 0:
                daily_returns.append((equity_curve[j] - equity_curve[j - 1]) / equity_curve[j - 1])

        bt_session.final_cash = final_cash
        bt_session.total_return = total_return
        bt_session.sharpe_ratio = _sharpe(daily_returns)
        bt_session.max_drawdown = _max_drawdown(equity_curve)
        bt_session.total_trades = len(all_bt_trades)
        bt_session.win_rate = _win_rate(all_bt_trades)
        self._s.flush()

        logger.info(
            "시뮬레이션 완료 — 수익률=%.1f%%, 샤프=%.2f, MDD=%.1f%%, 승률=%.1f%%, 거래=%d건",
            total_return * 100,
            float(bt_session.sharpe_ratio or 0),
            float(bt_session.max_drawdown or 0) * 100,
            float(bt_session.win_rate or 0) * 100,
            len(all_bt_trades),
        )
        return bt_session

    # ── 내부: 매매 ────────────────────────────────────────────────

    def _sim_buy(
        self,
        bt_session: BacktestSession,
        comp: Company,
        price: float,
        confidence: float,
        trade_date: date,
        trades: list[BacktestTrade],
    ) -> None:
        invest = self.cash * confidence * 0.15  # 최대 15% 포지션
        qty = int(invest // price)
        if qty <= 0:
            return
        cost = price * qty * 1.00015  # 수수료 포함
        if cost > self.cash:
            return
        self.cash -= cost

        pos = self._positions.setdefault(comp.id, {"qty": 0, "avg_price": 0.0})
        total_qty = pos["qty"] + qty
        pos["avg_price"] = (pos["avg_price"] * pos["qty"] + price * qty) / total_qty
        pos["qty"] = total_qty

        bt = BacktestTrade(
            session_id=bt_session.id,
            company_id=comp.id,
            side="BUY",
            quantity=qty,
            price=price,
            trade_date=trade_date,
        )
        self._s.add(bt)
        trades.append(bt)

    def _sim_sell(
        self,
        bt_session: BacktestSession,
        comp: Company,
        price: float,
        trade_date: date,
        trades: list[BacktestTrade],
        *,
        force: bool = False,
    ) -> None:
        pos = self._positions.get(comp.id)
        if not pos or pos["qty"] <= 0:
            return
        qty = pos["qty"]
        revenue = price * qty * 0.99985  # 수수료 차감
        realized_pnl = (price - pos["avg_price"]) * qty - price * qty * 0.00015
        self.cash += revenue

        pos["qty"] = 0
        pos["avg_price"] = 0.0

        bt = BacktestTrade(
            session_id=bt_session.id,
            company_id=comp.id,
            side="SELL",
            quantity=qty,
            price=price,
            realized_pnl=realized_pnl,
            trade_date=trade_date,
        )
        self._s.add(bt)
        trades.append(bt)

    # ── 내부: 데이터 조회 ─────────────────────────────────────────

    def _build_graph(self) -> CausalGraph:
        """DB의 causal_edges로 그래프 구성. 없으면 빈 그래프 반환."""
        from database.models import CausalEdge
        graph = CausalGraph()
        edges = self._s.query(CausalEdge).all()
        for e in edges:
            graph.add_edge(
                (e.from_type, e.from_id),
                (e.to_type, e.to_id),
                weight=float(e.weight),
                confidence=float(e.confidence),
                direction=e.direction,
            )
        logger.info("인과 그래프 로드 — 엣지 %d개", len(edges))
        return graph

    def _price_map(self, companies: list[Company], sim_date: date) -> dict[int, float]:
        """sim_date 당일 종가. 없으면 가장 최근 이전 종가 사용."""
        result: dict[int, float] = {}
        for comp in companies:
            sp = (
                self._s.query(StockPrice)
                .filter(StockPrice.company_id == comp.id, StockPrice.price_date <= sim_date)
                .order_by(StockPrice.price_date.desc())
                .first()
            )
            if sp:
                result[comp.id] = float(sp.close)
        return result

    def _events_before(self, sim_date: date) -> list[Event]:
        """sim_date 이전(포함)에 발생한 이벤트만 조회 — 미래 참조 차단."""
        cutoff = datetime(sim_date.year, sim_date.month, sim_date.day, 23, 59, tzinfo=timezone.utc)
        return (
            self._s.query(Event)
            .filter(Event.occurred_at <= cutoff)
            .order_by(Event.occurred_at.desc())
            .limit(200)  # 최근 200건만 사용
            .all()
        )

    def _build_event_inputs(
        self,
        events: list[Event],
        comp: Company,
        now: datetime,
    ) -> list[EventInput]:
        from database.models import Source
        inputs = []
        for ev in events:
            if ev.sentiment is None:
                continue
            src: Optional[Source] = self._s.get(Source, ev.source_id)
            grade_weight = float(src.grade_weight) if src else settings.NEUTRAL_WEIGHT_BELOW_MIN
            inputs.append(EventInput(
                event_node=("event", ev.id),
                sentiment=float(ev.sentiment),
                source_grade_weight=grade_weight,
                occurred_at=ev.occurred_at,
            ))
        return inputs

    def _portfolio_value(self, price_map: dict[int, float]) -> float:
        stock_val = sum(
            price_map.get(cid, pos["avg_price"]) * pos["qty"]
            for cid, pos in self._positions.items()
            if pos["qty"] > 0
        )
        return self.cash + stock_val

    @staticmethod
    def _trading_days(start: date, end: date) -> list[date]:
        days = []
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                days.append(cur)
            cur += timedelta(days=1)
        return days


# ── CLI ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="버핏 블라인드 백테스트")
    parser.add_argument("--start", required=True, help="시작일 YYYY-MM-DD")
    parser.add_argument("--end",   required=True, help="종료일 YYYY-MM-DD")
    parser.add_argument("--cash",  type=float, default=None, help="초기 자금 (기본: settings)")
    parser.add_argument("--name",  default=None, help="세션 이름")
    parser.add_argument("--rebalance", type=int, default=5, help="재평가 주기(거래일, 기본 5)")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = _parse_args()
    sim_start = date.fromisoformat(args.start)
    sim_end   = date.fromisoformat(args.end)

    with get_session() as session:
        sim = BuffettSimulator(session, initial_cash=args.cash or settings.PAPER_INITIAL_CASH)
        bt = sim.run(sim_start, sim_end, name=args.name, rebalance_days=args.rebalance)

    print("\n=== 백테스트 결과 ===")
    print(f"기간         : {bt.sim_start_date} ~ {bt.sim_end_date}")
    print(f"초기 자금    : {bt.initial_cash:,.0f}")
    print(f"최종 자금    : {bt.final_cash:,.0f}")
    print(f"총 수익률    : {float(bt.total_return or 0)*100:.2f}%")
    print(f"샤프 지수    : {float(bt.sharpe_ratio or 0):.3f}")
    print(f"최대 낙폭    : {float(bt.max_drawdown or 0)*100:.2f}%")
    print(f"총 거래 건수 : {bt.total_trades}")
    print(f"승률         : {float(bt.win_rate or 0)*100:.1f}%")
