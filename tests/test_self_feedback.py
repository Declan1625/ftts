"""core.self_feedback 단위 테스트."""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")

import pytest

from core.causal_graph import CausalGraph
from core.self_feedback import FeedbackReport, Outcome, SelfFeedback, WeightUpdate
from core.weight_engine import DecisionResult, EventInput, WeightEngine


NOW = datetime(2026, 5, 7, tzinfo=timezone.utc)


def _decision(signal: str, score: float, contribs, company=("company", 100)):
    return DecisionResult(
        company_node=company,
        signal=signal,  # type: ignore[arg-type]
        event_score=score,
        predicted_weight=min(1.0, abs(score)),
        confidence=0.7,
        contributing_events=list(contribs),
        snapshot={},
    )


# ── Outcome 의미론 ─────────────────────────────────────────────────
class TestOutcomeSemantics:
    def test_buy_correct_when_return_positive(self):
        d = _decision("BUY", 0.8, [("event", 1)])
        out = Outcome(decision=d, actual_return=0.05)
        assert out.is_correct
        assert out.actual_weight == pytest.approx(0.05)

    def test_buy_wrong_when_return_negative(self):
        d = _decision("BUY", 0.8, [("event", 1)])
        out = Outcome(decision=d, actual_return=-0.03)
        assert not out.is_correct

    def test_sell_correct_when_return_negative(self):
        d = _decision("SELL", -0.8, [("event", 1)])
        out = Outcome(decision=d, actual_return=-0.04)
        assert out.is_correct
        # SELL 입장에서 actual_weight 는 부호 뒤집힘 (양의 가치)
        assert out.actual_weight == pytest.approx(0.04)

    def test_hold_correct_when_return_within_tolerance(self):
        d = _decision("HOLD", 0.0, [])
        out_ok = Outcome(decision=d, actual_return=0.005)
        out_bad = Outcome(decision=d, actual_return=0.05)
        assert out_ok.is_correct
        assert not out_bad.is_correct


# ── 생성자 검증 ────────────────────────────────────────────────────
class TestConstruction:
    def test_invalid_learning_rate(self):
        g = CausalGraph()
        with pytest.raises(ValueError):
            SelfFeedback(g, learning_rate=0.0)
        with pytest.raises(ValueError):
            SelfFeedback(g, learning_rate=1.5)

    def test_invalid_confidence_factor_raises(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5)
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("BUY", 0.5, [("event", 1)])
        with pytest.raises(ValueError):
            fb.process(Outcome(d, actual_return=0.05), confidence_factor=1.5)


# ── 가중치 갱신 식 검증 ────────────────────────────────────────────
class TestWeightUpdate:
    def test_correct_buy_increases_edge_weight(self):
        """BUY 가 옳았다 (+return) → ε > 0 → 엣지 가중치 ↑."""
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5, direction=1)
        fb = SelfFeedback(g, learning_rate=0.1)

        # predicted=+0.4 (BUY 0.4), actual=+0.6 → ε = +0.2
        d = _decision("BUY", 0.4, [("event", 1)])
        out = Outcome(decision=d, actual_return=0.6)
        report = fb.process(out, confidence_factor=1.0)

        edge = g.get_edge(("event", 1), ("company", 100))
        assert edge.weight > 0.5
        # W_new = 0.5 + 0.1 * 0.2 * 1.0 * (+1) = 0.52
        assert edge.weight == pytest.approx(0.52)
        assert len(report.updates) == 1
        u = report.updates[0]
        assert u.weight_before == 0.5
        assert u.weight_after == pytest.approx(0.52)
        assert u.error == pytest.approx(0.2)

    def test_wrong_buy_decreases_edge_weight(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5, direction=1)
        fb = SelfFeedback(g, learning_rate=0.1)

        # predicted=+0.4, actual=-0.2 → ε = -0.6
        d = _decision("BUY", 0.4, [("event", 1)])
        out = Outcome(decision=d, actual_return=-0.2)
        fb.process(out, confidence_factor=1.0)

        edge = g.get_edge(("event", 1), ("company", 100))
        # 0.5 + 0.1*(-0.6)*1.0*1 = 0.44
        assert edge.weight == pytest.approx(0.44)

    def test_negative_direction_inverts_update_sign(self):
        """direction=-1 (악재 전파) 엣지: ε 부호와 반대로 움직여야 함."""
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5, direction=-1)
        fb = SelfFeedback(g, learning_rate=0.1)

        # SELL 신호: signed_predicted = -0.4. actual=-0.6 → ε = -0.2
        d = _decision("SELL", -0.4, [("event", 1)])
        out = Outcome(decision=d, actual_return=-0.6)
        fb.process(out, confidence_factor=1.0)

        edge = g.get_edge(("event", 1), ("company", 100))
        # 0.5 + 0.1*(-0.2)*1.0*(-1) = 0.52
        assert edge.weight == pytest.approx(0.52)

    def test_low_confidence_factor_dampens_update(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5, direction=1)
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("BUY", 0.4, [("event", 1)])
        out = Outcome(decision=d, actual_return=0.6)
        fb.process(out, confidence_factor=0.2)  # D 등급 가중치

        edge = g.get_edge(("event", 1), ("company", 100))
        # 0.5 + 0.1 * 0.2 * 0.2 * 1 = 0.504
        assert edge.weight == pytest.approx(0.504)

    def test_weight_clipped_to_unit_interval(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.95, direction=1)
        fb = SelfFeedback(g, learning_rate=1.0)
        d = _decision("BUY", 0.0, [("event", 1)])
        # 큰 양의 오차로 1.0 초과 시도
        out = Outcome(decision=d, actual_return=1.0)
        fb.process(out, confidence_factor=1.0)
        edge = g.get_edge(("event", 1), ("company", 100))
        assert 0.0 <= edge.weight <= 1.0
        assert edge.weight == 1.0  # 클립

    def test_multi_hop_path_all_edges_updated(self):
        """event → industry → company 3-hop 경로상의 모든 엣지가 갱신되어야 함."""
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.5, direction=1)
        g.add_edge(("industry", 10), ("company", 100), weight=0.4, direction=1)
        fb = SelfFeedback(g, learning_rate=0.1)

        d = _decision("BUY", 0.2, [("event", 1)])
        out = Outcome(decision=d, actual_return=0.4)  # ε = 0.2
        report = fb.process(out, confidence_factor=1.0)

        assert len(report.updates) == 2
        # 두 엣지 모두 ↑
        e1 = g.get_edge(("event", 1), ("industry", 10))
        e2 = g.get_edge(("industry", 10), ("company", 100))
        assert e1.weight > 0.5
        assert e2.weight > 0.4

    def test_unrelated_edges_untouched(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5)
        g.add_edge(("event", 2), ("company", 200), weight=0.3)  # 무관
        fb = SelfFeedback(g, learning_rate=0.1)

        d = _decision("BUY", 0.4, [("event", 1)])
        out = Outcome(decision=d, actual_return=0.6)
        fb.process(out, confidence_factor=1.0)

        unrelated = g.get_edge(("event", 2), ("company", 200))
        assert unrelated.weight == pytest.approx(0.3)


