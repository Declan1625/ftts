from __future__ import annotations
from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path
from sqlalchemy import func
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import httpx
import logging

from butterfly.db.manager import init_db, get_session
from butterfly.db.models import Event, ButterflyChain, Signal, Trade, Portfolio, CausalPattern
from butterfly.sources.collector import collect_and_save
from butterfly.engine.pipeline import process_pending
from butterfly.trading.simulator import run_simulation
from butterfly import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_log_buffer: deque[str] = deque(maxlen=100)
_log_listeners: list[asyncio.Queue] = []


class PipelineLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        _log_buffer.append(msg)
        for q in _log_listeners:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


_handler = PipelineLogHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s", "%H:%M:%S"))
for _lg_name in ("butterfly", "httpx"):
    _lg = logging.getLogger(_lg_name)
    if not any(isinstance(h, PipelineLogHandler) for h in _lg.handlers):
        _lg.addHandler(_handler)


async def run_pipeline():
    logger.info("🦋 파이프라인 시작")
    s = get_session()
    try:
        logger.info("📡 이벤트 수집 중...")
        collected = await asyncio.to_thread(collect_and_save, s)
        logger.info("✅ 수집 완료: %d건", collected)

        logger.info("🔍 나비효과 분석 중...")
        processed = await asyncio.to_thread(process_pending, s)
        logger.info("✅ 분석 완료: %d건", processed)

        logger.info("💼 시뮬레이션 실행 중...")
        traded = await asyncio.to_thread(run_simulation, s)
        logger.info("✅ 시뮬레이션 완료: %d건 매수", traded)

        if processed > 0:
            await notify_discord(s)
        logger.info("🏁 파이프라인 완료")
    finally:
        s.close()


async def notify_discord(session):
    signals = (
        session.query(Signal)
        .order_by(Signal.created_at.desc())
        .limit(10)
        .all()
    )
    if not signals or not config.DISCORD_WEBHOOK or not config.DISCORD_WEBHOOK.startswith("http"):
        return

    p = session.query(Portfolio).first()
    cash = p.cash if p else 0
    initial = p.initial_cash if p else config.PAPER_INITIAL_CASH
    open_cnt = session.query(func.count(Trade.id)).filter_by(status="open").scalar()

    lines = [f"🦋 **나비효과 AI 리포트**\n💼 현금: {cash:,.0f}원 | 오픈 포지션: {open_cnt}건\n"]
    for s in signals:
        icon = "🟢" if s.direction == "BUY" else "🔴"
        lines.append(f"{icon} {s.company_name}({s.ticker}) {s.direction} | 신뢰도 {s.confidence*100:.0f}%")

    try:
        async with httpx.AsyncClient() as client:
            await client.post(config.DISCORD_WEBHOOK, json={"content": "\n".join(lines)}, timeout=5)
    except Exception as e:
        logger.error("Discord 전송 실패: %s", e)


