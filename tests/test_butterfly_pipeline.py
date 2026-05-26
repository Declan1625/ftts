"""FTTS 나비효과 파이프라인 자동 QA 테스트
실제 Claude/KIS API 없이 mock으로 핵심 로직 검증.
새 기능 추가/버그 수정 시 여기서 먼저 터져야 한다.
"""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from butterfly.db.models import (
    Base, Event, Signal, Trade, Portfolio,
    ButterflyChain, CausalPattern,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def seeded_db(db):
    """이벤트+체인 공통 픽스처"""
    e = Event(source="fed", title="FOMC 금리결정", processed=True)
    db.add(e); db.flush()
    bc = ButterflyChain(event_id=e.id, chain_json="[]",
                        final_tickers="000660", direction="BUY", confidence=0.8)
    db.add(bc); db.flush()
    db.commit()
    return db, e, bc


# ── 1. 이벤트 점수화 ────────────────────────────────────────────────────────

class TestEventScorer:
    def test_tier1_fomc_high_score(self, db):
        from butterfly.engine.event_scorer import score_event
        e = Event(source="fed", title="FOMC 금리결정 발표", processed=False)
        db.add(e); db.flush()
        assert score_event(e) > 0.8

    def test_source_lowercase_normalization(self, db):
        from butterfly.engine.event_scorer import score_event
        e_upper = Event(source="FED", title="금리결정", processed=False)
        e_lower = Event(source="fed", title="금리결정", processed=False)
        db.add_all([e_upper, e_lower]); db.flush()
        assert abs(score_event(e_upper) - score_event(e_lower)) < 0.001

    def test_quick_sectors_case_insensitive(self):
        from butterfly.engine.event_scorer import quick_sectors
        assert "반도체" in quick_sectors("HBM 수요 급증")
        assert "반도체" in quick_sectors("hbm demand surge")
        assert "정유" in quick_sectors("WTI 유가 급등")

    def test_unknown_source_default_weight(self, db):
        from butterfly.engine.event_scorer import score_event
        e = Event(source="unknown_source", title="테스트", processed=False)
        db.add(e); db.flush()
        assert score_event(e) > 0  # 기본값 0.5로 계산


# ── 2. 패턴 엔진 ────────────────────────────────────────────────────────────

class TestPatternEngine:
    def test_merge_signals_same_direction_averages_conf(self):
        from butterfly.engine.pattern_engine import _merge_signals
        stored = [{"ticker": "000660", "direction": "BUY", "avg_conf": 0.8}]
        _merge_signals(stored, [{"ticker": "000660", "direction": "BUY", "confidence": 0.6}])
        assert stored[0]["direction"] == "BUY"
        assert stored[0]["avg_conf"] == pytest.approx(0.7)

    def test_merge_signals_direction_collision_takes_latest(self):
        from butterfly.engine.pattern_engine import _merge_signals
        stored = [{"ticker": "000660", "direction": "BUY", "avg_conf": 0.8}]
        _merge_signals(stored, [{"ticker": "000660", "direction": "SELL", "confidence": 0.7}])
        assert stored[0]["direction"] == "SELL"
        assert stored[0]["avg_conf"] == pytest.approx(0.7)

    def test_save_and_find_pattern(self, db):
        from butterfly.engine.pattern_engine import save_pattern, find_pattern
        result = {
            "summary": "반도체 이벤트",
            "chain": [],
            "affected_sectors": ["반도체", "배터리"],
            "signals": [{"ticker": "000660", "name": "SK하이닉스",
                         "direction": "BUY", "confidence": 0.8}],
        }
        # occurrence_count >= 2 요건 충족을 위해 2번 저장
        save_pattern(db, result)
        save_pattern(db, result)
        db.commit()
        found = find_pattern(db, ["반도체"])
        assert found is not None
        assert found.occurrence_count >= 2

    def test_find_pattern_below_threshold_returns_none(self, db):
        from butterfly.engine.pattern_engine import find_pattern
        assert find_pattern(db, ["존재하지않는섹터XYZ"]) is None


# ── 3. 드로우다운 가드 ──────────────────────────────────────────────────────

class TestDrawdownGuard:
    def test_no_portfolio_returns_green(self, db):
        from butterfly.trading.drawdown_guard import assess
        dd = assess(db)
        assert dd.level == "GREEN"
        assert dd.trading_allowed is True

    def test_minus_10pct_yellow(self, db):
        from butterfly.trading.drawdown_guard import assess
        db.add(Portfolio(cash=9_000_000, initial_cash=10_000_000, realized_pnl=0))
        db.commit()
        dd = assess(db)
        assert dd.level == "YELLOW"

    def test_minus_15pct_red(self, db):
        from butterfly.trading.drawdown_guard import assess
        db.add(Portfolio(cash=8_500_000, initial_cash=10_000_000, realized_pnl=0))
        db.commit()
        dd = assess(db)
        assert dd.level == "RED"
        assert "STABLE" in dd.allowed_tiers
        assert "HIGH" not in dd.allowed_tiers

    def test_minus_20pct_black_no_trading(self, db):
        from butterfly.trading.drawdown_guard import assess
        db.add(Portfolio(cash=8_000_000, initial_cash=10_000_000, realized_pnl=0))
        db.commit()
        dd = assess(db)
        assert dd.level == "BLACK"
        assert dd.trading_allowed is False

    def test_emergency_close_deducts_cost(self, db):
        from butterfly.trading.drawdown_guard import assess
        p = Portfolio(cash=8_000_000, initial_cash=10_000_000, realized_pnl=0)
        db.add(p); db.flush()
        e = Event(source="fed", title="t", processed=True)
        db.add(e); db.flush()
        bc = ButterflyChain(event_id=e.id, chain_json="[]")
        db.add(bc); db.flush()
        sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                     confidence=0.8, executed=True)
        db.add(sig); db.flush()
        t = Trade(signal_id=sig.id, ticker="000660", direction="BUY",
                  risk_tier="HIGH", quantity=10, price_at_entry=100_000,
                  current_price=80_000, pnl_pct=-20.0, status="open")
        db.add(t); db.commit()

        cash_before = p.cash
        assess(db)
        db.refresh(p)
        # 거래비용(0.25%) 차감 확인
        assert p.cash < cash_before + 80_000 * 10  # 전액보다 적어야 함


