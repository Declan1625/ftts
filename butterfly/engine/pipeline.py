"""이벤트 → 나비효과 분석 → 신호 생성 파이프라인"""
from __future__ import annotations
import json
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Event, ButterflyChain, Signal
from butterfly.engine import analyzer as _analyzer
from butterfly.engine.pattern_engine import find_pattern, save_pattern, pattern_to_result
from butterfly.engine.event_scorer import score_event, quick_sectors
from butterfly.engine import industry_analyzer as _industry
from butterfly.engine import timing_filter as _timing
from butterfly.sources.dart_financial import enrich_signals
from butterfly.sources.krx_supply import adjust_confidence
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

    events.sort(key=lambda e: score_event(e), reverse=True)
    events = events[:max_per_cycle]
    logger.info("미처리 이벤트 처리 시작: %d건 (최대 %d)", len(events), max_per_cycle)

    # ── 1단계: 캐시 분류 ────────────────────────────────────────────
    cache_results: dict[int, dict] = {}      # event.id → result
    cache_pattern_ids: dict[int, int] = {}   # event.id → pattern.id
    needs_claude: list[Event] = []

    for event in events:
        hint = quick_sectors(event.title)
        if hint:
            cached = find_pattern(session, hint)
            if cached:
                cache_results[event.id] = pattern_to_result(cached)
                cache_pattern_ids[event.id] = cached.id
                logger.info("🗂️  캐시 히트: %s", event.title[:40])

        if event.id not in cache_results:
            needs_claude.append(event)

    # ── 2단계: Batch API로 cache-miss 일괄 분석 ──────────────────────
    claude_results: dict[int, dict | None] = {}
    if needs_claude:
        batch_out = _analyzer.analyze_batch([(e.title, e.body or "") for e in needs_claude])
        for event, result in zip(needs_claude, batch_out):
            claude_results[event.id] = result
    logger.info("파이프라인: Batch %d건 / 캐시 %d건", len(needs_claude), len(cache_results))

    # ── 3단계: 결과 처리 ─────────────────────────────────────────────
    processed = 0
    for event in events:
        try:
            used_cache = event.id in cache_results
            result = cache_results.get(event.id) or claude_results.get(event.id)

            if not result:
                event.processed = True
                session.commit()
                continue

            signals = result.get("signals", [])
            sectors = result.get("affected_sectors", [])

            pattern_id: int | None = cache_pattern_ids.get(event.id)
            if not used_cache and signals and sectors:
                saved = save_pattern(session, result)
                pattern_id = saved.id

            if not signals:
                event.processed = True
                session.commit()
                continue

            # ── 3-1. 타이밍 필터 (오래된 뉴스 감쇠) ─────────────────
            signals = _timing.apply(signals, event.published_at)
            if not signals:
                event.processed = True
                session.commit()
                continue

            # ── 3-2. DART 재무데이터 보강 ────────────────────────────
            signals = enrich_signals(signals)

            # ── 3-3. 산업/기업 분석 레이어 (밸류체인 + 재무 필터) ────
            sector_names = [
                s["name"] if isinstance(s, dict) else s
                for s in sectors
            ]
            signals = _industry.analyze(event.title, sector_names, signals)

            # ── 3-4. KRX 수급 보정 ───────────────────────────────────
            for s in signals:
                if s.get("ticker"):
                    s["confidence"] = adjust_confidence(s["ticker"], s.get("confidence", 0.5))

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
                        pattern_id=pattern_id,
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

    return processed
