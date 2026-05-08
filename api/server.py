"""api/server.py — FTTS FastAPI 서버 (n8n → FTTS 연동 엔드포인트)"""

from __future__ import annotations

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