# ── 누적 통계 / 정확도 게이트 ─────────────────────────────────────
class TestAccuracyTracking:
    def test_initial_accuracy_zero(self):
        fb = SelfFeedback(CausalGraph(), learning_rate=0.1)
        assert fb.accuracy == 0.0
        assert fb.total_predictions == 0

    def test_accuracy_accumulates(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5)
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("BUY", 0.4, [("event", 1)])

        # 3건 중 2건 정답
        fb.process(Outcome(d, actual_return=0.05), confidence_factor=1.0)
        fb.process(Outcome(d, actual_return=0.02), confidence_factor=1.0)
        fb.process(Outcome(d, actual_return=-0.03), confidence_factor=1.0)

        assert fb.total_predictions == 3
        assert fb.correct_predictions == 2
        assert fb.accuracy == pytest.approx(2 / 3)

    def test_live_gate_requires_min_predictions(self):
        from config import settings
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5)
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("BUY", 0.4, [("event", 1)])

        # 적은 표본 + 100% 정답이라도 게이트 불통과
        for _ in range(settings.MIN_PREDICTIONS_FOR_GRADE - 1):
            fb.process(Outcome(d, actual_return=0.05), confidence_factor=1.0)
        assert fb.accuracy == 1.0
        assert not fb.passes_live_gate()

    def test_live_gate_passes_when_threshold_met(self):
        from config import settings
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5)
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("BUY", 0.4, [("event", 1)])

        for _ in range(settings.MIN_PREDICTIONS_FOR_GRADE):
            fb.process(Outcome(d, actual_return=0.05), confidence_factor=1.0)
        # 100% > 80%
        assert fb.passes_live_gate()


# ── FeedbackReport 형식 ──────────────────────────────────────────
class TestFeedbackReport:
    def test_report_records_error_and_correctness(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.5)
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("BUY", 0.4, [("event", 1)])
        out = Outcome(decision=d, actual_return=0.6)
        report = fb.process(out, confidence_factor=1.0)

        assert isinstance(report, FeedbackReport)
        assert report.error == pytest.approx(0.2)
        assert report.is_correct is True
        assert all(isinstance(u, WeightUpdate) for u in report.updates)

    def test_no_contributors_means_no_updates(self):
        g = CausalGraph()
        fb = SelfFeedback(g, learning_rate=0.1)
        d = _decision("HOLD", 0.0, [])
        out = Outcome(decision=d, actual_return=0.001)
        report = fb.process(out, confidence_factor=0.5)
        assert report.updates == []
        assert fb.total_predictions == 1
        assert fb.correct_predictions == 1
