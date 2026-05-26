from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from sqlalchemy import func
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx
import logging

from butterfly.db.manager import init_db, get_session
from butterfly.db.models import Event, ButterflyChain, Signal, Trade
from butterfly.sources.collector import collect_and_save
from butterfly.engine.pipeline import process_pending
from butterfly.trading.paper_trader import execute_pending
from butterfly import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_pipeline():
    logger.info("파이프라인 시작")
    s = get_session()
    try:
        collected = collect_and_save(s)
        logger.info("수집: %d건", collected)

        processed = process_pending(s)
        logger.info("분석: %d건", processed)

        traded = execute_pending(s)
        logger.info("모의투자: %d건", traded)

        if processed > 0:
            await notify_discord(s)
    finally:
        s.close()


async def notify_discord(session):
    signals = (
        session.query(Signal)
        .filter_by(executed=False)
        .order_by(Signal.created_at.desc())
        .limit(10)
        .all()
    )
    if not signals or not config.DISCORD_WEBHOOK:
        return

    lines = ["🦋 **나비효과 신호 & 모의투자 실행**\n"]
    for s in signals:
        icon = "🟢" if s.direction == "BUY" else "🔴"
        trade_status = "✅ 주문완료" if s.executed else "⏳ 대기"
        lines.append(f"{icon} {s.company_name}({s.ticker}) {s.direction} | 신뢰도 {s.confidence*100:.0f}% | {trade_status}")

    msg = "\n".join(lines)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(config.DISCORD_WEBHOOK, json={"content": msg}, timeout=5)
    except Exception as e:
        logger.error("Discord 전송 실패: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(run_pipeline, "interval", minutes=30, id="pipeline")
    scheduler.start()
    logger.info("나비효과 AI 시작 - 30분 스케줄 활성화")
    yield
    scheduler.shutdown()


app = FastAPI(title="나비효과 AI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    html = Path(__file__).parent / "dashboard.html"
    return html.read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stats")
def stats():
    s = get_session()
    return {
        "events": s.query(func.count(Event.id)).scalar(),
        "chains": s.query(func.count(ButterflyChain.id)).scalar(),
        "signals": s.query(func.count(Signal.id)).scalar(),
        "trades": s.query(func.count(Trade.id)).scalar(),
        "pending_events": s.query(func.count(Event.id)).filter_by(processed=False).scalar(),
    }


@app.post("/collect")
async def collect():
    s = get_session()
    n = collect_and_save(s)
    return {"collected": n}


@app.post("/process")
async def process():
    s = get_session()
    n = process_pending(s)
    return {"processed": n}


@app.get("/run")
async def run_now(background_tasks: BackgroundTasks):
    """즉시 파이프라인 실행 (백그라운드)"""
    background_tasks.add_task(run_pipeline)
    return {"status": "started", "message": "파이프라인 백그라운드 실행 중. /stats 로 확인하세요."}


@app.get("/signals")
def signals(limit: int = 20):
    s = get_session()
    rows = s.query(Signal).order_by(Signal.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "ticker": r.ticker, "company": r.company_name,
             "direction": r.direction, "confidence": r.confidence,
             "executed": r.executed} for r in rows]


@app.get("/chains/{chain_id}")
def chain_detail(chain_id: int):
    import json
    s = get_session()
    c = s.query(ButterflyChain).get(chain_id)
    if not c:
        return {"error": "not found"}
    return {
        "id": c.id,
        "event": c.event.title,
        "chain": json.loads(c.chain_json),
        "signals": c.final_tickers,
        "direction": c.direction,
        "confidence": c.confidence,
    }