# ── 4. 시뮬레이터 풀 사이클 ─────────────────────────────────────────────────

class TestSimulator:
    @pytest.fixture(autouse=True)
    def mock_market(self, monkeypatch):
        import butterfly.trading.simulator as sim
        self._prices = {}
        monkeypatch.setattr(sim, "_is_market_hours", lambda: True)
        monkeypatch.setattr(sim, "_kis", lambda: self)

    def get_price(self, ticker):
        return self._prices.get(ticker, 75_000.0)

    def test_buy_signal_creates_trade(self, seeded_db):
        import butterfly.trading.simulator as sim
        db, e, bc = seeded_db
        self._prices["000660"] = 75_000
        sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                     confidence=0.8, risk_tier="HIGH", executed=False)
        db.add(Portfolio(cash=10_000_000, initial_cash=10_000_000, realized_pnl=0))
        db.add(sig); db.commit()
        sim.run_simulation(db)
        t = db.query(Trade).filter_by(ticker="000660").first()
        assert t is not None
        assert t.status == "open"
        assert t.target_price == round(75_000 * 1.08)
        assert t.stop_loss_price == round(75_000 * 0.95)

    def test_target_hit_closes_correct(self, seeded_db):
        import butterfly.trading.simulator as sim
        db, e, bc = seeded_db
        self._prices["000660"] = 75_000
        db.add(Portfolio(cash=10_000_000, initial_cash=10_000_000, realized_pnl=0))
        sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                     confidence=0.8, risk_tier="HIGH", executed=False)
        db.add(sig); db.commit()
        sim.run_simulation(db)
        t = db.query(Trade).first()
        self._prices["000660"] = t.target_price + 500
        sim.run_simulation(db)
        db.refresh(t)
        assert t.status == "closed"
        assert t.is_correct is True
        assert t.pnl > 0

    def test_stop_loss_closes_incorrect(self, seeded_db):
        import butterfly.trading.simulator as sim
        db, e, bc = seeded_db
        self._prices["000660"] = 75_000
        db.add(Portfolio(cash=10_000_000, initial_cash=10_000_000, realized_pnl=0))
        sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                     confidence=0.8, risk_tier="HIGH", executed=False)
        db.add(sig); db.commit()
        sim.run_simulation(db)
        t = db.query(Trade).first()
        self._prices["000660"] = t.stop_loss_price - 500
        sim.run_simulation(db)
        db.refresh(t)
        assert t.status == "closed"
        assert t.is_correct is False
        assert t.pnl < 0

    def test_sell_signal_closes_open_position(self, seeded_db):
        import butterfly.trading.simulator as sim
        db, e, bc = seeded_db
        self._prices["000660"] = 75_000
        db.add(Portfolio(cash=10_000_000, initial_cash=10_000_000, realized_pnl=0))
        buy_sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                         confidence=0.8, risk_tier="HIGH", executed=False)
        db.add(buy_sig); db.commit()
        sim.run_simulation(db)
        sell_sig = Signal(chain_id=bc.id, ticker="000660", direction="SELL",
                          confidence=0.7, risk_tier="HIGH", executed=False)
        db.add(sell_sig); db.commit()
        sim.run_simulation(db)
        t = db.query(Trade).filter_by(ticker="000660").first()
        db.refresh(t)
        assert t.status == "closed"

    def test_outside_market_hours_skips(self, seeded_db, monkeypatch):
        import butterfly.trading.simulator as sim
        monkeypatch.setattr(sim, "_is_market_hours", lambda: False)
        db, e, bc = seeded_db
        db.add(Portfolio(cash=10_000_000, initial_cash=10_000_000, realized_pnl=0))
        sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                     confidence=0.8, risk_tier="HIGH", executed=False)
        db.add(sig); db.commit()
        result = sim.run_simulation(db)
        assert result == 0
        assert db.query(Trade).count() == 0

    def test_transaction_cost_deducted(self, seeded_db):
        import butterfly.trading.simulator as sim
        from butterfly import config
        db, e, bc = seeded_db
        price = 75_000
        self._prices["000660"] = price
        db.add(Portfolio(cash=10_000_000, initial_cash=10_000_000, realized_pnl=0))
        sig = Signal(chain_id=bc.id, ticker="000660", direction="BUY",
                     confidence=0.8, risk_tier="HIGH", executed=False)
        db.add(sig); db.commit()
        sim.run_simulation(db)
        t = db.query(Trade).first()
        p = db.query(Portfolio).first()
        expected_cost = price * t.quantity * (1 + config.ROUND_TRIP_COST / 2)
        assert abs(p.cash - (10_000_000 - expected_cost)) < 1


