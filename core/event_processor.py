"""core/event_processor.py — 이벤트 수집 → NLP 분석 → 인과관계 연결"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from anthropic import Anthropic
from sqlalchemy.orm import Session

from core.causal_graph import CausalGraph
from database.models import Event, Industry, Company
from nlp.entity_linker import link_companies, link_industries
from nlp.event_extractor import extract_events, ExtractedEvent
from nlp.sentiment_analyzer import analyze_with_detail

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


class EventProcessor:
    """이벤트 수집 → 분석 → 인과관계 연결 통합 파이프라인."""

    def __init__(self, session: Session):
        self.session = session
        self.client = Anthropic()
        self.graph = CausalGraph()

    def process_event(
        self,
        raw_text: str,
        source_name: str = "",
        source_id: int | None = None,
        occurred_at: datetime | None = None,
    ) -> dict:
        """
        원본 텍스트 → 이벤트 추출 → 감성 분석 → 엔티티 링킹 → DB 저장 → 인과관계 연결.

        Args:
            raw_text: 원본 텍스트
            source_name: 정보원 이름
            source_id: 정보원 ID (있으면 Event 저장)
            occurred_at: 이벤트 발생 시각 (기본값: now)

        Returns:
            {
                "events": [Event objects, ...],
                "industry_edges": int,
                "company_edges": int,
                "sentiment": float,
            }
        """
        from datetime import datetime, timezone

        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)

        result = {
            "events": [],
            "industry_edges": 0,
            "company_edges": 0,
            "sentiment": 0.0,
        }

        try:
            # 1️⃣ 이벤트 추출
            extracted = extract_events(raw_text, source_name=source_name)
            if not extracted:
                logger.info("이벤트 미검출: %s", source_name)
                return result

            # 2️⃣ 감성 분석
            sentiment_detail = analyze_with_detail(raw_text)
            sentiment = sentiment_detail["score"]
            result["sentiment"] = sentiment

            # 3️⃣ 각 이벤트별 엔티티 링킹 → DB 저장 → 인과관계 연결
            total_ind_edges = 0
            total_cmp_edges = 0
            saved_events = []

            for event in extracted:
                ind_linked = link_industries(self.session, event.affected_industries)
                cmp_linked = link_companies(self.session, event.affected_companies)

                ind_ids = [iid for iid, obj in ind_linked.items() if obj]
                cmp_ids = [cid for cid, obj in cmp_linked.items() if obj]

                # DB에 Event 저장 (source_id가 있으면)
                db_event = None
                if source_id:
                    # event_type 정규화
                    valid_types = {'policy', 'earnings', 'macro', 'geopolitical', 'supply_chain', 'rate', 'commodity', 'other'}
                    normalized_type = event.event_type if event.event_type in valid_types else 'other'

                    db_event = Event(
                        source_id=source_id,
                        title=event.summary,
                        content=raw_text[:2000],
                        event_type=normalized_type,
                        sentiment=sentiment,
                        occurred_at=occurred_at,
                        industry_id=ind_ids[0] if ind_ids else None,
                        company_id=cmp_ids[0] if cmp_ids else None,
                    )
                    self.session.add(db_event)
                    self.session.flush()
                    saved_events.append(db_event)
                    event_id = db_event.id
                else:
                    # 임시 ID 생성
                    event_id = hash((raw_text, event.summary)) % (2**31)

                # 인과관계 연결
                if ind_ids or cmp_ids:
                    ind_ct, cmp_ct = self.graph.auto_connect_event(
                        event_id=event_id,
                        industry_ids=ind_ids,
                        company_ids=cmp_ids,
                        sentiment=sentiment,
                    )
                    total_ind_edges += ind_ct
                    total_cmp_edges += cmp_ct

            self.session.commit()
            result["events"] = saved_events if saved_events else extracted
            result["industry_edges"] = total_ind_edges
            result["company_edges"] = total_cmp_edges

        except Exception as exc:
            logger.error("이벤트 처리 실패: %s", exc)
            self.session.rollback()

        return result

    def sync_graph_to_db(self) -> int:
        """in-memory 그래프를 DB에 동기화.

        Returns:
            동기화된 엣지 개수
        """
        from database.db_manager import upsert_causal_edge

        count = 0

        try:
            for src, dst, edge_data in self.graph.edges():
                upsert_causal_edge(
                    session=self.session,
                    from_type=src[0],
                    from_id=src[1],
                    to_type=dst[0],
                    to_id=dst[1],
                    weight=edge_data.weight,
                    confidence=edge_data.confidence,
                    direction=edge_data.direction,
                    observation_count=edge_data.observation_count,
                )
                count += 1

            self.session.commit()
            logger.info("그래프 DB 동기화 완료: %d 엣지", count)
            return count
        except Exception as exc:
            logger.error("그래프 동기화 실패: %s", exc)
            self.session.rollback()
            return 0

    def apply_industry_hierarchy(self) -> int:
        """산업 내 회사 계층 자동 연결.

        같은 산업의 모든 회사를 연결 (가중치 0.8).

        Returns:
            추가된 엣지 개수
        """
        industries = self.session.query(Industry).all()
        total_edges = 0

        for industry in industries:
            company_ids = [
                c.id for c in self.session.query(Company)
                .filter(Company.industry_id == industry.id, Company.is_active == True)
                .all()
            ]

            if company_ids:
                edges = self.graph.auto_connect_industry_to_companies(
                    industry_id=industry.id,
                    company_ids=company_ids,
                    weight=0.8,
                )
                total_edges += edges

        logger.info("산업-회사 계층 연결: %d 엣지", total_edges)
        return total_edges
