"""core.causal_graph 단위 테스트."""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone

# settings.py 가 DATABASE_URL 을 import 시점에 요구하므로 더미 주입
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")

import pytest

from core.causal_graph import CausalGraph, EdgeData


# ── 노드/엣지 검증 ──────────────────────────────────────────────────
class TestNodeValidation:
    def test_invalid_node_type_raises(self):
        g = CausalGraph()
        with pytest.raises(ValueError):
            g.add_node(("invalid_type", 1))

    def test_invalid_node_id_type_raises(self):
        g = CausalGraph()
        with pytest.raises(ValueError):
            g.add_node(("event", "not_int"))  # type: ignore[arg-type]

    def test_valid_node_added(self):
        g = CausalGraph()
        g.add_node(("event", 1))
        assert g.node_count == 1


class TestEdgeData:
    def test_weight_clipped_to_unit_range(self):
        e = EdgeData(weight=1.5, confidence=-0.2, direction=1)
        assert e.weight == 1.0
        assert e.confidence == 0.0

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            EdgeData(direction=2)


# ── 그래프 조작 ─────────────────────────────────────────────────────
class TestAddEdge:
    def test_add_edge_creates_nodes(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.7)
        assert g.node_count == 2
        assert g.edge_count == 1

    def test_self_loop_rejected(self):
        g = CausalGraph()
        with pytest.raises(ValueError):
            g.add_edge(("event", 1), ("event", 1))

    def test_duplicate_edge_increments_observation(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.7)
        data = g.add_edge(("event", 1), ("industry", 10), weight=0.9)
        assert g.edge_count == 1
        assert data.observation_count == 2
        # 가중치는 weight_engine 책임이므로 add_edge 가 임의로 변경하지 않는다
        assert data.weight == 0.7

    def test_get_edge_returns_data(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("company", 100), weight=0.4, direction=-1)
        data = g.get_edge(("event", 1), ("company", 100))
        assert data is not None
        assert data.weight == 0.4
        assert data.direction == -1

    def test_update_edge_weight_clips(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10))
        data = g.update_edge_weight(("event", 1), ("industry", 10), 1.5)
        assert data.weight == 1.0

    def test_update_missing_edge_raises(self):
        g = CausalGraph()
        with pytest.raises(KeyError):
            g.update_edge_weight(("event", 1), ("industry", 10), 0.5)


# ── recency decay ─────────────────────────────────────────────────
class TestRecencyDecay:
    def test_zero_days_returns_one(self):
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        assert CausalGraph.recency_decay(now, now=now, lam=0.05) == pytest.approx(1.0)

    def test_decays_over_time(self):
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        ten_days_ago = now - timedelta(days=10)
        decay = CausalGraph.recency_decay(ten_days_ago, now=now, lam=0.05)
        assert decay == pytest.approx(math.exp(-0.5))

    def test_naive_datetime_assumed_utc(self):
        now = datetime(2026, 5, 7)
        past = datetime(2026, 5, 5)
        decay = CausalGraph.recency_decay(past, now=now, lam=0.05)
        assert decay == pytest.approx(math.exp(-0.1))

    def test_future_clamped_to_zero_days(self):
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        future = now + timedelta(days=5)
        assert CausalGraph.recency_decay(future, now=now, lam=0.05) == pytest.approx(1.0)


# ── 점수 전파 ─────────────────────────────────────────────────────
class TestPropagateScore:
    def test_single_hop_propagation(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.5, direction=1)
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        scores = g.propagate_score(
            ("event", 1),
            base_score=2.0,
            source_grade_weight=1.0,
            occurred_at=now,
            now=now,
            max_depth=3,
        )
        # 2.0 * 1.0 * exp(0) * 0.5 * 1 = 1.0
        assert scores == {("industry", 10): pytest.approx(1.0)}

    def test_multi_hop_chain_multiplies(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.5, direction=1)
        g.add_edge(("industry", 10), ("company", 100), weight=0.4, direction=1)
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        scores = g.propagate_score(
            ("event", 1),
            base_score=1.0,
            source_grade_weight=1.0,
            occurred_at=now, now=now,
            max_depth=3,
        )
        assert scores[("industry", 10)] == pytest.approx(0.5)
        assert scores[("company", 100)] == pytest.approx(0.5 * 0.4)

    def test_negative_direction_flips_sign(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.6, direction=-1)
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        scores = g.propagate_score(
            ("event", 1),
            base_score=1.0, source_grade_weight=1.0,
            occurred_at=now, now=now, max_depth=2,
        )
        assert scores[("industry", 10)] == pytest.approx(-0.6)

    def test_multiple_paths_sum_at_destination(self):
        g = CausalGraph()
        # event 1 → industry 10 → company 100
        # event 1 →             company 100
        g.add_edge(("event", 1), ("industry", 10), weight=0.5)
        g.add_edge(("industry", 10), ("company", 100), weight=0.4)
        g.add_edge(("event", 1), ("company", 100), weight=0.3)
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        scores = g.propagate_score(
            ("event", 1),
            base_score=1.0, source_grade_weight=1.0,
            occurred_at=now, now=now, max_depth=3,
        )
        # 직접 경로: 0.3, 우회 경로: 0.5*0.4=0.2 → 합산 0.5
        assert scores[("company", 100)] == pytest.approx(0.5)

    def test_max_depth_caps_traversal(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.5)
        g.add_edge(("industry", 10), ("company", 100), weight=0.5)
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        scores = g.propagate_score(
            ("event", 1),
            base_score=1.0, source_grade_weight=1.0,
            occurred_at=now, now=now, max_depth=1,
        )
        assert ("industry", 10) in scores
        assert ("company", 100) not in scores

    def test_unknown_start_returns_empty(self):
        g = CausalGraph()
        scores = g.propagate_score(
            ("event", 999),
            base_score=1.0, source_grade_weight=1.0,
            occurred_at=datetime.now(timezone.utc),
            max_depth=3,
        )
        assert scores == {}

    def test_cycle_does_not_loop_forever(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.5)
        g.add_edge(("industry", 10), ("event", 1), weight=0.5)
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        # 종료만 되면 성공
        scores = g.propagate_score(
            ("event", 1),
            base_score=1.0, source_grade_weight=1.0,
            occurred_at=now, now=now, max_depth=4,
        )
        assert isinstance(scores, dict)


# ── 직렬화 ─────────────────────────────────────────────────────────
class TestSerialization:
    def test_roundtrip_preserves_structure(self):
        g = CausalGraph()
        g.add_edge(("event", 1), ("industry", 10), weight=0.7, confidence=0.8, direction=1)
        g.add_edge(("industry", 10), ("company", 100), weight=0.4, confidence=0.6, direction=-1)
        # observation_count 누적 시뮬레이션
        g.add_edge(("event", 1), ("industry", 10))

        records = g.to_records()
        assert len(records) == 2

        g2 = CausalGraph.from_records(records)
        assert g2.edge_count == 2
        e = g2.get_edge(("event", 1), ("industry", 10))
        assert e is not None
        assert e.weight == pytest.approx(0.7)
        assert e.observation_count == 2

    def test_from_records_handles_minimal_input(self):
        g = CausalGraph.from_records([
            {"from_type": "event", "from_id": 1, "to_type": "company", "to_id": 100},
        ])
        assert g.edge_count == 1
        e = g.get_edge(("event", 1), ("company", 100))
        assert e is not None
        assert e.weight == 0.5  # default
