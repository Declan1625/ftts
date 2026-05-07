"""Self-Feedback Loop.

CLAUDE.md §3 의 핵심 학습식을 구현한다.

    결정 시 예측 가중치: W_predicted(x)
    실제 시장 영향도:   W_actual(y)
    오차:               ε = y - x

    W_new = W_old + α × ε × confidence_factor
        α = settings.LEARNING_RATE
        confidence_factor = 정보원 등급 가중치 (S=1.0 ... D=0.2)

판단 → 결과 → 그래프 가중치 보정 → 정확도 누적 의 사이클을 담당한다.
DB 영속화는 호출자 (db_manager) 가 처리하고, 본 모듈은 순수 계산만 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from config import settings
from core.causal_graph import CausalGraph, EdgeData, Node
from core.weight_engine import DecisionResult


# ── 결과 데이터 클래스 ─────────────────────────────────────────────
@dataclass
class Outcome:
    """매매 판단 이후 시장에서 관측된 결과.

    actual_return: 결정 시점 → 평가 시점의 수익률 (예: +0.03 = +3%)
    is_correct 는 actual_return 의 부호와 decision.signal 의 정합성으로 판정한다.
    """

    decision: DecisionResult
    actual_return: float
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def actual_weight(self) -> float:
        """방향성을 가진 실제 영향도. predicted_weight 와 같은 좌표계로 비교 가능.

        - BUY 가 옳았다 = actual_return > 0 → +|return|
        - SELL 이 옳았다 = actual_return < 0 → +|return| (sell 입장에서는 양의 가치)
        - HOLD 는 절댓값이 작을수록 좋음 → -|return| (작을수록 0 에 가까워짐)
        """
        if self.decision.signal == "BUY":
            return self.actual_return
        if self.decision.signal == "SELL":
            return -self.actual_return
        # HOLD: 변동이 작을수록 정답 → 부호를 뒤집어 magnitude penalty
        return -abs(self.actual_return)

    @property
    def is_correct(self) -> bool:
        """신호가 맞았는지 판정.

        BUY: actual_return > 0
        SELL: actual_return < 0
        HOLD: |actual_return| < HOLD_TOLERANCE (1%)
        """
        HOLD_TOLERANCE = 0.01
        sig = self.decision.signal
        if sig == "BUY":
            return self.actual_return > 0
        if sig == "SELL":
            return self.actual_return < 0
        return abs(self.actual_return) < HOLD_TOLERANCE


@dataclass
class WeightUpdate:
    """엣지 가중치 갱신 1건의 기록 (weight_history 테이블 적재용)."""

    src: Node
    dst: Node
    weight_before: float
    weight_after: float
    delta: float
    learning_rate: float
    error: float
    confidence_factor: float


@dataclass
class FeedbackReport:
    """단일 outcome 처리 결과 요약."""

    outcome: Outcome
    error: float
    is_correct: bool
    updates: list[WeightUpdate] = field(default_factory=list)


# ── 메인 클래스 ────────────────────────────────────────────────────
class SelfFeedback:
    """Self-Review Loop.

    process(outcome) 호출 시:
        1) 오차 ε = actual_weight - predicted_weight 계산
        2) decision.contributing_events 의 모든 엣지에 대해
           W_new = W_old + α × ε × confidence_factor 적용
        3) 정확도 카운터 갱신
        4) FeedbackReport 반환
    """

    def __init__(
        self,
        graph: CausalGraph,
        *,
        learning_rate: Optional[float] = None,
    ) -> None:
        self.graph = graph
        self.learning_rate = (
            settings.LEARNING_RATE if learning_rate is None else float(learning_rate)
        )
        if self.learning_rate <= 0 or self.learning_rate > 1:
            raise ValueError(f"learning_rate must be in (0, 1], got {self.learning_rate}")

        self._total_predictions = 0
        self._correct_predictions = 0

    # ── 누적 통계 ─────────────────────────────────────────────────
    @property
    def total_predictions(self) -> int:
        return self._total_predictions

    @property
    def correct_predictions(self) -> int:
        return self._correct_predictions

    @property
    def accuracy(self) -> float:
        if self._total_predictions == 0:
            return 0.0
        return self._correct_predictions / self._total_predictions

    def passes_live_gate(self) -> bool:
        """정확도가 실전 전환 임계값을 넘었는가."""
        return (
            self._total_predictions >= settings.MIN_PREDICTIONS_FOR_GRADE
            and self.accuracy >= settings.LIVE_TRADING_ACCURACY_GATE
        )

    # ── 핵심 처리 ─────────────────────────────────────────────────
    def process(
        self,
        outcome: Outcome,
        *,
        confidence_factor: float,
    ) -> FeedbackReport:
        """단일 결과를 받아 가중치를 갱신하고 누적 통계에 반영.

        Args:
            outcome: 매매 결정 + 실제 결과
            confidence_factor: 결정에 기여한 정보원의 등급 가중치
                (여러 정보원이면 평균을 호출자가 미리 계산해 전달)
        """
        if not (0.0 <= confidence_factor <= 1.0):
            raise ValueError(f"confidence_factor must be in [0, 1], got {confidence_factor}")

        decision = outcome.decision
        # 부호를 살린 예측 가중치
        signed_predicted = decision.predicted_weight * (
            1 if decision.signal == "BUY" else (-1 if decision.signal == "SELL" else 0)
        )
        # actual_weight 도 BUY/SELL 관점에서 부호가 정의되어 있음
        # 비교는 같은 좌표계: predicted vs actual_return (BUY 기준)
        # 단순화: ε = actual_return - signed_predicted
        error = outcome.actual_return - signed_predicted

        updates: list[WeightUpdate] = []
        for ev_node in decision.contributing_events:
            # ev_node 에서 시작해 company_node 로 향하는 모든 엣지를 찾아 갱신
            updates.extend(
                self._update_path_edges(
                    ev_node, decision.company_node,
                    error=error, confidence_factor=confidence_factor,
                )
            )

        # 통계 갱신
        self._total_predictions += 1
        if outcome.is_correct:
            self._correct_predictions += 1

        return FeedbackReport(
            outcome=outcome,
            error=error,
            is_correct=outcome.is_correct,
            updates=updates,
        )

    # ── 내부: 경로상의 엣지 가중치 갱신 ──────────────────────────
    def _update_path_edges(
        self,
        start: Node,
        target: Node,
        *,
        error: float,
        confidence_factor: float,
        max_depth: int = 4,
    ) -> list[WeightUpdate]:
        """start → target 사이의 모든 엣지에 학습식을 적용.

        DFS 로 도달 가능한 모든 엣지를 후보로 잡되, 각 엣지는 한 번만 갱신한다.
        """
        if start not in self.graph._g or target not in self.graph._g:
            return []

        # target 으로 도달 가능한 경로상의 엣지 집합
        path_edges: set[tuple[Node, Node]] = set()
        self._collect_path_edges(start, target, max_depth, [], path_edges, set())

        updates: list[WeightUpdate] = []
        for src, dst in path_edges:
            edge: Optional[EdgeData] = self.graph.get_edge(src, dst)
            if edge is None:
                continue
            before = float(edge.weight)
            # W_new = W_old + α × ε × confidence_factor
            # direction 을 곱해 인과 방향과 부호를 일치시킨다
            delta = self.learning_rate * error * confidence_factor * edge.direction
            after = max(0.0, min(1.0, before + delta))
            edge.weight = after
            updates.append(WeightUpdate(
                src=src, dst=dst,
                weight_before=before, weight_after=after,
                delta=after - before,
                learning_rate=self.learning_rate,
                error=error,
                confidence_factor=confidence_factor,
            ))
        return updates

    def _collect_path_edges(
        self,
        node: Node,
        target: Node,
        depth_left: int,
        path: list[Node],
        out: set[tuple[Node, Node]],
        visiting: set[Node],
    ) -> bool:
        """node 에서 target 까지의 경로상에 있는 엣지를 out 에 모은다.
        Returns: target 에 도달 가능했는지 여부.
        """
        if depth_left <= 0:
            return False
        if node in visiting:
            return False
        visiting.add(node)
        reached = False
        for nxt in self.graph._g.successors(node):
            if nxt == target:
                out.add((node, nxt))
                reached = True
                continue
            if self._collect_path_edges(nxt, target, depth_left - 1, path + [nxt], out, visiting):
                out.add((node, nxt))
                reached = True
        visiting.discard(node)
        return reached
