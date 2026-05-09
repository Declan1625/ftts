"""가중치 엔진 (Weight Engine).

CausalGraph 위에서 다음 두 가지를 담당한다.

1. 복합 이벤트 스코어링
       event_score = Σ (edge_weight_i × source_grade_i × recency_decay_i)
   여러 이벤트 → 한 기업의 점수를 합산한다.

2. 매매 신호 결정
       score > BUY_THRESHOLD  → BUY
       score < SELL_THRESHOLD → SELL
       그 외                  → HOLD
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal, Optional

from config import settings
from core.causal_graph import CausalGraph, Node


Signal = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class EventInput:
    """스코어링에 들어가는 단일 이벤트.

    - event_node: 그래프상의 이벤트 노드 ('event', event_id)
    - sentiment: -1.0 ~ +1.0 (뉴스 감성). base_score 로 사용.
    - source_grade_weight: settings.GRADE_WEIGHTS[grade] 값
    - occurred_at: 이벤트 발생 시각 (recency decay 계산용)
    """

    event_node: Node
    sentiment: float
    source_grade_weight: float
    occurred_at: datetime

    def __post_init__(self) -> None:
        # frozen dataclass 라 object.__setattr__ 로 클램핑
        s = max(-1.0, min(1.0, float(self.sentiment)))
        gw = max(0.0, min(1.0, float(self.source_grade_weight)))
        object.__setattr__(self, "sentiment", s)
        object.__setattr__(self, "source_grade_weight", gw)


@dataclass
class DecisionResult:
    """매매 판단 결과. logic_snapshot 으로 decisions 테이블에 그대로 저장 가능."""

    company_node: Node
    signal: Signal
    event_score: float
    predicted_weight: float  # 모델이 기대한 |영향도|, [0, 1]
    confidence: float        # 점수의 신뢰도, [0, 1]
    contributing_events: list[Node] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)


class WeightEngine:
    """그래프 + 임계값을 받아 점수/신호를 산출한다."""

    def __init__(
        self,
        graph: CausalGraph,
        *,
        buy_threshold: Optional[float] = None,
        sell_threshold: Optional[float] = None,
        max_propagation_depth: int = 3,
    ) -> None:
        self.graph = graph
        self.buy_threshold = (
            settings.BUY_THRESHOLD if buy_threshold is None else float(buy_threshold)
        )
        self.sell_threshold = (
            settings.SELL_THRESHOLD if sell_threshold is None else float(sell_threshold)
        )
        if self.sell_threshold >= self.buy_threshold:
            raise ValueError(
                f"sell_threshold({self.sell_threshold}) must be < buy_threshold({self.buy_threshold})"
            )
        self.max_propagation_depth = max_propagation_depth

    # ── 점수 계산 ─────────────────────────────────────────────────
    def score_company(
        self,
        company: Node,
        events: Iterable[EventInput],
        *,
        now: Optional[datetime] = None,
    ) -> tuple[float, list[Node]]:
        """주어진 이벤트들이 특정 기업에 미치는 누적 점수를 계산한다.

        Returns:
            (event_score, contributing_event_nodes)
        """
        if company[0] != "company":
            raise ValueError(f"company arg must be ('company', id), got {company!r}")

        total = 0.0
        contributors: list[Node] = []
        for ev in events:
            if ev.event_node[0] != "event":
                raise ValueError(f"event_node must be ('event', id), got {ev.event_node!r}")
            scores = self.graph.propagate_score(
                ev.event_node,
                base_score=ev.sentiment,
                source_grade_weight=ev.source_grade_weight,
                occurred_at=ev.occurred_at,
                now=now,
                max_depth=self.max_propagation_depth,
            )
            contribution = scores.get(company, 0.0)
            if contribution != 0.0:
                total += contribution
                contributors.append(ev.event_node)
        return total, contributors

    # ── 신호 결정 ─────────────────────────────────────────────────
    def decide(
        self,
        company: Node,
        events: Iterable[EventInput],
        *,
        now: Optional[datetime] = None,
    ) -> DecisionResult:
        events = list(events)  # 두 번 순회하므로 materialize
        score, contributors = self.score_company(company, events, now=now)
        signal = self._signal_from_score(score)

        predicted_weight = min(1.0, abs(score))
        # confidence: 기여 이벤트 수가 많을수록 + grade_weight 평균이 높을수록 ↑
        if contributors:
            avg_grade_w = sum(
                ev.source_grade_weight for ev in events if ev.event_node in contributors
            ) / len(contributors)
            # 기여 이벤트 8건 이상이면 saturate
            count_factor = min(1.0, len(contributors) / 8.0)
            confidence = max(0.0, min(1.0, avg_grade_w * count_factor))
        else:
            confidence = 0.0

        snapshot = {
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "max_depth": self.max_propagation_depth,
            "n_events": len(events),
            "n_contributors": len(contributors),
        }
        return DecisionResult(
            company_node=company,
            signal=signal,
            event_score=score,
            predicted_weight=predicted_weight,
            confidence=confidence,
            contributing_events=contributors,
            snapshot=snapshot,
        )

    def _signal_from_score(self, score: float) -> Signal:
        if score > self.buy_threshold:
            return "BUY"
        if score < self.sell_threshold:
            return "SELL"
        return "HOLD"
