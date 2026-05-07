"""정보원 등급(S~D) 채점.

CLAUDE.md §4 의 룰을 그대로 구현한다.

    초기 등급: 신규 정보원 → C
    최소 유효 예측: 10건 이상

    S: accuracy >= 0.90
    A: accuracy >= 0.75
    B: accuracy >= 0.60
    C: accuracy >= 0.45
    D: accuracy <  0.45

    의사결정 가중치:
        {S:1.0, A:0.8, B:0.6, C:0.4, D:0.2}

    특수 규칙:
        - 10건 미만        : grade_weight = 0.5 (중립)
        - D등급 3회 연속   : 자동 비활성화 + 알림
        - S등급 우선순위 처리 (호출자 책임)

본 모듈은 순수 계산 + state machine. DB 영속화는 호출자 (db_manager) 가 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from config import settings


Grade = Literal["S", "A", "B", "C", "D"]
_GRADE_ORDER: tuple[Grade, ...] = ("S", "A", "B", "C", "D")


# ── 데이터 클래스 ──────────────────────────────────────────────────
@dataclass
class GradingResult:
    """단일 정보원 채점 결과. Source 모델 컬럼과 1:1 매핑된다."""

    grade: Grade
    grade_weight: float
    accuracy: float
    total_predictions: int
    correct_predictions: int
    consecutive_d_count: int
    is_active: bool
    is_neutral: bool   # 표본 부족으로 중립 가중치 적용 중인가
    just_disabled: bool = False  # 이번 채점에서 비활성화로 전환됐는가


# ── 메인 클래스 ────────────────────────────────────────────────────
class SourceGrader:
    """정보원 한 곳에 대해 누적 통계를 받아 등급을 산출한다.

    상태(consecutive_d_count, is_active)는 인스턴스 외부 (DB) 가 보유하고
    매 호출마다 grade(...) 에 입력으로 넣는 패턴을 권장.
    """

    def __init__(
        self,
        *,
        grade_thresholds: Optional[dict[str, float]] = None,
        grade_weights: Optional[dict[str, float]] = None,
        min_predictions: Optional[int] = None,
        neutral_weight: Optional[float] = None,
        consecutive_d_disable: Optional[int] = None,
    ) -> None:
        self.grade_thresholds = grade_thresholds or settings.GRADE_THRESHOLDS
        self.grade_weights = grade_weights or settings.GRADE_WEIGHTS
        self.min_predictions = (
            settings.MIN_PREDICTIONS_FOR_GRADE if min_predictions is None else int(min_predictions)
        )
        self.neutral_weight = (
            settings.NEUTRAL_WEIGHT_BELOW_MIN if neutral_weight is None else float(neutral_weight)
        )
        self.consecutive_d_disable = (
            settings.CONSECUTIVE_D_DISABLE if consecutive_d_disable is None else int(consecutive_d_disable)
        )

        # GRADE_WEIGHTS 누락 키 검증
        for g in _GRADE_ORDER:
            if g not in self.grade_weights:
                raise ValueError(f"grade_weights missing key: {g!r}")
        for g in ("S", "A", "B", "C"):
            if g not in self.grade_thresholds:
                raise ValueError(f"grade_thresholds missing key: {g!r}")

    # ── 1회 채점 ──────────────────────────────────────────────────
    def grade(
        self,
        *,
        total_predictions: int,
        correct_predictions: int,
        previous_grade: Optional[Grade] = None,
        consecutive_d_count: int = 0,
        is_active: bool = True,
    ) -> GradingResult:
        """누적 카운터 → 등급 계산.

        Args:
            total_predictions: 전체 예측 수 (누적)
            correct_predictions: 적중 수 (누적)
            previous_grade: 직전 등급 (consecutive_d 갱신에 사용)
            consecutive_d_count: 직전까지의 연속 D 카운트
            is_active: 현재 활성 상태 (이미 비활성이면 그대로 유지)
        """
        if total_predictions < 0 or correct_predictions < 0:
            raise ValueError("counts must be non-negative")
        if correct_predictions > total_predictions:
            raise ValueError("correct_predictions cannot exceed total_predictions")

        accuracy = (
            correct_predictions / total_predictions if total_predictions > 0 else 0.0
        )

        # 표본 부족: 중립 가중치, 등급은 직전 또는 C
        if total_predictions < self.min_predictions:
            grade: Grade = previous_grade or "C"
            return GradingResult(
                grade=grade,
                grade_weight=self.neutral_weight,
                accuracy=accuracy,
                total_predictions=total_predictions,
                correct_predictions=correct_predictions,
                consecutive_d_count=consecutive_d_count,
                is_active=is_active,
                is_neutral=True,
                just_disabled=False,
            )

        grade = self._grade_from_accuracy(accuracy)

        # 연속 D 처리
        new_consecutive_d = consecutive_d_count + 1 if grade == "D" else 0
        just_disabled = False
        new_is_active = is_active
        if (
            grade == "D"
            and new_consecutive_d >= self.consecutive_d_disable
            and is_active
        ):
            new_is_active = False
            just_disabled = True

        return GradingResult(
            grade=grade,
            grade_weight=self.grade_weights[grade],
            accuracy=accuracy,
            total_predictions=total_predictions,
            correct_predictions=correct_predictions,
            consecutive_d_count=new_consecutive_d,
            is_active=new_is_active,
            is_neutral=False,
            just_disabled=just_disabled,
        )

    # ── 보조 ──────────────────────────────────────────────────────
    def _grade_from_accuracy(self, accuracy: float) -> Grade:
        if accuracy >= self.grade_thresholds["S"]:
            return "S"
        if accuracy >= self.grade_thresholds["A"]:
            return "A"
        if accuracy >= self.grade_thresholds["B"]:
            return "B"
        if accuracy >= self.grade_thresholds["C"]:
            return "C"
        return "D"

    def reactivate(
        self, *, reset_consecutive_d: bool = True
    ) -> tuple[bool, int]:
        """비활성화된 정보원을 재활성화할 때 호출.
        Returns: (is_active, consecutive_d_count)
        """
        return True, (0 if reset_consecutive_d else -1)
