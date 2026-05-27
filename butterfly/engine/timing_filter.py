"""뉴스 타이밍 보정
시장 반영 정도에 따라 신뢰도 감쇠
- 2시간 이내: 감쇠 없음 (선점 가능)
- 6시간: -15% (일부 반영)
- 12시간: -30% (상당 부분 반영)
- 24시간: -50% (대부분 반영)
- 48시간 초과: 신호 생성 스킵
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# (최대시간, 감쇠계수)
_DECAY = [(2, 1.0), (6, 0.85), (12, 0.70), (24, 0.50), (48, 0.30)]
SKIP_HOURS = 48


def _age_hours(published_at) -> float:
    if not published_at:
        return 6.0  # 시간 정보 없으면 보수적으로
    now = datetime.now(timezone.utc)
    pub = published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    return (now - pub).total_seconds() / 3600


def decay_factor(published_at) -> float:
    """0.0(스킵) ~ 1.0(감쇠 없음)"""
    age = _age_hours(published_at)
    for hours, factor in _DECAY:
        if age <= hours:
            return factor
    return 0.0  # SKIP_HOURS 초과


def apply(signals: list[dict], published_at) -> list[dict]:
    """신호 목록에 타이밍 감쇠 적용. 0.0이면 빈 리스트 반환."""
    factor = decay_factor(published_at)
    age = _age_hours(published_at)

    if factor == 0.0:
        logger.info("⏰ 타이밍 스킵: 뉴스 %.0f시간 경과 (상한 %d시간)", age, SKIP_HOURS)
        return []

    if factor == 1.0:
        return signals

    adjusted = []
    for s in signals:
        orig = s.get("confidence", 0.5)
        new  = round(orig * factor, 3)
        adjusted.append({**s, "confidence": new})

    logger.info("⏰ 타이밍 감쇠: %.0f시간 경과 → factor=%.2f (%d개 신호)",
                age, factor, len(signals))
    return adjusted
