"""monitoring/accuracy_tracker.py 단위 테스트."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Company, Decision, Industry, Outcome, Source
from monitoring.accuracy_tracker import AccuracyTracker


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()

    ind = Industry(code="T", name="테스트")
    s.add(ind)
    s.flush()

    src = Source(name="테스트소스", type="news", grade="C", grade_weight=0.4,
                 total_predictions=0, correct_predictions=0, accuracy=0.0)
    s.add(src)

    comp = Company(ticker="T001", name="테스트기업", market="KOSPI", industry_id=ind.id)
    s.add(comp)
    s.flush()

    yield s, src, comp
    s.close()


def _add_decision_outcome(session, company, signal: str, is_correct: bool):
    d = Decision(
        company_id=company.id,
        signal=signal,
        event_score=0.7,
        predicted_weight=0.5,
        confidence=0.8,
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


def test_empty_report(session):
    s, src, comp = session
    tracker = AccuracyTracker(s)
    r = tracker.report()
    assert r.total_evaluated == 0
    assert r.accuracy == 0.0
    assert r.live_gate_passed is False


def test_accuracy_calculation(session):
    s, src, comp = session
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


def test_below_gate(session):
    s, src, comp = session
    for _ in range(7):
        _add_decision_outcome(s, comp, "BUY", True)
    for _ in range(3):
        _add_decision_outcome(s, comp, "BUY", False)

    tracker = AccuracyTracker(s)
    r = tracker.report()
    assert r.live_gate_passed is False


def test_by_signal_breakdown(session):
    s, src, comp = session
    _add_decision_outcome(s, comp, "BUY", True)
    _add_decision_outcome(s, comp, "BUY", False)
    _add_decision_outcome(s, comp, "SELL", True)

    tracker = AccuracyTracker(s)
    r = tracker.report()

    assert "BUY" in r.by_signal
    assert r.by_signal["BUY"]["total"] == 2
    assert r.by_signal["BUY"]["correct"] == 1
    assert "SELL" in r.by_signal


def test_can_go_live_requires_min_samples(session):
    s, src, comp = session
    # 80% 정확도지만 10건뿐 (min_samples=20)
    for _ in range(8):
        _add_decision_outcome(s, comp, "BUY", True)
    for _ in range(2):
        _add_decision_outcome(s, comp, "BUY", False)

    tracker = AccuracyTracker(s)
    assert tracker.can_go_live(min_samples=20) is False
    assert tracker.can_go_live(min_samples=10) is True


def test_refresh_source_grades_upgrades(session):
    s, src, comp = session
    # 정확도 95% 소스 → S등급 승격
    src.total_predictions = 20
    src.correct_predictions = 19
    src.accuracy = 0.95
    s.flush()

    tracker = AccuracyTracker(s)
    changed = tracker.refresh_source_grades()

    assert changed == 1
    assert src.grade == "S"


def test_refresh_source_auto_disable(session):
    s, src, comp = session
    src.total_predictions = 15
    src.correct_predictions = 5
    src.accuracy = 0.33  # D등급
    src.consecutive_d_count = 2  # 이미 2회 연속 D
    s.flush()

    tracker = AccuracyTracker(s)
    tracker.refresh_source_grades()

    assert src.is_active is False
    assert src.consecutive_d_count == 3


def test_summary_lines_format(session):
    s, src, comp = session
    for _ in range(5):
        _add_decision_outcome(s, comp, "BUY", True)

    tracker = AccuracyTracker(s)
    r = tracker.report()
    lines = r.summary_lines()

    assert any("정확도" in line for line in lines)
    assert any("실전 전환" in line for line in lines)
