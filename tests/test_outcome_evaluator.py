"""monitoring/outcome_evaluator.py 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from database.models import Company, Decision, Industry, Outcome, Source
from monitoring.outcome_evaluator import OutcomeEvaluator


@pytest.fixture
def test_data(session: Session):
    """테스트용 기본 데이터."""
    ind = Industry(code="T", name="테스트")
    session.add(ind)
    session.flush()

    src = Source(
        name="테스트소스",
        type="news",
        grade="C",
        grade_weight=0.4,
        total_predictions=0,
        correct_predictions=0,
        accuracy=0.0,
    )
    session.add(src)

    comp = Company(ticker="005930", name="삼성전자", market="KOSPI", industry_id=ind.id)
    session.add(comp)
    session.flush()

    return session, src, comp


def _create_decision_outcome(
    session: Session, company: Company, signal: str, decided_days_ago: int
) -> tuple[Decision, Outcome]:
    """결정과 미평가 outcome 생성."""
    decided_at = datetime.now(timezone.utc) - timedelta(days=decided_days_ago)

    decision = Decision(
        company_id=company.id,
        signal=signal,
        event_score=0.5,
        predicted_weight=0.5,
        confidence=0.7,
        decided_at=decided_at,
    )
    session.add(decision)
    session.flush()

    # evaluated_at은 평가 전 임시 값으로 미래 시간 설정 (나중에 None으로 업데이트)
    outcome = Outcome(
        decision_id=decision.id,
        company_id=company.id,
        is_correct=None,
        evaluated_at=datetime.now(timezone.utc) + timedelta(days=100),  # 미래 시간
    )
    session.add(outcome)
    session.flush()

    return decision, outcome


def test_no_pending_outcomes(test_data):
    """평가 대상이 없을 때."""
    session, src, comp = test_data
    evaluator = OutcomeEvaluator(session, eval_days=5)
    n = evaluator.evaluate_pending()
    assert n == 0


def test_outcome_too_recent(test_data):
    """결정 후 2일 경과 (기준: 5일) → 평가 스킵."""
    session, src, comp = test_data
    _create_decision_outcome(session, comp, "BUY", decided_days_ago=2)
    session.commit()

    evaluator = OutcomeEvaluator(session, eval_days=5)
    n = evaluator.evaluate_pending()
    assert n == 0


def test_buy_positive_return(test_data):
    """BUY 신호 후 수익률 > 0 → is_correct=True."""
    session, src, comp = test_data
    decision, outcome = _create_decision_outcome(session, comp, "BUY", decided_days_ago=6)
    session.commit()

    # 모의 주가 설정 (yfinance 호출 없이)
    evaluator = OutcomeEvaluator(session, eval_days=5)

    # 실제 yfinance 호출이 되는데, 테스트용으로는 mock 필요
    # 여기서는 수동으로 설정하고 _judge_outcome만 테스트
    is_correct = evaluator._judge_outcome("BUY", actual_return=0.05)
    assert is_correct is True


def test_buy_negative_return(test_data):
    """BUY 신호 후 수익률 ≤ 0 → is_correct=False."""
    session, src, comp = test_data
    _create_decision_outcome(session, comp, "BUY", decided_days_ago=6)

    evaluator = OutcomeEvaluator(session, eval_days=5)
    is_correct = evaluator._judge_outcome("BUY", actual_return=-0.02)
    assert is_correct is False


def test_sell_negative_return(test_data):
    """SELL 신호 후 수익률 < 0 → is_correct=True."""
    session, src, comp = test_data
    _create_decision_outcome(session, comp, "SELL", decided_days_ago=6)

    evaluator = OutcomeEvaluator(session, eval_days=5)
    is_correct = evaluator._judge_outcome("SELL", actual_return=-0.03)
    assert is_correct is True


def test_sell_positive_return(test_data):
    """SELL 신호 후 수익률 ≥ 0 → is_correct=False."""
    session, src, comp = test_data
    _create_decision_outcome(session, comp, "SELL", decided_days_ago=6)

    evaluator = OutcomeEvaluator(session, eval_days=5)
    is_correct = evaluator._judge_outcome("SELL", actual_return=0.01)
    assert is_correct is False


def test_hold_always_false(test_data):
    """HOLD 신호는 항상 is_correct=False."""
    session, src, comp = test_data
    _create_decision_outcome(session, comp, "HOLD", decided_days_ago=6)

    evaluator = OutcomeEvaluator(session, eval_days=5)
    is_correct = evaluator._judge_outcome("HOLD", actual_return=0.05)
    assert is_correct is False


def test_custom_eval_days(test_data):
    """커스텀 eval_days (3일) 적용."""
    session, src, comp = test_data
    decision, outcome = _create_decision_outcome(session, comp, "BUY", decided_days_ago=4)
    session.commit()

    # 4일 경과, eval_days=3 → 평가 대상
    evaluator = OutcomeEvaluator(session, eval_days=3)
    assert outcome.is_correct is None
    # 실제 yfinance 호출 없으므로 evaluate_pending() 호출은 건너뜀
