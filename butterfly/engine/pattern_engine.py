"""나비효과 패턴 축적 & 즉각 조회 엔진

쌓인 패턴 → 새 이벤트 빠른 분류 (Claude API 호출 최소화)
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from butterfly.db.models import CausalPattern

logger = logging.getLogger(__name__)

PATTERN_REUSE_THRESHOLD = 0.65   # 패턴 재사용 최소 정확도
SECTOR_OVERLAP_THRESHOLD = 0.50  # 섹터 50% 이상 겹치면 같은 패턴


def _sector_key(sectors: list[str]) -> str:
    return ",".join(sorted(set(s.strip() for s in sectors if s.strip())))


def _overlap_ratio(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_pattern(session: Session, sectors: list[str]) -> CausalPattern | None:
    """유사 패턴 검색 - 섹터 겹침률 기반"""
    if not sectors:
        return None
    # occurrence_count >= 2면 후보. accuracy는 피드백 데이터 있을 때만 필터
    candidates = session.query(CausalPattern).filter(
        CausalPattern.occurrence_count >= 2,
    ).all()

    best, best_score = None, 0.0
    for c in candidates:
        # 실거래 피드백이 쌓인 경우에만 accuracy 게이트 적용
        if c.correct_count > 0 and c.accuracy < PATTERN_REUSE_THRESHOLD:
            continue
        stored = json.loads(c.affected_sectors or "[]")
        score = _overlap_ratio(sectors, stored)
        if score > best_score and score >= SECTOR_OVERLAP_THRESHOLD:
            best, best_score = c, score

    if best:
        logger.info("🗂️  기존 패턴 매칭 (섹터 %.0f%% 일치): %s", best_score * 100, best.trigger_summary)
    return best


def save_pattern(session: Session, result: dict) -> CausalPattern:
    """Claude 분석 결과를 패턴으로 저장/업데이트"""
    sectors = result.get("affected_sectors", [])
    signals = result.get("signals", [])
    key = _sector_key(sectors)

    # 기존 패턴 찾기
    existing = session.query(CausalPattern).filter_by(sector_key=key).first()
    if existing:
        # 기존 패턴 업데이트 (신호 병합 + 평균 신뢰도)
        stored_signals = json.loads(existing.ticker_signals or "[]")
        _merge_signals(stored_signals, signals)
        existing.ticker_signals = json.dumps(stored_signals, ensure_ascii=False)
        existing.occurrence_count += 1
        existing.avg_confidence = (
            (existing.avg_confidence * (existing.occurrence_count - 1) +
             _avg_conf(signals)) / existing.occurrence_count
        )
        existing.updated_at = datetime.now(timezone.utc)
        session.commit()
        logger.info("🔄 패턴 업데이트: %s (발생 %d회)", key, existing.occurrence_count)
        return existing

    # 신규 패턴 저장
    pattern = CausalPattern(
        sector_key=key,
        trigger_summary=result.get("summary", "")[:200],
        chain_template=json.dumps(result.get("chain", []), ensure_ascii=False),
        ticker_signals=json.dumps(
            [{"ticker": s["ticker"], "name": s.get("name", ""), "direction": s["direction"],
              "avg_conf": s["confidence"]} for s in signals],
            ensure_ascii=False,
        ),
        affected_sectors=json.dumps(sectors, ensure_ascii=False),
        avg_confidence=_avg_conf(signals),
    )
    session.add(pattern)
    session.commit()
    logger.info("✨ 새 패턴 저장: %s (%d개 섹터)", key, len(sectors))
    return pattern


def update_accuracy(session: Session, pattern_id: int, was_correct: bool):
    """거래 결과로 패턴 정확도 업데이트"""
    p = session.get(CausalPattern, pattern_id)
    if not p:
        return
    if was_correct:
        p.correct_count += 1
    p.accuracy = p.correct_count / p.occurrence_count if p.occurrence_count else 0
    p.updated_at = datetime.now(timezone.utc)
    session.commit()


def pattern_to_result(pattern: CausalPattern) -> dict:
    """패턴 → Claude 분석 결과 형식으로 변환"""
    signals_raw = json.loads(pattern.ticker_signals or "[]")
    return {
        "summary": f"[패턴 재사용] {pattern.trigger_summary}",
        "chain": json.loads(pattern.chain_template or "[]"),
        "affected_sectors": json.loads(pattern.affected_sectors or "[]"),
        "signals": [
            {"ticker": s["ticker"], "name": s.get("name", ""),
             "direction": s["direction"], "confidence": s.get("avg_conf", 0.7),
             "reason": "누적 패턴 기반"}
            for s in signals_raw
        ],
    }


def _avg_conf(signals: list[dict]) -> float:
    if not signals:
        return 0.0
    return sum(s.get("confidence", 0) for s in signals) / len(signals)


def _merge_signals(stored: list[dict], new: list[dict]):
    """기존 신호 목록에 새 신호 병합 (평균 신뢰도 업데이트)"""
    ticker_map = {s["ticker"]: s for s in stored}
    for n in new:
        t = n["ticker"]
        if t in ticker_map:
            old = ticker_map[t]
            if old.get("direction") == n.get("direction"):
                old["avg_conf"] = (old.get("avg_conf", 0.7) + n.get("confidence", 0.7)) / 2
            else:
                # 방향 충돌 → 최신 신호로 교체
                old["direction"] = n["direction"]
                old["avg_conf"] = n.get("confidence", 0.7)
        else:
            stored.append({"ticker": t, "name": n.get("name", ""),
                           "direction": n["direction"], "avg_conf": n.get("confidence", 0.7)})
