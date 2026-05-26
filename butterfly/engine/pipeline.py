"""이벤트 → 나비효과 분석 → 신호 생성 파이프라인"""
from __future__ import annotations
import json
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Event, ButterflyChain, Signal
from butterfly.engine.analyzer import analyze
from butterfly.engine.pattern_engine import find_pattern, save_pattern, pattern_to_result
from butterfly.engine.event_scorer import score_event, quick_sectors
from butterfly.config import BUY_CONFIDENCE_MIN

logger = logging.getLogger(__name__)

# GICS 기반 섹터→티어 매핑
_SECTOR_TIER: dict[str, str] = {
    # HIGH (변동성 높음, 이벤트 드리븐)
    "반도체": "HIGH", "DRAM": "HIGH", "HBM": "HIGH", "낸드": "HIGH", "파운드리": "HIGH",
    "바이오": "HIGH", "제약": "HIGH", "임상": "HIGH", "신약": "HIGH",
    "배터리": "HIGH", "2차전지": "HIGH", "리튬": "HIGH", "양극재": "HIGH",
    "방산": "HIGH", "게임": "HIGH", "엔터": "HIGH",
    # MEDIUM (경기순환)
    "자동차": "MEDIUM", "전기차": "MEDIUM", "정유": "MEDIUM", "화학": "MEDIUM",
    "철강": "MEDIUM", "건설": "MEDIUM", "조선": "MEDIUM", "해운": "MEDIUM",
    "화장품": "MEDIUM", "IT": "MEDIUM", "소프트웨어": "MEDIUM",
    # STABLE (방어주)
    "은행": "STABLE", "금융": "STABLE", "보험": "STABLE",
    "통신": "STABLE", "전력": "STABLE", "식품": "STABLE", "유통": "STABLE",
    "공기업": "STABLE", "리츠": "STABLE",
}


def _classify_tier(sectors: list[str]) -> str:
    joined = " ".join(sectors)
    counts = {"HIGH": 0, "MEDIUM": 0, "STABLE": 0}
    for kw, tier in _SECTOR_TIER.items():
        if kw in joined:
            counts[tier] += 1
    if counts["HIGH"] > 0:
        return "HIGH"
    if counts["STABLE"] > counts["MEDIUM"]:
        return "STABLE"
    return "MEDIUM"


def process_pending(session: Session, max_per_cycle: int = 30) -> int:
    events = (session.query(Event)
              .filter_by(processed=False)
              .all())
    if not events:
        return 0

    # 중요도 순 정렬 후 한 사이클 최대 처리 수 제한
    events.sort(key=lambda e: score_event(e), reverse=True)
    events = events[:max_per_cycle]
    logger.info("미처리 이벤트 처리 시작: %d건 (최대 %d)", len(events), max_per_cycle)

    processed = 0
    claude_calls = 0
    cache_hits = 0

    for event in events:
        try:
            result = None
            used_cache = False

            # ── 1. 패턴 캐시 먼저 시도 ──────────────────────────────
            hint = quick_sectors(event.title)
            if hint:
                cached = find_pattern(session, hint)
                if cached:
                    result = pattern_to_result(cached)
                    used_cache = True
                    cache_hits += 1
                    logger.info("🗂️  캐시 히트: %s (Claude 절약)", event.title[:40])

            # ── 2. 캐시 미스 → Claude 호출 ───────────────────────────
            if result is None:
                result = analyze(event.title, event.body or "")
                claude_calls += 1

            if not result:
                event.processed = True
                session.commit()
                continue

            signals = result.get("signals", [])
            sectors = result.get("affected_sectors", [])

            # ── 3. 결과 패턴으로 저장 (지식 축적) ───────────────────
            if not used_cache and signals and sectors:
                save_pattern(session, result)

            if not signals:
                event.processed = True
                session.commit()
                continue

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
            logger.info("처리: %s → 티어:%s 신호:%d건", event.title[:40], tier, added)

        except Exception as e:
            logger.error("처리 실패 [%d]: %s", event.id, e)
            session.rollback()

    logger.info("파이프라인: Claude %d회 / 캐시 %d회 / 처리 %d건", claude_calls, cache_hits, processed)
    return processed
