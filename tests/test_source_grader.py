"""core.source_grader 단위 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")

import pytest

from core.source_grader import GradingResult, SourceGrader


# ── 입력 검증 ──────────────────────────────────────────────────────
class TestInputValidation:
    def test_negative_counts_raise(self):
        sg = SourceGrader()
        with pytest.raises(ValueError):
            sg.grade(total_predictions=-1, correct_predictions=0)
        with pytest.raises(ValueError):
            sg.grade(total_predictions=10, correct_predictions=-1)

    def test_correct_exceeding_total_raises(self):
        sg = SourceGrader()
        with pytest.raises(ValueError):
            sg.grade(total_predictions=5, correct_predictions=10)

    def test_missing_grade_weights_raises(self):
        with pytest.raises(ValueError):
            SourceGrader(grade_weights={"S": 1.0})  # 나머지 키 누락


# ── 표본 부족 케이스 ───────────────────────────────────────────────
class TestBelowMinPredictions:
    def test_neutral_weight_applied(self):
        sg = SourceGrader(min_predictions=10, neutral_weight=0.5)
        r = sg.grade(total_predictions=5, correct_predictions=5)
        assert r.is_neutral is True
        assert r.grade_weight == 0.5

    def test_previous_grade_preserved(self):
        sg = SourceGrader(min_predictions=10)
        r = sg.grade(
            total_predictions=3, correct_predictions=3,
            previous_grade="A",
        )
        assert r.grade == "A"
        assert r.is_neutral

    def test_default_grade_is_C_when_no_previous(self):
        sg = SourceGrader(min_predictions=10)
        r = sg.grade(total_predictions=0, correct_predictions=0)
        assert r.grade == "C"
        assert r.accuracy == 0.0

    def test_consecutive_d_not_incremented_when_neutral(self):
        sg = SourceGrader(min_predictions=10)
        r = sg.grade(
            total_predictions=5, correct_predictions=0,  # 0% 정확도라도
            previous_grade="D", consecutive_d_count=2,
        )
        # 표본 부족이므로 D 판정 자체가 없음 → 카운터 유지
        assert r.consecutive_d_count == 2
        assert r.is_neutral


# ── 등급 경계값 ────────────────────────────────────────────────────
class TestGradeBoundaries:
    @pytest.mark.parametrize("acc,expected", [
        (0.95, "S"),
        (0.90, "S"),  # 경계 포함
        (0.89, "A"),
        (0.75, "A"),  # 경계 포함
        (0.74, "B"),
        (0.60, "B"),
        (0.59, "C"),
        (0.45, "C"),
        (0.44, "D"),
        (0.10, "D"),
    ])
    def test_accuracy_to_grade_mapping(self, acc, expected):
        sg = SourceGrader(min_predictions=10)
        # acc = correct/total → 100건으로 정확히 만들기
        total = 100
        correct = round(acc * total)
        r = sg.grade(total_predictions=total, correct_predictions=correct)
        assert r.grade == expected

    def test_grade_weights_correct(self):
        sg = SourceGrader(min_predictions=10)
        r = sg.grade(total_predictions=100, correct_predictions=95)
        assert r.grade == "S" and r.grade_weight == 1.0

        r = sg.grade(total_predictions=100, correct_predictions=80)
        assert r.grade == "A" and r.grade_weight == 0.8

        r = sg.grade(total_predictions=100, correct_predictions=65)
        assert r.grade == "B" and r.grade_weight == 0.6

        r = sg.grade(total_predictions=100, correct_predictions=50)
        assert r.grade == "C" and r.grade_weight == 0.4

        r = sg.grade(total_predictions=100, correct_predictions=20)
        assert r.grade == "D" and r.grade_weight == 0.2


# ── 연속 D 비활성화 ────────────────────────────────────────────────
class TestConsecutiveDDisable:
    def test_first_d_increments_counter(self):
        sg = SourceGrader(min_predictions=10, consecutive_d_disable=3)
        r = sg.grade(
            total_predictions=100, correct_predictions=20,
            consecutive_d_count=0, is_active=True,
        )
        assert r.grade == "D"
        assert r.consecutive_d_count == 1
        assert r.is_active is True
        assert r.just_disabled is False

    def test_third_consecutive_d_disables(self):
        sg = SourceGrader(min_predictions=10, consecutive_d_disable=3)
        r = sg.grade(
            total_predictions=100, correct_predictions=20,
            consecutive_d_count=2, is_active=True,
        )
        assert r.grade == "D"
        assert r.consecutive_d_count == 3
        assert r.is_active is False
        assert r.just_disabled is True

    def test_non_d_resets_counter(self):
        sg = SourceGrader(min_predictions=10, consecutive_d_disable=3)
        r = sg.grade(
            total_predictions=100, correct_predictions=70,
            consecutive_d_count=2, is_active=True,
        )
        assert r.grade == "B"
        assert r.consecutive_d_count == 0
        assert r.just_disabled is False

    def test_already_disabled_no_double_flag(self):
        """이미 비활성화된 정보원: just_disabled 가 다시 True 가 되면 안 됨."""
        sg = SourceGrader(min_predictions=10, consecutive_d_disable=3)
        r = sg.grade(
            total_predictions=100, correct_predictions=20,
            consecutive_d_count=5, is_active=False,
        )
        assert r.grade == "D"
        assert r.is_active is False
        assert r.just_disabled is False  # 이미 꺼져 있었으므로 새 이벤트 아님


# ── 재활성화 ───────────────────────────────────────────────────────
class TestReactivate:
    def test_reactivate_resets_d_counter(self):
        sg = SourceGrader()
        is_active, d_count = sg.reactivate(reset_consecutive_d=True)
        assert is_active is True
        assert d_count == 0

    def test_reactivate_preserve_counter(self):
        sg = SourceGrader()
        is_active, d_count = sg.reactivate(reset_consecutive_d=False)
        assert is_active is True
        assert d_count == -1  # 기존 값을 호출자가 유지하라는 sentinel


# ── 결과 객체 형식 ─────────────────────────────────────────────────
class TestGradingResultShape:
    def test_returns_dataclass(self):
        sg = SourceGrader()
        r = sg.grade(total_predictions=100, correct_predictions=85)
        assert isinstance(r, GradingResult)
        assert r.accuracy == 0.85
        assert r.total_predictions == 100
        assert r.correct_predictions == 85
