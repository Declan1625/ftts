"""이벤트 → 나비효과 분석 → 신호 생성 파이프라인"""
from __future__ import annotations
import json
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Event, ButterflyChain, Signal
from butterfly.engine.analyzer import analyze
from butterfly.config import BUY_CONFIDENCE_MIN

logger = logging.getLogger(__name__)


def process_pending(session: Session) -> int:
    events = session.query(Event).filter_by(processed=False).all()
    processed = 0
    for event in events:
        try:
            result = analyze(event.title, event.body or "")
            if not result:
                event.processed = True
                continue

            signals = result.get("signals", [])
            if not signals:
                event.processed = True
                session.commit()
                continue

            chain = ButterflyChain(
                event_id=event.id,
                chain_json=json.dumps(result.get("chain", []), ensure_ascii=False),
                final_tickers=",".join(s["ticker"] for s in signals),
                direction=signals[0]["direction"] if signals else None,
                confidence=max(s["confidence"] for s in signals) if signals else 0,
            )
            session.add(chain)
            session.flush()

            for s in signals:
                if s["confidence"] >= BUY_CONFIDENCE_MIN:
                    session.add(Signal(
                        chain_id=chain.id,
                        ticker=s["ticker"],
                        company_name=s.get("name", ""),
                        direction=s["direction"],
                        confidence=s["confidence"],
                    ))

            event.processed = True
            session.commit()
            processed += 1
            logger.info("처리 완료: %s → 신호 %d건", event.title[:50], len(signals))
        except Exception as e:
            logger.error("처리 실패 [%d]: %s", event.id, e)
            session.rollback()
    return processed
