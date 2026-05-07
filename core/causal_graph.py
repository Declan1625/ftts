"""인과관계 지식 그래프 (Causal Knowledge Graph).

[Mer's Logic] 사건 → 산업 → 기업으로 이어지는 인과관계를 그래프로 표현한다.
- 노드: ('event'|'industry'|'company', id)
- 엣지: weight(0~1), confidence(0~1), direction(±1), observation_count

DB의 causal_edges 테이블과 1:1 동기화 가능하지만, 여기서는 in-memory 모델로
가중치 전파 / 점수 계산을 담당한다. 영속화는 weight_engine + db_manager 가 맡는다.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Iterator, Literal, Optional

import networkx as nx

from config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


NodeType = Literal["event", "industry", "company"]
Node = tuple[NodeType, int]

_VALID_NODE_TYPES: frozenset[NodeType] = frozenset({"event", "industry", "company"})


@dataclass
class EdgeData:
    """causal_edges 한 줄에 대응하는 in-memory 표현."""

    weight: float = 0.5
    confidence: float = 0.5
    direction: int = 1  # +1 호재 전파, -1 악재 전파
    observation_count: int = 1
    last_triggered: Optional[datetime] = None
    edge_id: Optional[int] = None  # DB PK (있으면 동기화에 사용)

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError(f"direction must be ±1 (got {self.direction})")
        self.weight = _clip01(self.weight)
        self.confidence = _clip01(self.confidence)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _validate_node(node: Node) -> None:
    if not (isinstance(node, tuple) and len(node) == 2):
        raise ValueError(f"node must be (type, id) tuple, got {node!r}")
    n_type, n_id = node
    if n_type not in _VALID_NODE_TYPES:
        raise ValueError(f"invalid node type: {n_type!r}")
    if not isinstance(n_id, int):
        raise ValueError(f"node id must be int, got {type(n_id).__name__}")


class CausalGraph:
    """방향성 인과 그래프.

    - NetworkX DiGraph 위에 도메인 메서드를 얹은 wrapper.
    - 평행 엣지(같은 from→to)는 단일 엣지로 합쳐 관리한다 (observation_count++).
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ── 그래프 조작 ────────────────────────────────────────────────
    def add_node(self, node: Node) -> None:
        _validate_node(node)
        if node not in self._g:
            self._g.add_node(node)

    def add_edge(
        self,
        src: Node,
        dst: Node,
        *,
        weight: float = 0.5,
        confidence: float = 0.5,
        direction: int = 1,
        edge_id: Optional[int] = None,
    ) -> EdgeData:
        """엣지 추가 또는 기존 엣지의 observation_count 증가.

        - 새 엣지: 주어진 weight/confidence/direction 으로 생성
        - 기존 엣지: observation_count 만 +1 (가중치 변경은 weight_engine 책임)
        """
        _validate_node(src)
        _validate_node(dst)
        if src == dst:
            raise ValueError("self-loop is not allowed")
        self.add_node(src)
        self.add_node(dst)

        if self._g.has_edge(src, dst):
            data: EdgeData = self._g[src][dst]["data"]
            data.observation_count += 1
            data.last_triggered = datetime.now(timezone.utc)
            return data

        data = EdgeData(
            weight=weight,
            confidence=confidence,
            direction=direction,
            observation_count=1,
            last_triggered=datetime.now(timezone.utc),
            edge_id=edge_id,
        )
        self._g.add_edge(src, dst, data=data)
        return data

    def get_edge(self, src: Node, dst: Node) -> Optional[EdgeData]:
        if not self._g.has_edge(src, dst):
            return None
        return self._g[src][dst]["data"]

    def update_edge_weight(self, src: Node, dst: Node, new_weight: float) -> EdgeData:
        data = self.get_edge(src, dst)
        if data is None:
            raise KeyError(f"edge {src} -> {dst} not found")
        data.weight = _clip01(new_weight)
        return data

    def remove_edge(self, src: Node, dst: Node) -> None:
        if self._g.has_edge(src, dst):
            self._g.remove_edge(src, dst)

    # ── 조회 ───────────────────────────────────────────────────────
    @property
    def node_count(self) -> int:
        return self._g.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._g.number_of_edges()

    def successors(self, node: Node) -> Iterator[Node]:
        if node not in self._g:
            return iter(())
        return iter(self._g.successors(node))

    def predecessors(self, node: Node) -> Iterator[Node]:
        if node not in self._g:
            return iter(())
        return iter(self._g.predecessors(node))

    def edges(self) -> Iterator[tuple[Node, Node, EdgeData]]:
        for u, v, attrs in self._g.edges(data=True):
            yield u, v, attrs["data"]

    # ── 도메인 로직: recency / 점수 계산 ───────────────────────────
    @staticmethod
    def recency_decay(occurred_at: datetime, now: Optional[datetime] = None,
                      lam: Optional[float] = None) -> float:
        """exp(-λ * days_since_event). λ 기본값은 settings.RECENCY_DECAY_LAMBDA."""
        if lam is None:
            lam = settings.RECENCY_DECAY_LAMBDA
        if now is None:
            now = datetime.now(timezone.utc)
        # naive datetime 들어오면 UTC 로 가정 (테스트 편의)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        days_since = max(0.0, (now - occurred_at).total_seconds() / 86400.0)
        return math.exp(-lam * days_since)

    def propagate_score(
        self,
        start: Node,
        *,
        base_score: float,
        source_grade_weight: float,
        occurred_at: datetime,
        now: Optional[datetime] = None,
        max_depth: int = 3,
    ) -> dict[Node, float]:
        """이벤트 노드에서 출발해 후속 노드들로 점수를 전파.

        다음 식의 누적값을 각 도달 노드에 기록한다:
            contribution = edge.weight * edge.direction
                         * source_grade_weight
                         * recency_decay(occurred_at)
                         * base_score (depth=1 부터 곱셈 누적)

        같은 노드에 여러 경로가 도달하면 합산한다 (Σ).
        """
        _validate_node(start)
        if start not in self._g:
            return {}
        if max_depth < 1:
            return {}

        decay = self.recency_decay(occurred_at, now=now)
        scores: dict[Node, float] = {}

        # (node, accumulated_factor, depth)
        stack: list[tuple[Node, float, int]] = [(start, 1.0, 0)]
        # 사이클 방지: (node, depth) 단위 방문 (다른 깊이로의 재방문은 허용)
        visited_at_depth: set[tuple[Node, int]] = set()

        while stack:
            node, factor, depth = stack.pop()
            if (node, depth) in visited_at_depth:
                continue
            visited_at_depth.add((node, depth))

            if depth >= max_depth:
                continue

            for nxt in self._g.successors(node):
                edge: EdgeData = self._g[node][nxt]["data"]
                next_factor = factor * edge.weight * edge.direction
                contribution = base_score * source_grade_weight * decay * next_factor
                scores[nxt] = scores.get(nxt, 0.0) + contribution
                stack.append((nxt, next_factor, depth + 1))

        return scores

    # ── 직렬화 / 복원 ──────────────────────────────────────────────
    def to_records(self) -> list[dict]:
        """DB upsert 용 레코드 목록."""
        records: list[dict] = []
        for (s_type, s_id), (d_type, d_id), data in self.edges():
            records.append({
                "from_type": s_type, "from_id": s_id,
                "to_type": d_type, "to_id": d_id,
                "weight": data.weight,
                "confidence": data.confidence,
                "direction": data.direction,
                "observation_count": data.observation_count,
                "last_triggered": data.last_triggered,
                "edge_id": data.edge_id,
            })
        return records

    @classmethod
    def from_records(cls, records: Iterable[dict]) -> "CausalGraph":
        g = cls()
        for r in records:
            src: Node = (r["from_type"], int(r["from_id"]))
            dst: Node = (r["to_type"], int(r["to_id"]))
            data = g.add_edge(
                src, dst,
                weight=float(r.get("weight", 0.5)),
                confidence=float(r.get("confidence", 0.5)),
                direction=int(r.get("direction", 1)),
                edge_id=r.get("edge_id"),
            )
            obs = int(r.get("observation_count", 1))
            data.observation_count = obs
            lt = r.get("last_triggered")
            if isinstance(lt, datetime):
                data.last_triggered = lt
        return g

    # ── 자동 엣지 생성 (이벤트 → 산업/기업 연결) ──────────────────────
    def auto_connect_event(
        self,
        event_id: int,
        industry_ids: list[int],
        company_ids: list[int],
        sentiment: float,
    ) -> tuple[int, int]:
        """이벤트 → 산업/기업 자동 연결.

        Args:
            event_id: 이벤트 ID
            industry_ids: 관련 산업 ID 목록
            company_ids: 관련 기업 ID 목록
            sentiment: -1~1 (호재 +, 악재 -)

        Returns:
            (industry_edges_added, company_edges_added)
        """
        event_node: Node = ("event", event_id)
        self.add_node(event_node)

        ind_count = 0
        for ind_id in industry_ids:
            ind_node: Node = ("industry", ind_id)
            self.add_node(ind_node)
            direction = 1 if sentiment > 0 else (-1 if sentiment < 0 else 1)
            confidence = min(1.0, abs(sentiment))
            self.add_edge(
                event_node, ind_node,
                weight=0.7,
                confidence=confidence,
                direction=direction,
            )
            ind_count += 1

        cmp_count = 0
        for cmp_id in company_ids:
            cmp_node: Node = ("company", cmp_id)
            self.add_node(cmp_node)
            direction = 1 if sentiment > 0 else (-1 if sentiment < 0 else 1)
            confidence = min(1.0, abs(sentiment))
            self.add_edge(
                event_node, cmp_node,
                weight=0.6,
                confidence=confidence,
                direction=direction,
            )
            cmp_count += 1

        return ind_count, cmp_count

    def auto_connect_industry_to_companies(
        self,
        industry_id: int,
        company_ids: list[int],
        weight: float = 0.8,
    ) -> int:
        """산업 → 기업 자동 연결 (산업의 변화가 구성 기업들에 미치는 영향).

        Returns:
            추가된 엣지 개수
        """
        ind_node: Node = ("industry", industry_id)
        self.add_node(ind_node)

        count = 0
        for cmp_id in company_ids:
            cmp_node: Node = ("company", cmp_id)
            self.add_node(cmp_node)
            self.add_edge(
                ind_node, cmp_node,
                weight=weight,
                confidence=0.8,
                direction=1,
            )
            count += 1

        return count
