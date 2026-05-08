"""monitoring/accuracy_tracker.py 단위 테스트."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from database.models import Company, Decision, Industry, Outcome, Source
from monitoring.accuracy_tracker import AccuracyTracker


@pytest.fixture
def test_data(session):
    """테스트용 기본 데이터 생성."""
    ind = Industry(code="T", name="테스트")
    session.add(ind)
    session.flush()

    src = Source(name="테스트소스", type="news", grade="C", grade_weight=0.4,
                 total_predictions=0, correct_predictions=0, accuracy=0.0)
    session.add(src)

    comp = Company(ticker="T001", name="테스트기업", market="KOSPI", industry_id=ind.id)
    session.add(comp)
    session.flush()

    return session, src, comp


def _add_decision_outcome(session, company, signal: str, is_correct: bool, confidence: float = 0.8):
    d = Decision(
        company_id=company.id,
        signal=signal,
        event_score=0.7,
        predicted_weight=0.5,
        confidence=confidence,
        decided_at=datetime.now(timezone.utc),
    )
    session.add(d)
    session.flush()

    o = Outcome(
        decision_id=d.id,
        company_id=company.id,
        is_correct=is_correct,
        evaluated_at=datetime.now(timezone.utc),
    )
    session.add(o)
    session.flush()
    return d, o


def test_empty_report(test_data):
    s, src, comp = test_data
    tracker = AccuracyTracker(s)
    r = tracker.report()
    assert r.total_evaluated == 0
    assert r.accuracy == 0.0
    assert r.live_gate_passed is False


def test_accuracy_calculation(test_data):
    s, src, comp = test_data
    # 8 correct, 2 wrong → 80%
    for _ in range(8):
        _add_decision_outcome(s, comp, "BUY", True)
    for _ in range(2):
        _add_decision_outcome(s, comp, "BUY", False)

    tracker = AccuracyTracker(s)
    r = tracker.report()

    assert r.total_evaluated == 10
    assert r.correct == 8
    assert abs(r.accuracy - 0.8) < 1e-6
    assert r.live_gate_passed is True


def test_below_gate(test_data):
    s, src, comp = test_data
    for _ in range(7):
        _add_decision_outcome(s, comp, "BUY", True)
    for _ in range(3):
        _add_decision_outcome(s, comp, "BUY", False)

    tracker = AccuracyTracker(s)
    r = tracker.report()
    assert r.live_gate_passed is False


def test_by_signal_breakdown(test_data):
    s, src, comp = test_data
    _add_decision_outcome(s, comp, "BUY", True)
    _add_decision_outcome(s, comp, "BUY", False)
    _add_decision_outcome(s, comp, "SELL", True)

    tracker = AccuracyTracker(s)
    r = tracker.report()

    assert "BUY" in r.by_signal
    assert r.by_signal["BUY"]["total"] == 2
    assert r.by_signal["BUY"]["correct"] == 1
    assert "SELL" in r.by_signal


def test_can_go_live_requires_min_samples(test_data):
    s, src, comp = test_data
    # 80% 정확도지만 10건뿐 (min_samples=20)
    for _ in range(8):
        _add_decision_outcome(s, comp, "BUY", True)
    for _ in range(2):
        _add_decision_outcome(s, comp, "BUY", False)

    tracker = AccuracyTracker(s)
    assert tracker.can_go_live(min_samples=20) is False
    assert tracker.can_go_live(min_samples=10) is True


def test_refresh_source_grades_upgrades(test_data):
    s, src, comp = test_data
    # 정확도 95% 소스 → S등급 승격
    src.total_predictions = 20
    src.correct_predictions = 19
    src.accuracy = 0.95
    s.flush()

    tracker = AccuracyTracker(s)
    changed = tracker.refresh_source_grades()

    assert changed == 1
    assert src.grade == "S"


def test_refresh_source_auto_disable(test_data):
    s, src, comp = test_data
    src.total_predictions = 15
    src.correct_predictions = 5
    src.accuracy = 0.33  # D등급
    src.consecutive_d_count = 2  # 이미 2회 연속 D
    s.flush()

    tracker = AccuracyTracker(s)
    tracker.refresh_source_grades()

    assert src.is_active is False
    assert src.consecutive_d_count == 3


def test_summary_lines_format(test_data):
    s, src, comp = test_data
    for _ in range(5):
        _add_decision_outcome(s, comp, "BUY", True)

    tracker = AccuracyTracker(s)
    r = tracker.report()
    lines = r.summary_lines()

    assert any("정확도" in line for line in lines)
    assert any("실전 전환" in line for line in lines)


def test_mercer_accuracy_high_confidence(test_data):
    """메르식: confidence >= 0.6 (사건 감지 명확)."""
    s, src, comp = test_data
    # confidence 0.8 (고신뢰도) → 메르식
    for _ in range(8):
        _add_decision_outcome(s, comp, "BUY", True, confidence=0.8)
    for _ in range(2):
        _add_decision_outcome(s, comp, "BUY", False, confidence=0.8)

    tracker = AccuracyTracker(s)
    r = tracker.report()

    assert r.mercer_count == 10
    assert abs(r.mercer_accuracy - 0.8) < 1e-6


def test_buffett_accuracy_low_confidence(test_data):
    """버핏식: confidence < 0.6 (투자신호 보수적)."""
    s, src, comp = test_data
    # confidence 0.4 (저신뢰도) → 버핏식
    for _ in range(7):
        _add_decision_outcome(s, comp, "BUY", True, confidence=0.4)
    for _ in range(3):
        _add_decision_outcome(s, comp, "BUY", False, confidence=0.4)

    tracker = AccuracyTracker(s)
    r = tracker.report()

    assert r.buffett_count == 10
    assert abs(r.buffett_accuracy - 0.7) < 1e-6


def test_mercer_and_buffett_combined(test_data):
    """메르식과 버핏식 동시 사용."""
    s, src, comp = test_data
    # 메르식: 8/10 = 80%
    for _ in range(8):
        _add_decision_outcome(s, comp, "BUY", True, confidence=0.8)
    for _ in range(2):
        _add_decision_outcome(s, comp, "BUY", False, confidence=0.8)

    # 버핏식: 6/10 = 60%
    for _ in range(6):
        _add_decision_outcome(s, comp, "SELL", True, confidence=0.4)
    for _ in range(4):
        _add_decision_outcome(s, comp, "SELL", False, confidence=0.4)

    tracker = AccuracyTracker(s)
    r = tracker.report()

    assert r.total_evaluated == 20
    assert r.mercer_count == 10
    assert abs(r.mercer_accuracy - 0.8) < 1e-6
    assert r.buffett_count == 10
    assert abs(r.buffett_accuracy - 0.6) < 1e-6
    # 전체: 14/20 = 70%
    assert abs(r.accuracy - 0.7) < 1e-6
