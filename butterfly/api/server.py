from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import func
from butterfly.db.manager import init_db, get_session
from butterfly.db.models import Event, ButterflyChain, Signal, Trade
from butterfly.sources.collector import collect_and_save
from butterfly.engine.pipeline import process_pending
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("나비효과 AI 시작")
    yield


app = FastAPI(title="나비효과 AI", lifespan=lifespan)


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
def collect():
    s = get_session()
    n = collect_and_save(s)
    return {"collected": n}


@app.post("/process")
def process():
    s = get_session()
    n = process_pending(s)
    return {"processed": n}


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