async def morning_briefing():
    """매일 오전 8시 KST 일간 브리핑 → Discord"""
    if not config.DISCORD_WEBHOOK or not config.DISCORD_WEBHOOK.startswith("http"):
        return
    s = get_session()
    try:
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        yesterday = now - timedelta(days=1)

        # 전날 신호
        yesterday_signals = (
            s.query(Signal)
            .filter(Signal.created_at >= yesterday.replace(hour=0, minute=0, second=0))
            .order_by(Signal.created_at.desc())
            .limit(10).all()
        )
        # 전날 거래
        yesterday_trades = (
            s.query(Trade)
            .filter(Trade.entered_at >= yesterday.replace(hour=0, minute=0, second=0))
            .all()
        )
        closed_today = s.query(Trade).filter_by(status="closed").filter(
            Trade.exited_at >= yesterday.replace(hour=0, minute=0, second=0)
        ).all()

        # 포트폴리오
        p = s.query(Portfolio).first()
        open_cnt = s.query(func.count(Trade.id)).filter_by(status="open").scalar()
        patterns_cnt = s.query(func.count(CausalPattern.id)).filter(
            CausalPattern.occurrence_count >= 2
        ).scalar()

        # 손익 계산
        cash = p.cash if p else config.PAPER_INITIAL_CASH
        initial = p.initial_cash if p else config.PAPER_INITIAL_CASH
        pnl_pct = (cash - initial) / initial * 100 if initial else 0
        realized = p.realized_pnl if p else 0

        lines = [
            f"🌅 **FTTS 일간 브리핑 — {now.strftime('%m/%d %H:%M')} KST**",
            "",
            f"💼 **포트폴리오**: 현금 {cash:,.0f}원 | 수익률 {pnl_pct:+.2f}% | 실현손익 {realized:+,.0f}원",
            f"📊 **포지션**: 오픈 {open_cnt}건 | 누적 패턴 {patterns_cnt}개",
            "",
        ]

        if yesterday_signals:
            lines.append(f"📡 **어제 신호 ({len(yesterday_signals)}건)**")
            for sig in yesterday_signals[:5]:
                icon = "🟢" if sig.direction == "BUY" else "🔴"
                lines.append(f"  {icon} {sig.company_name or sig.ticker}({sig.ticker}) {sig.direction} {sig.confidence*100:.0f}%")
        else:
            lines.append("📡 어제 신호: 없음")

        if closed_today:
            wins = sum(1 for t in closed_today if t.pnl and t.pnl > 0)
            lines.append(f"\n🏁 **어제 청산**: {len(closed_today)}건 | 승률 {wins/len(closed_today)*100:.0f}%")

        lines += [
            "",
            "⚡ 30분 파이프라인 가동 중 | 장 시작(09:00) 자동 매수 대기",
        ]

        async with httpx.AsyncClient() as client:
            await client.post(config.DISCORD_WEBHOOK,
                              json={"content": "\n".join(lines)}, timeout=5)
        logger.info("📨 일간 브리핑 Discord 전송 완료")
    except Exception as e:
        logger.error("일간 브리핑 실패: %s", e)
    finally:
        s.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(run_pipeline, "interval", minutes=30, id="pipeline")
    # 매일 오전 8시 KST 일간 브리핑
    scheduler.add_job(
        morning_briefing, "cron",
        hour=8, minute=0,
        timezone="Asia/Seoul",
        day_of_week="mon-fri",
        id="morning_briefing",
    )
    scheduler.start()
    logger.info("나비효과 AI 시작 - 30분 파이프라인 + 08:00 KST 일간 브리핑 활성화")
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
    try:
        return {
            "events": s.query(func.count(Event.id)).scalar(),
            "chains": s.query(func.count(ButterflyChain.id)).scalar(),
            "signals": s.query(func.count(Signal.id)).scalar(),
            "trades": s.query(func.count(Trade.id)).scalar(),
            "pending_events": s.query(func.count(Event.id)).filter_by(processed=False).scalar(),
            "patterns": s.query(func.count(CausalPattern.id)).scalar(),
        }
    finally:
        s.close()


@app.get("/portfolio")
def portfolio():
    s = get_session()
    try:
        p = s.query(Portfolio).first()
        if not p:
            return {
                "initial_cash": config.PAPER_INITIAL_CASH,
                "cash": config.PAPER_INITIAL_CASH,
                "invested": 0,
                "current_value": config.PAPER_INITIAL_CASH,
                "unrealized_pnl": 0,
                "realized_pnl": 0,
                "total_pnl_pct": 0,
                "positions": [],
            }

        open_trades = s.query(Trade).filter_by(status="open").order_by(Trade.entered_at.desc()).all()
        positions = []
        invested = 0
        current_val = 0

        for t in open_trades:
            entry_val = (t.price_at_entry or 0) * t.quantity
            cur_val = (t.current_price or t.price_at_entry or 0) * t.quantity
            invested += entry_val
            current_val += cur_val
            positions.append({
                "id": t.id,
                "ticker": t.ticker,
                "company": t.company_name or t.ticker,
                "risk_tier": t.risk_tier or "MEDIUM",
                "qty": t.quantity,
                "entry_price": t.price_at_entry,
                "current_price": t.current_price or t.price_at_entry,
                "target_price": t.target_price,
                "stop_loss": t.stop_loss_price,
                "pnl": t.pnl or 0,
                "pnl_pct": t.pnl_pct or 0,
                "status": t.status,
            })

        total_value = p.cash + current_val
        unrealized = current_val - invested
        total_pnl_pct = (total_value - p.initial_cash) / p.initial_cash * 100

        return {
            "initial_cash": p.initial_cash,
            "cash": p.cash,
            "invested": invested,
            "current_value": total_value,
            "unrealized_pnl": unrealized,
            "realized_pnl": p.realized_pnl or 0,
            "total_pnl_pct": total_pnl_pct,
            "positions": positions,
        }
    finally:
        s.close()


