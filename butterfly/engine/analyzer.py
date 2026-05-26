"""나비효과 분석기: 사건 → 파장 체인 → 한국 종목"""
from __future__ import annotations
import json
import logging
import anthropic
from butterfly.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """당신은 세계 경제 인과관계 전문가입니다.
실제로 일어난 사건을 분석해서 나비효과 체인을 추적합니다.

규칙:
1. 실제로 일어날 수 있는 인과관계만 추적 (추측 금지)
2. 최대 5단계 체인
3. 최종적으로 한국 상장 종목에 미치는 영향 명시
4. 반드시 JSON으로만 응답

응답 형식:
{
  "summary": "한 줄 요약",
  "chain": [
    {"step": 1, "event": "사건 설명", "mechanism": "인과 메커니즘"},
    {"step": 2, "event": "2차 영향", "mechanism": "인과 메커니즘"},
    ...
  ],
  "affected_sectors": ["반도체", "정유", ...],
  "signals": [
    {"ticker": "005930", "name": "삼성전자", "direction": "BUY", "confidence": 0.75, "reason": "이유"},
    ...
  ]
}

signals가 없으면 "signals": [] 반환."""


def analyze(title: str, body: str) -> dict | None:
    text = f"제목: {title}\n\n본문: {body[:3000]}" if body else f"제목: {title}"
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"다음 사건의 나비효과를 분석하세요:\n\n{text}"}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.error("분석 실패: %s", e)
        return None
