"""core.weight_engine 단위 테스트."""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")

import pytest

from core.causal_graph import CausalGraph
from core.weight_engine import DecisionResult, EventInput, WeightEngine


NOW = datetime(2026, 5, 7, tzinfo=timezone.utc)


def _build_graph() -> CausalGraph:
    """공통 fixture: 사건 1 → 산업 10 → 기업 100 (양의 인과)."""
    g = CausalGraph()
    g.add_edge(("event", 1), ("industry", 10), weight=0.5, direction=1)
    g.add_edge(("industry", 10), ("company", 100), weight=0.4, direction=1)
    return g


# ── 입력 검증 ──────────────────────────────────────────────────────
class TestEventInputValidation:
    def test_sentiment_clipped(self):
        e = EventInput(("event", 1), sentiment=2.0, source_grade_weight=1.5,
                       occurred_at=NOW)
        assert e.sentiment == 1.0
        assert e.source_grade_weight == 1.0

    def test_sentiment_negative_clipped(self):
        e = EventInput(("event", 1), sentiment=-2.0, source_grade_weight=-0.5,
                       occurred_at=NOW)
        assert e.sentiment == -1.0
        assert e.source_grade_weight == 0.0


class TestEngineConstruction:
    def test_threshold_order_enforced(self):
        g = _build_graph()
        with pytest.raises(ValueError):
            WeightEngine(g, buy_threshold=0.1, sell_threshold=0.2)

    def test_uses_settings_defaults(self):
        from config import settings
        g = _build_graph()
        eng = WeightEngine(g)
        assert eng.buy_threshold == settings.BUY_THRESHOLD
        assert eng.sell_threshold == settings.SELL_THRESHOLD


# ── 점수 계산 ──────────────────────────────────────────────────────
class TestScoreCompany:
    def test_single_event_chain(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.1, sell_threshold=-0.1)
        ev = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        score, contribs = eng.score_company(("company", 100), [ev], now=NOW)
        assert score == pytest.approx(0.5 * 0.4)
        assert contribs == [("event", 1)]

    def test_multiple_events_summed(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5, direction=1)
        g.add_edge(("event", 2), ("company", 100), weight=0.3, direction=1)
        eng = WeightEngine(g, buy_threshold=0.1, sell_threshold=-0.1)
        evs = [
            EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW),
            EventInput(("event", 2), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW),
        ]
        score, contribs = eng.score_company(("company", 100), evs, now=NOW)
        assert score == pytest.approx(0.8)
        assert len(contribs) == 2

    def test_negative_sentiment_drops_score(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.1, sell_threshold=-0.1)
        ev = EventInput(("event", 1), sentiment=-1.0, source_grade_weight=1.0, occurred_at=NOW)
        score, _ = eng.score_company(("company", 100), [ev], now=NOW)
        assert score < 0

    def test_unrelated_company_yields_zero(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.1, sell_threshold=-0.1)
        ev = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        score, contribs = eng.score_company(("company", 999), [ev], now=NOW)
        assert score == 0.0
        assert contribs == []

    def test_low_grade_weight_reduces_score(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.1, sell_threshold=-0.1)
        ev_full = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        ev_low = EventInput(("event", 1), sentiment=1.0, source_grade_weight=0.2, occurred_at=NOW)
        s_full, _ = eng.score_company(("company", 100), [ev_full], now=NOW)
        s_low, _ = eng.score_company(("company", 100), [ev_low], now=NOW)
        assert s_low < s_full

    def test_non_company_target_raises(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.1, sell_threshold=-0.1)
        ev = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        with pytest.raises(ValueError):
            eng.score_company(("industry", 10), [ev], now=NOW)


# ── 신호 결정 ──────────────────────────────────────────────────────
class TestDecide:
    def test_buy_signal_when_score_above_threshold(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=1.0, direction=1)
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.5)
        ev = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        result = eng.decide(("company", 100), [ev], now=NOW)
        assert result.signal == "BUY"
        assert result.event_score == pytest.approx(1.0)
        assert result.contributing_events == [("event", 1)]

    def test_sell_signal_when_score_below_threshold(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=1.0, direction=1)
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.5)
        ev = EventInput(("event", 1), sentiment=-1.0, source_grade_weight=1.0, occurred_at=NOW)
        result = eng.decide(("company", 100), [ev], now=NOW)
        assert result.signal == "SELL"

    def test_hold_signal_inside_band(self):
        g = _build_graph()  # 약한 체인 (0.2 max)
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.5)
        ev = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        result = eng.decide(("company", 100), [ev], now=NOW)
        assert result.signal == "HOLD"

    def test_predicted_weight_clipped_to_one(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=1.0, direction=1)
        g.add_edge(("event", 2), ("company", 100), weight=1.0, direction=1)
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.5)
        evs = [
            EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW),
            EventInput(("event", 2), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW),
        ]
        result = eng.decide(("company", 100), evs, now=NOW)
        assert result.event_score == pytest.approx(2.0)
        assert result.predicted_weight == 1.0  # clip

    def test_confidence_zero_when_no_contributors(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.5)
        ev = EventInput(("event", 999), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        result = eng.decide(("company", 100), [ev], now=NOW)
        assert result.confidence == 0.0
        assert result.signal == "HOLD"

    def test_confidence_increases_with_contributors(self):
        g = CausalGraph()
        for i in range(1, 5):
            g.add_edge(("event", i), ("company", 100), weight=0.3, direction=1)
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.5)

        ev_few = [EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)]
        ev_many = [
            EventInput(("event", i), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
            for i in range(1, 5)
        ]
        c_few = eng.decide(("company", 100), ev_few, now=NOW).confidence
        c_many = eng.decide(("company", 100), ev_many, now=NOW).confidence
        assert c_many > c_few

    def test_snapshot_records_thresholds(self):
        g = _build_graph()
        eng = WeightEngine(g, buy_threshold=0.5, sell_threshold=-0.3, max_propagation_depth=2)
        ev = EventInput(("event", 1), sentiment=1.0, source_grade_weight=1.0, occurred_at=NOW)
        result = eng.decide(("company", 100), [ev], now=NOW)
        assert result.snapshot["buy_threshold"] == 0.5
        assert result.snapshot["sell_threshold"] == -0.3
        assert result.snapshot["max_depth"] == 2
        assert result.snapshot["n_events"] == 1
