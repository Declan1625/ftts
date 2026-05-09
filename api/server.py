"""api/server.py — FTTS FastAPI 서버 (n8n → FTTS 연동 엔드포인트)"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database.db_manager import get_session
from core.event_processor import EventProcessor
from core.weight_engine import WeightEngine
from core.causal_graph import CausalGraph
from monitoring.alert_manager import get_alert_manager
from data_collection import blog_scraper
from nlp import mer_analyzer
from core import mer_ingest, ticker_mapper

logger = logging.getLogger(__name__)

app = FastAPI(
    title="FTTS API",
    description="자가 진단형 주식 자동매매 시스템 — n8n 연동 엔드포인트",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response 스키마 ─────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str = Field(..., description="분석할 원문 텍스트")
    source_name: str = Field(default="", description="정보원 이름 (예: 메르블로그, DART, Fed)")
    source_id: Optional[int] = Field(default=None, description="DB 정보원 ID")
    occurred_at: Optional[str] = Field(default=None, description="이벤트 발생 시각 (ISO8601)")
    title: Optional[str] = Field(default=None, description="원문 제목")
    url: Optional[str] = Field(default=None, description="원문 URL")


class SignalResult(BaseModel):
    ticker: str
    company_name: str
    signal: str          # BUY / SELL / HOLD
    score: float
    confidence: float


class AnalyzeResponse(BaseModel):
    status: str
    source_name: str
    sentiment: float
    event_count: int
    industry_edges: int
    company_edges: int
    signals: list[SignalResult]
    summary: str          # Discord에 바로 붙여넣기용 마크다운 요약


class BlogFetchResponse(BaseModel):
    page: int
    post_nos: list[str]


class BlogAnalyzeRequest(BaseModel):
    post_no: str = Field(..., description="블로그 포스트 번호")


class BlogAnalyzeResponse(BaseModel):
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


# ── 헬스체크 ──────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── 핵심 엔드포인트 ───────────────────────────────────────────────

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    """
    n8n에서 수집한 텍스트를 받아 분석 후 매매 신호 반환.

    흐름:
        1. Gemini로 필요한 정보원 판단 & 검색
        2. Claude로 종합 분석
        3. weight_engine으로 매매 신호 산출
        4. Discord 요약
    """
    if not req.text or len(req.text.strip()) < 5:
        raise HTTPException(status_code=400, detail="텍스트가 너무 짧습니다.")

    occurred_at = None
    if req.occurred_at:
        try:
            occurred_at = datetime.fromisoformat(req.occurred_at)
        except ValueError:
            occurred_at = None

    with get_session() as session:
        processor = EventProcessor(session)

        # source_id가 없으면 자동 생성
        if req.source_id is None:
            from database.models import Source
            source = session.query(Source).filter(Source.name == req.source_name).first()
            if not source:
                source = Source(
                    name=req.source_name,
                    type="news",
                    grade="C",
                    is_active=True,
                )
                session.add(source)
                session.flush()
            req.source_id = source.id

        # Claude 분석
        result = processor.process_event(
            raw_text=req.text,
            source_name=req.source_name,
            source_id=req.source_id,
            occurred_at=occurred_at,
        )

        # 3단계: 매매 신호 산출
        engine = WeightEngine(processor.graph)
        signals = _collect_signals(session, engine, processor.graph)

        # 그래프 DB 동기화
        processor.sync_graph_to_db()

    summary = _build_discord_summary(
        title=req.title,
        url=req.url,
        source_name=req.source_name,
        sentiment=result["sentiment"],
        signals=signals,
        event_count=result["event_count"] if "event_count" in result else len(result.get("events", [])),
    )

    # 텔레그램 알림 (BUY/SELL 신호만)
    alert_mgr = get_alert_manager()
    for sig in signals:
        if sig.signal in ("BUY", "SELL"):
            alert_mgr.send_signal_alert(
                ticker=sig.ticker,
                company_name=sig.company_name,
                signal=sig.signal,
                score=sig.score,
                confidence=sig.confidence,
                source_name=req.source_name,
            )

    return AnalyzeResponse(
        status="ok",
        source_name=req.source_name,
        sentiment=round(result["sentiment"], 3),
        event_count=len(result.get("events", [])),
        industry_edges=result["industry_edges"],
        company_edges=result["company_edges"],
        signals=signals,
        summary=summary,
    )


# ── 메르 블로그 크롤링 & 분석 ─────────────────────────────────────

@app.get("/blog/fetch", response_model=BlogFetchResponse)
def blog_fetch(page: int = 1):
    """메르 블로그 특정 페이지의 포스트 번호 목록 반환 (페이지당 30개)."""
    if page < 1:
        raise HTTPException(status_code=400, detail="page는 1 이상이어야 합니다.")

    try:
        all_post_nos = blog_scraper._get_all_post_nos(max_pages=page)
        start = (page - 1) * 30
        end = page * 30
        page_post_nos = all_post_nos[start:end]
        return BlogFetchResponse(page=page, post_nos=page_post_nos)
    except Exception as e:
        logger.error("블로그 목록 수집 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"블로그 목록 수집 실패: {str(e)}")


@app.get("/blog/fetch/all")
def blog_fetch_all(max_pages: int = 50, jsonl_path: str = "/Users/kangbook/Library/Mobile Documents/com~apple~CloudDocs/FTTS/data/raw/mer_analysis.jsonl"):
    """메르 블로그 전체 포스트 번호 목록 반환 (이미 분석된 포스트 제외)."""
    import os
    try:
        post_nos = blog_scraper._get_all_post_nos(max_pages=max_pages)

        # 이미 분석된 post_no 로드
        seen: set[str] = set()
        if os.path.exists(jsonl_path):
            with open(jsonl_path) as f:
                for line in f:
                    try:
                        seen.add(json.loads(line)["post_no"])
                    except Exception:
                        pass

        new_nos = [no for no in post_nos if no not in seen]
        return {"total": len(new_nos), "skipped": len(seen), "post_nos": new_nos}
    except Exception as e:
        logger.error("블로그 전체 목록 수집 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/blog/analyze", response_model=BlogAnalyzeResponse)
def blog_analyze(req: BlogAnalyzeRequest):
    """메르 블로그 포스트를 메르식으로 분석 (사건 → 정보원 → 인과관계)."""
    try:
        post = blog_scraper._fetch_post(req.post_no)
        if not post:
            raise HTTPException(status_code=404, detail=f"포스트를 찾을 수 없습니다: {req.post_no}")

        analysis = mer_analyzer.analyze_mer_blog(
            title=post.title,
            content=post.content,
            source_name="메르 블로그",
        )

        return BlogAnalyzeResponse(
            post_no=req.post_no,
            title=post.title,
            published_at=post.published_at.isoformat(),
            is_investment_related=analysis.is_investment_related,
            events=analysis.events,
            primary_source=analysis.primary_source,
            reference_sources=analysis.reference_sources,
            source_correlations=analysis.source_correlations,
            affected_industries=analysis.affected_industries,
            affected_companies=analysis.affected_companies,
            causal_chain=analysis.causal_chain,
            confidence=analysis.confidence,
            summary=analysis.summary,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("블로그 분석 실패 post_no=%s: %s", req.post_no, e)
        raise HTTPException(status_code=500, detail=f"분석 실패: {str(e)}")


_DEFAULT_JSONL = "/Users/kangbook/Library/Mobile Documents/com~apple~CloudDocs/FTTS/data/raw/mer_analysis.jsonl"


@app.post("/ingest")
def ingest(jsonl_path: str = _DEFAULT_JSONL):
    """JSONL → DB + CausalGraph 주입."""
    graph = CausalGraph()
    try:
        with get_session() as session:
            results = mer_ingest.ingest_jsonl(jsonl_path, session, graph)
        return {
            "ingested": len(results),
            "nodes": graph.node_count,
            "edges": graph.edge_count,
        }
    except Exception as e:
        logger.error("ingest 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources")
def sources():
    """정보원별 등급/신뢰도 리포트."""
    with get_session() as session:
        return mer_ingest.source_report(session)


@app.post("/tickers/map")
def map_tickers(dry_run: bool = False):
    """OTHER 마켓 기업 → Claude로 ticker 매핑 (통칭 기업 분해 포함)."""
    with get_session() as session:
        results = ticker_mapper.map_tickers(session, dry_run=dry_run)
        return ticker_mapper.mapping_report(results)


@app.post("/events/extract-dates")
def extract_event_dates():
    """Event 텍스트에서 실제 사건 발생일 추출 후 occurred_at 업데이트."""
    with get_session() as session:
        updated = ticker_mapper.extract_event_dates(session)
        return {"updated": updated}


@app.get("/stats")
def stats():
    """DB 현황: 이벤트/결정/포지션/아웃컴 카운트."""
    from database.models import Event, Decision, Position, Outcome
    with get_session() as session:
        event_count = session.query(Event).count()
        decision_count = session.query(Decision).count()
        position_count = session.query(Position).count()
        outcome_count = session.query(Outcome).count()
        buy = session.query(Decision).filter(Decision.signal == "BUY").count()
        sell = session.query(Decision).filter(Decision.signal == "SELL").count()
        hold = session.query(Decision).filter(Decision.signal == "HOLD").count()
        return {
            "events": event_count,
            "decisions": {"total": decision_count, "BUY": buy, "SELL": sell, "HOLD": hold},
            "positions": position_count,
            "outcomes": outcome_count,
        }


# ── 헬퍼 ─────────────────────────────────────────────────────────

def _collect_signals(session, engine: WeightEngine, graph: CausalGraph) -> list[SignalResult]:
    """그래프 내 모든 company 노드에 대해 신호를 산출."""
    from database.models import Company
    from core.weight_engine import EventInput

    signals = []
    companies = session.query(Company).filter(Company.is_active == True).all()

    for company in companies:
        try:
            company_node = ("company", company.id)
            decision = engine.decide(company_node, [])
            if decision.signal in ("BUY", "SELL"):
                signals.append(SignalResult(
                    ticker=company.ticker or "",
                    company_name=company.name,
                    signal=decision.signal,
                    score=round(decision.event_score, 3),
                    confidence=round(decision.confidence, 3),
                ))
        except Exception:
            continue

    signals.sort(key=lambda s: abs(s.score), reverse=True)
    return signals[:10]  # 상위 10개만


def _build_discord_summary(
    title: str | None,
    url: str | None,
    source_name: str,
    sentiment: float,
    signals: list[SignalResult],
    event_count: int,
) -> str:
    """Discord 메시지용 마크다운 생성."""
    sentiment_emoji = "📈" if sentiment > 0.2 else "📉" if sentiment < -0.2 else "➡️"
    lines = []

    if title:
        header = f"**[{source_name}] {title}**"
        if url:
            header = f"**[{source_name}]** [{title}]({url})"
        lines.append(header)
    else:
        lines.append(f"**[{source_name}] 새 이벤트 감지**")

    lines.append(f"{sentiment_emoji} 감성 점수: `{sentiment:+.3f}` | 이벤트: `{event_count}건`")

    if signals:
        lines.append("")
        lines.append("**📊 매매 신호**")
        for s in signals[:5]:
            signal_emoji = "🟢" if s.signal == "BUY" else "🔴"
            ticker_str = f"`{s.ticker}`" if s.ticker else ""
            lines.append(
                f"{signal_emoji} {s.signal} {s.company_name} {ticker_str} "
                f"(score: `{s.score:+.3f}`, 신뢰도: `{s.confidence:.0%}`)"
            )
    else:
        lines.append("⬜ 매매 신호 없음 (관망)")

    return "\n".join(lines)
