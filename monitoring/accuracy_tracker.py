"""정확도 추적기 (Accuracy Tracker).

역할:
1. decisions + outcomes 조인으로 전체/기간별/기업별 정확도 산출
2. 정확도 ≥ LIVE_TRADING_ACCURACY_GATE(80%)이면 실전 전환 가능 신호 반환
3. 소스별 정확도 재채점 트리거 (source.recalculate_grade)
4. --report CLI로 콘솔 리포트 출력

사용:
    python -m monitoring.accuracy_tracker --report
    python -m monitoring.accuracy_tracker --report --days 30
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import settings
from database.db_manager import get_session
from database.models import Company, Decision, Outcome, Source

logger = logging.getLogger(__name__)


@dataclass
class AccuracyReport:
    """정확도 리포트 스냅샷 (메르식+버핏식)."""

    total_evaluated: int
    correct: int
    accuracy: float
    live_gate_passed: bool

    by_signal: dict[str, dict] = field(default_factory=dict)
    by_company: dict[str, dict] = field(default_factory=dict)
    period_days: Optional[int] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 메르식(사건분석) vs 버핏식(투자신호) 분리
    mercer_accuracy: Optional[float] = None
    buffett_accuracy: Optional[float] = None
    mercer_count: Optional[int] = None
    buffett_count: Optional[int] = None

    def summary_lines(self) -> list[str]:
        lines = [
            "=" * 60,
            f"📊 정확도 리포트  ({self.generated_at.strftime('%Y-%m-%d %H:%M')} UTC)",
        ]
        if self.period_days:
            lines.append(f"   기간: 최근 {self.period_days}일")
        lines += [
            "-" * 60,
            f"전체 평가: {self.total_evaluated}건 | 정답: {self.correct}건 | {self.accuracy:.1%}",
            f"실전 전환: {'✅ 가능 (80% 이상)' if self.live_gate_passed else '❌ 불가 (80% 미달)'}",
        ]

        # 메르식 vs 버핏식
        if self.mercer_accuracy is not None:
            lines.append("-" * 60)
            lines.append("[메르식 (사건분석)]")
            lines.append(f"  {self.mercer_count or 0}건 | {self.mercer_accuracy:.1%}")
        if self.buffett_accuracy is not None:
            lines.append("[버핏식 (투자신호)]")
            lines.append(f"  {self.buffett_count or 0}건 | {self.buffett_accuracy:.1%}")

        if self.by_signal:
            lines.append("-" * 60)
            lines.append("[신호별]")
            for sig, d in sorted(self.by_signal.items()):
                lines.append(f"  {sig:4s}  {d['correct']}/{d['total']:3d}  ({d['accuracy']:.1%})")

        if self.by_company:
            lines.append("-" * 60)
            lines.append("[기업별 Top 5]")
            top5 = sorted(self.by_company.items(), key=lambda x: -x[1]["total"])[:5]
            for name, d in top5:
                lines.append(f"  {name[:20]:20s}  {d['correct']}/{d['total']:3d}  ({d['accuracy']:.1%})")

        lines.append("=" * 60)
        return lines


class AccuracyTracker:
    """decisions / outcomes 테이블을 분석해 정확도를 계산한다 (메르식+버핏식)."""

    def __init__(self, session: Session) -> None:
        self._s = session

    # ── 전체 리포트 (메르식+버핏식 분리) ───────────────────────────

    def report(self, *, days: Optional[int] = None) -> AccuracyReport:
        """전체(또는 최근 N일) 정확도 리포트 (메르식+버핏식 분리)."""
        since = self._since(days)

        outcomes = self._fetch_outcomes(since)
        if not outcomes:
            return AccuracyReport(
                total_evaluated=0,
                correct=0,
                accuracy=0.0,
                live_gate_passed=False,
                period_days=days,
            )

        total = len(outcomes)
        correct = sum(1 for o in outcomes if o.is_correct)
        accuracy = correct / total

        # 메르식(사건분석) vs 버핏식(투자신호) 분리
        mercer_acc, mercer_cnt = self._mercer_accuracy(outcomes)
        buffett_acc, buffett_cnt = self._buffett_accuracy(outcomes)

        return AccuracyReport(
            total_evaluated=total,
            correct=correct,
            accuracy=accuracy,
            live_gate_passed=accuracy >= settings.LIVE_TRADING_ACCURACY_GATE,
            by_signal=self._by_signal(outcomes),
            by_company=self._by_company(outcomes),
            period_days=days,
            mercer_accuracy=mercer_acc,
            mercer_count=mercer_cnt,
            buffett_accuracy=buffett_acc,
            buffett_count=buffett_cnt,
        )

    # ── 실전 전환 게이트 ──────────────────────────────────────────

    def can_go_live(self, *, min_samples: int = 20, days: Optional[int] = None) -> bool:
        """최소 min_samples 건 이상이고 정확도 80% 이상이면 True."""
        r = self.report(days=days)
        if r.total_evaluated < min_samples:
            logger.info(
                "실전 전환 불가: 평가 건수 %d < 최소 %d", r.total_evaluated, min_samples
            )
            return False
        return r.live_gate_passed

    # ── 소스 등급 재채점 ──────────────────────────────────────────

    def refresh_source_grades(self) -> int:
        """모든 활성 소스의 등급을 재채점한다. 변경된 소스 수를 반환."""
        sources: list[Source] = self._s.query(Source).filter_by(is_active=True).all()
        changed = 0
        for src in sources:
            old_grade = src.grade
            src.recalculate_grade(
                settings.GRADE_THRESHOLDS,
                settings.GRADE_WEIGHTS,
                settings.MIN_PREDICTIONS_FOR_GRADE,
                settings.NEUTRAL_WEIGHT_BELOW_MIN,
            )
            if src.grade != old_grade:
                changed += 1
                logger.info("소스 등급 변경: %s  %s → %s", src.name, old_grade, src.grade)

            # D등급 연속 3회 → 비활성화
            if src.grade == "D":
                src.consecutive_d_count += 1
                if src.consecutive_d_count >= settings.CONSECUTIVE_D_DISABLE:
                    src.is_active = False
                    logger.warning("소스 자동 비활성화: %s (D등급 %d회 연속)", src.name, src.consecutive_d_count)
            else:
                src.consecutive_d_count = 0

        self._s.flush()
        return changed

    # ── 메르식 vs 버핏식 ──────────────────────────────────────────

    def _mercer_accuracy(self, outcomes: list[Outcome]) -> tuple[Optional[float], Optional[int]]:
        """메르식 정확도: 사건 감지 + 인과관계 분석.

        confidence가 높을수록 "사건 감지가 명확했다"는 의미.
        confidence >= 0.6이면 메르식 고신뢰도.
        """
        mercer_outcomes = [o for o in outcomes if o.decision and o.decision.confidence >= 0.6]
        if not mercer_outcomes:
            return None, None
        correct = sum(1 for o in mercer_outcomes if o.is_correct)
        return correct / len(mercer_outcomes), len(mercer_outcomes)

    def _buffett_accuracy(self, outcomes: list[Outcome]) -> tuple[Optional[float], Optional[int]]:
        """버핏식 정확도: 투자 신호 + 수익률 달성도.

        actual_weight가 predicted_weight에 가까우면 "투자 신호가 정확했다".
        단순히 is_correct만 봐서는 부족, weight 편차도 함께 보면 좋음.
        현재는 is_correct만 사용하되, 나중에 weight_delta 추가 가능.
        """
        buffett_outcomes = [o for o in outcomes if o.decision and o.decision.confidence < 0.6]
        if not buffett_outcomes:
            return None, None
        correct = sum(1 for o in buffett_outcomes if o.is_correct)
        return correct / len(buffett_outcomes), len(buffett_outcomes)

    # ── 내부 ─────────────────────────────────────────────────────

    def _since(self, days: Optional[int]) -> Optional[datetime]:
        if days is None:
            return None
        return datetime.now(timezone.utc) - timedelta(days=days)

    def _fetch_outcomes(self, since: Optional[datetime]) -> list[Outcome]:
        q = self._s.query(Outcome).filter(Outcome.is_correct.isnot(None))
        if since:
            q = q.filter(Outcome.evaluated_at >= since)
        return q.all()

    def _by_signal(self, outcomes: list[Outcome]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for o in outcomes:
            decision: Decision = self._s.get(Decision, o.decision_id)
            if decision is None:
                continue
            sig = decision.signal
            bucket = result.setdefault(sig, {"total": 0, "correct": 0})
            bucket["total"] += 1
            if o.is_correct:
                bucket["correct"] += 1
        for d in result.values():
            d["accuracy"] = d["correct"] / d["total"] if d["total"] else 0.0
        return result

    def _by_company(self, outcomes: list[Outcome]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for o in outcomes:
            company: Company = self._s.get(Company, o.company_id)
            name = company.name if company else f"id={o.company_id}"
            bucket = result.setdefault(name, {"total": 0, "correct": 0})
            bucket["total"] += 1
            if o.is_correct:
                bucket["correct"] += 1
        for d in result.values():
            d["accuracy"] = d["correct"] / d["total"] if d["total"] else 0.0
        return result


# ── CLI ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FTTS 정확도 리포트")
    parser.add_argument("--report", action="store_true", help="리포트 출력")
    parser.add_argument("--days", type=int, default=None, help="최근 N일 (기본: 전체)")
    parser.add_argument("--refresh-grades", action="store_true", help="소스 등급 재채점")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()

    with get_session() as session:
        tracker = AccuracyTracker(session)

        if args.refresh_grades:
            n = tracker.refresh_source_grades()
            print(f"소스 등급 재채점 완료 — {n}개 변경")

        if args.report:
            r = tracker.report(days=args.days)
            print("\n".join(r.summary_lines()))
            if tracker.can_go_live():
                print(">>> 실전 전환 조건 충족! live_trader 활성화를 검토하세요.")
