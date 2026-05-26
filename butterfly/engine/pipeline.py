"""이벤트 → 나비효과 분석 → 신호 생성 파이프라인"""
from __future__ import annotations
import json
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Event, ButterflyChain, Signal
from butterfly.engine.analyzer import analyze
from butterfly.engine.pattern_engine import find_pattern, save_pattern, pattern_to_result
from butterfly.config import BUY_CONFIDENCE_MIN

logger = logging.getLogger(__name__)

# 섹터 → 리스크 티어 분류
_HIGH_SECTORS = {"바이오", "게임", "엔터", "스타트업", "제약", "코스닥", "중소형"}
_STABLE_SECTORS = {"은행", "통신", "전력", "가스", "식품", "유통", "보험", "공기업"}


def _classify_tier(sectors: list[str]) -> str:
    joined = " ".join(sectors)
    if any(k in joined for k in _HIGH_SECTORS):
        return "HIGH"
    if any(k in joined for k in _STABLE_SECTORS):
        return "STABLE"
    return "MEDIUM"


def process_pending(session: Session) -> int:
    events = session.query(Event).filter_by(processed=False).all()
    processed = 0

    for event in events:
        try:
            sectors_hint = []
            result = None

            # ── 1. 기존 패턴 먼저 확인 (빠른 경로) ──────────────────
            # 제목에서 간단한 키워드로 임시 섹터 추출은 생략,
            # Claude 호출 후 저장된 패턴과 섹터 매칭으로 다음 사이클부터 재사용
            result = analyze(event.title, event.body or "")

            if not result:
                event.processed = True
                session.commit()
                continue

            signals = result.get("signals", [])
            sectors = result.get("affected_sectors", [])

            # ── 2. 패턴 저장 (축적) ──────────────────────────────────
            if signals and sectors:
                save_pattern(session, result)

            if not signals:
                event.processed = True
                session.commit()
                continue

            # ── 3. 티어 분류 ─────────────────────────────────────────
            tier = _classify_tier(sectors)

            chain = ButterflyChain(
                event_id=event.id,
                chain_json=json.dumps(result.get("chain", []), ensure_ascii=False),
                final_tickers=",".join(s["ticker"] for s in signals),
                direction=signals[0]["direction"] if signals else None,
                confidence=max(s["confidence"] for s in signals) if signals else 0,
            )
            session.add(chain)
            session.flush()

            added = 0
            for s in signals:
                if s["confidence"] >= BUY_CONFIDENCE_MIN:
                    session.add(Signal(
                        chain_id=chain.id,
                        ticker=s["ticker"],
                        company_name=s.get("name", ""),
                        direction=s["direction"],
                        confidence=s["confidence"],
                        risk_tier=tier,
                    ))
                    added += 1

            event.processed = True
            session.commit()
            processed += 1
            logger.info("처리: %s → 섹터:%s 티어:%s 신호:%d건",
                        event.title[:40], ",".join(sectors[:2]), tier, added)

        except Exception as e:
            logger.error("처리 실패 [%d]: %s", event.id, e)
            session.rollback()

    return processed