# ── 5. 파이프라인 통합 ─────────────────────────────────────────────────────

class TestPipeline:
    def test_process_pending_with_mock_claude(self, db, monkeypatch):
        from butterfly.engine import analyzer
        from butterfly.engine.pipeline import process_pending
        from butterfly.db.models import Signal, ButterflyChain

        mock_result = {
            "summary": "테스트",
            "chain": [],
            "affected_sectors": ["반도체"],
            "signals": [{"ticker": "000660", "name": "SK하이닉스",
                         "direction": "BUY", "confidence": 0.8,
                         "holding_period": "1주", "reason": "테스트"}],
        }
        monkeypatch.setattr(analyzer, "analyze", lambda t, b: mock_result)
        monkeypatch.setattr(analyzer, "analyze_batch", lambda evs: [mock_result] * len(evs))

        for i in range(3):
            db.add(Event(source="fed", title=f"이벤트 {i}", processed=False))
        db.commit()

        processed = process_pending(db)
        assert processed == 3
        assert db.query(ButterflyChain).count() == 3
        assert db.query(Signal).count() == 3
        assert db.query(CausalPattern).count() == 1  # 같은 섹터 → 1개 패턴

    def test_cache_hit_reuses_pattern(self, db, monkeypatch):
        from butterfly.engine import analyzer, pipeline as pipe_mod
        from butterfly.engine.pipeline import process_pending

        call_count = {"n": 0}
        mock_result = {
            "summary": "테스트", "chain": [],
            "affected_sectors": ["반도체"],
            "signals": [{"ticker": "000660", "direction": "BUY",
                         "confidence": 0.8, "name": "SK하이닉스",
                         "holding_period": "1주", "reason": "t"}],
        }
        def counting_batch(evs):
            call_count["n"] += len(evs)
            return [mock_result] * len(evs)

        # pipeline은 _analyzer 모듈 참조 → 모듈 레벨 패치
        monkeypatch.setattr(analyzer, "analyze", lambda t, b: mock_result)
        monkeypatch.setattr(analyzer, "analyze_batch", counting_batch)

        # 1차: Claude 호출로 패턴 생성 (occurrence_count=1)
        db.add(Event(source="fed", title="HBM 첫 이벤트", processed=False))
        db.commit()
        process_pending(db)
        first_calls = call_count["n"]

        # 2차: occurrence_count=1이라 캐시 미스 → Claude 호출 (count=2로 승격)
        db.add(Event(source="fed", title="HBM 두번째 이벤트", processed=False))
        db.commit()
        process_pending(db)
        second_calls = call_count["n"]

        # 3차: occurrence_count=2 → 캐시 히트 → Claude 추가 호출 없음
        db.add(Event(source="fed", title="HBM 세번째 이벤트", processed=False))
        db.commit()
        process_pending(db)
        assert call_count["n"] == second_calls  # 3차는 캐시 히트
