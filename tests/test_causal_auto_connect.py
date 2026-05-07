"""tests/test_causal_auto_connect.py — P2 자동 엣지 생성 테스트"""

import pytest

from core.causal_graph import CausalGraph


class TestAutoConnectEvent:
    def test_auto_connect_event_creates_edges(self):
        graph = CausalGraph()

        ind_ct, cmp_ct = graph.auto_connect_event(
            event_id=1,
            industry_ids=[10, 11],
            company_ids=[100, 101, 102],
            sentiment=0.8,  # 호재
        )

        assert ind_ct == 2
        assert cmp_ct == 3
        assert graph.edge_count == 5

    def test_auto_connect_event_direction_positive(self):
        graph = CausalGraph()
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=0.9,
        )

        edge = graph.get_edge(("event", 1), ("industry", 10))
        assert edge is not None
        assert edge.direction == 1  # 호재 → +1

    def test_auto_connect_event_direction_negative(self):
        graph = CausalGraph()
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=-0.7,
        )

        edge = graph.get_edge(("event", 1), ("industry", 10))
        assert edge is not None
        assert edge.direction == -1  # 악재 → -1

    def test_auto_connect_event_direction_neutral(self):
        graph = CausalGraph()
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=0.0,
        )

        edge = graph.get_edge(("event", 1), ("industry", 10))
        assert edge is not None
        assert edge.direction == 1  # 중립 → +1 (기본값)

    def test_auto_connect_event_confidence_from_sentiment(self):
        graph = CausalGraph()
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=0.5,
        )

        edge = graph.get_edge(("event", 1), ("industry", 10))
        assert edge is not None
        assert edge.confidence == 0.5  # |sentiment| = 0.5


class TestAutoConnectIndustryToCompanies:
    def test_auto_connect_industry_to_companies(self):
        graph = CausalGraph()

        count = graph.auto_connect_industry_to_companies(
            industry_id=10,
            company_ids=[100, 101, 102],
            weight=0.8,
        )

        assert count == 3
        assert graph.edge_count == 3

    def test_auto_connect_industry_creates_correct_edges(self):
        graph = CausalGraph()
        graph.auto_connect_industry_to_companies(
            industry_id=10,
            company_ids=[100, 101],
        )

        edge1 = graph.get_edge(("industry", 10), ("company", 100))
        edge2 = graph.get_edge(("industry", 10), ("company", 101))

        assert edge1 is not None
        assert edge2 is not None
        assert edge1.weight == 0.8
        assert edge2.weight == 0.8


class TestAutoConnectChain:
    def test_chain_event_to_industry_to_company(self):
        graph = CausalGraph()

        # 이벤트 → 산업 연결
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=0.7,
        )

        # 산업 → 기업 연결
        graph.auto_connect_industry_to_companies(
            industry_id=10,
            company_ids=[100, 101],
        )

        # 경로 확인: event → industry → company
        assert graph.get_edge(("event", 1), ("industry", 10)) is not None
        assert graph.get_edge(("industry", 10), ("company", 100)) is not None
        assert graph.get_edge(("industry", 10), ("company", 101)) is not None

        # 총 엣지 개수
        assert graph.edge_count == 3

    def test_propagate_score_through_chain(self):
        from datetime import datetime, timezone

        graph = CausalGraph()

        # 체인 구축
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=0.8,
        )
        graph.auto_connect_industry_to_companies(
            industry_id=10,
            company_ids=[100],
        )

        # 점수 전파
        scores = graph.propagate_score(
            ("event", 1),
            base_score=1.0,
            source_grade_weight=0.8,
            occurred_at=datetime.now(timezone.utc),
            max_depth=3,
        )

        # company 100 까지 점수가 전파되었나?
        assert ("industry", 10) in scores
        assert ("company", 100) in scores
        assert scores[("company", 100)] > 0


class TestEdgeWeights:
    def test_event_to_industry_weight(self):
        graph = CausalGraph()
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[10],
            company_ids=[],
            sentiment=0.5,
        )

        edge = graph.get_edge(("event", 1), ("industry", 10))
        assert edge.weight == 0.7  # 산업 가중치

    def test_event_to_company_weight(self):
        graph = CausalGraph()
        graph.auto_connect_event(
            event_id=1,
            industry_ids=[],
            company_ids=[100],
            sentiment=0.5,
        )

        edge = graph.get_edge(("event", 1), ("company", 100))
        assert edge.weight == 0.6  # 기업 가중치
