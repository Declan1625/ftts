"""core/mer_ingest.py — JSONL 분석 결과 → DB + CausalGraph 주입.

흐름:
    JSONL 한 줄 (MerPost)
        → Source (정보원) upsert
        → Industry upsert (텍스트 → slug code)
        → Company upsert (텍스트 → ticker 미확정은 name으로 임시 저장)
        → Event insert
        → CausalGraph 엣지 연결
            event → industry (confidence=post.confidence)
            event → company  (confidence=post.confidence)
            industry → company (weight=0.8)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from core.causal_graph import CausalGraph
from database.models import Company, Event, Industry, Source

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^\w가-힣]")

# ── 데이터 클래스 ──────────────────────────────────────────────────

@dataclass
class MerPost:
    post_no: str
    title: str
    published_at: str
    is_investment_related: bool
    events: list[str]
    primary_source: str
    reference_sources: list[str]
    source_correlations: list[dict]
    affected_industries: list[str]
    affected_companies: list[str]
    causal_chain: str
    confidence: float
    summary: str


@dataclass
class IngestResult:
    post_no: str
    source_id: int
    event_ids: list[int]
    industry_ids: list[int]
    company_ids: list[int]
    edges_added: int


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", text.strip())[:20].lower()


def _get_or_create_source(session: Session, name: str) -> Source:
    src = session.query(Source).filter_by(name=name).first()
    if not src:
        src = Source(name=name, type="blog", grade="C", grade_weight=0.40)
        session.add(src)
        session.flush()
    return src


def _get_or_create_industry(session: Session, name: str) -> Industry:
    code = _slug(name)
    ind = session.query(Industry).filter_by(code=code).first()
    if not ind:
        ind = Industry(code=code, name=name)
        session.add(ind)
        session.flush()
    return ind


def _get_or_create_company(session: Session, name: str, industry_id: Optional[int]) -> Company:
    # ticker 미확정 → name을 ticker로 임시 사용 (slug)
    ticker = _slug(name)
    cmp = session.query(Company).filter_by(ticker=ticker).first()
    if not cmp:
        cmp = Company(
            ticker=ticker,
            name=name,
            market="OTHER",
            industry_id=industry_id,
        )
        session.add(cmp)
        session.flush()
    return cmp


def _parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


# ── 핵심 함수 ──────────────────────────────────────────────────────

def ingest_post(session: Session, graph: CausalGraph, post: MerPost) -> IngestResult:
    """MerPost 1개를 DB + CausalGraph에 주입."""

    # 1. 정보원 (primary source)
    primary_src = _get_or_create_source(session, post.primary_source)

    # reference sources도 DB에 등록 (가중치 추적용)
    ref_sources: list[Source] = []
    for rs_name in post.reference_sources:
        ref_sources.append(_get_or_create_source(session, rs_name))

    # 2. 산업
    industries: list[Industry] = [
        _get_or_create_industry(session, name)
        for name in post.affected_industries
    ]

    # 3. 기업 (첫 번째 산업에 연결)
    first_ind_id = industries[0].id if industries else None
    companies: list[Company] = [
        _get_or_create_company(session, name, first_ind_id)
        for name in post.affected_companies
    ]

    # 4. 이벤트 insert (post 내 각 사건 문자열마다 1개)
    occurred_at = _parse_dt(post.published_at)
    event_ids: list[int] = []
    for event_text in post.events:
        ev = Event(
            title=event_text[:500],
            content=post.causal_chain,
            source_id=primary_src.id,
            industry_id=first_ind_id,
            event_type="macro",
            sentiment=post.confidence,
            raw_score=post.confidence,
            occurred_at=occurred_at,
        )
        session.add(ev)
        session.flush()
        event_ids.append(ev.id)

    # 이벤트가 없으면 포스트 자체를 이벤트 1개로
    if not event_ids:
        ev = Event(
            title=post.title[:500],
            content=post.summary,
            source_id=primary_src.id,
            industry_id=first_ind_id,
            event_type="macro",
            sentiment=post.confidence,
            raw_score=post.confidence,
            occurred_at=occurred_at,
        )
        session.add(ev)
        session.flush()
        event_ids.append(ev.id)

    # 5. CausalGraph 엣지 연결
    edges = 0
    direction = 1  # 기본 호재 (신뢰도 기반)

    ind_ids = [ind.id for ind in industries]
    cmp_ids = [cmp.id for cmp in companies]

    for ev_id in event_ids:
        ev_node = ("event", ev_id)
        graph.add_node(ev_node)

        for ind_id in ind_ids:
            graph.add_edge(
                ev_node, ("industry", ind_id),
                weight=post.confidence,
                confidence=post.confidence,
                direction=direction,
            )
            edges += 1

        for cmp_id in cmp_ids:
            graph.add_edge(
                ev_node, ("company", cmp_id),
                weight=post.confidence * 0.8,
                confidence=post.confidence,
                direction=direction,
            )
            edges += 1

    # industry → company 연결
    for ind_id in ind_ids:
        for cmp_id in cmp_ids:
            graph.add_edge(
                ("industry", ind_id), ("company", cmp_id),
                weight=0.8,
                confidence=0.8,
                direction=1,
            )
            edges += 1

    logger.info(
        "ingest post_no=%s events=%d industries=%d companies=%d edges=%d",
        post.post_no, len(event_ids), len(ind_ids), len(cmp_ids), edges,
    )

    return IngestResult(
        post_no=post.post_no,
        source_id=primary_src.id,
        event_ids=event_ids,
        industry_ids=ind_ids,
        company_ids=cmp_ids,
        edges_added=edges,
    )


def ingest_jsonl(
    jsonl_path: str | Path,
    session: Session,
    graph: CausalGraph,
) -> list[IngestResult]:
    """JSONL 파일 전체를 읽어 ingest_post 반복 호출."""
    path = Path(jsonl_path)
    if not path.exists():
        logger.warning("JSONL 파일 없음: %s", path)
        return []

    results: list[IngestResult] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if not d.get("is_investment_related", True):
                continue
            post = MerPost(**{k: d[k] for k in MerPost.__dataclass_fields__})
            result = ingest_post(session, graph, post)
            results.append(result)
        except Exception as exc:
            logger.error("ingest 실패: %s | line=%s", exc, line[:80])

    session.commit()
    logger.info("ingest 완료: %d개 포스트 처리", len(results))
    return results


# ── 정보원 신뢰도 리포트 ───────────────────────────────────────────

def source_report(session: Session) -> list[dict]:
    """현재 DB의 정보원별 등급/정확도 요약."""
    sources = session.query(Source).filter_by(is_active=True).all()
    return [
        {
            "name": s.name,
            "grade": s.grade,
            "grade_weight": float(s.grade_weight),
            "accuracy": float(s.accuracy),
            "total_predictions": s.total_predictions,
            "correct_predictions": s.correct_predictions,
        }
        for s in sorted(sources, key=lambda x: -float(x.grade_weight))
    ]