@app.get("/metrics")
def metrics():
    """성과 지표: 승률, MDD, Sharpe, 총 수익률"""
    import math
    s = get_session()
    try:
        closed = s.query(Trade).filter_by(status="closed").all()
        if not closed:
            return {"win_rate": 0, "total_trades": 0, "mdd": 0, "sharpe": 0, "total_return_pct": 0}

        wins = sum(1 for t in closed if t.pnl and t.pnl > 0)
        win_rate = wins / len(closed) * 100
        pnl_list = [t.pnl_pct or 0 for t in closed]
        avg_pnl = sum(pnl_list) / len(pnl_list)
        std_pnl = math.sqrt(sum((x - avg_pnl) ** 2 for x in pnl_list) / len(pnl_list)) if len(pnl_list) > 1 else 1
        sharpe = avg_pnl / std_pnl if std_pnl else 0

        # MDD: 누적 수익 곡선 기준
        cumulative = 0
        peak = 0
        mdd = 0
        for p in pnl_list:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > mdd:
                mdd = dd

        p = s.query(Portfolio).first()
        total_return = (p.realized_pnl / p.initial_cash * 100) if p and p.initial_cash else 0

        return {
            "total_trades": len(closed),
            "win_rate": round(win_rate, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "sharpe": round(sharpe, 2),
            "mdd": round(mdd, 2),
            "total_return_pct": round(total_return, 2),
        }
    finally:
        s.close()


@app.get("/run")
async def run_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_pipeline)
    return {"status": "started"}


@app.get("/briefing")
async def run_briefing(background_tasks: BackgroundTasks):
    """수동 일간 브리핑 트리거 (테스트/긴급용)"""
    background_tasks.add_task(morning_briefing)
    return {"status": "briefing_started"}


@app.get("/logs/stream")
async def log_stream():
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _log_listeners.append(q)

    async def generate():
        for msg in list(_log_buffer):
            yield f"data: {msg}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield "data: ping\n\n"
        finally:
            _log_listeners.remove(q)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/signals")
def signals(limit: int = 20):
    s = get_session()
    try:
        rows = s.query(Signal).order_by(Signal.created_at.desc()).limit(limit).all()
        return [{"id": r.id, "ticker": r.ticker, "company": r.company_name,
                 "direction": r.direction, "confidence": r.confidence,
                 "executed": r.executed} for r in rows]
    finally:
        s.close()


@app.get("/patterns")
def patterns(limit: int = 20):
    s = get_session()
    try:
        rows = (s.query(CausalPattern)
                .order_by(CausalPattern.occurrence_count.desc())
                .limit(limit).all())
        return [{"id": r.id, "sectors": r.sector_key, "summary": r.trigger_summary,
                 "occurrences": r.occurrence_count, "accuracy": round(r.accuracy * 100, 1),
                 "avg_confidence": round(r.avg_confidence * 100, 1)} for r in rows]
    finally:
        s.close()


@app.get("/chains")
def chains_list(limit: int = 20):
    import json as _j
    s = get_session()
    try:
        rows = (s.query(ButterflyChain)
                .order_by(ButterflyChain.created_at.desc())
                .limit(limit).all())
        result = []
        for c in rows:
            try:
                chain_data = _j.loads(c.chain_json)
            except Exception:
                chain_data = {}
            result.append({
                "id": c.id,
                "event": c.event.title if c.event else "",
                "event_source": c.event.source if c.event else "",
                "direction": c.direction,
                "confidence": c.confidence,
                "chain": chain_data,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })
        return result
    finally:
        s.close()


@app.get("/chains/{chain_id}")
def chain_detail(chain_id: int):
    import json
    s = get_session()
    try:
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
    finally:
        s.close()
