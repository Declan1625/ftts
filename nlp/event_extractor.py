"""nlp/event_extractor.py — Claude Sonnet 4.6 기반 이벤트 구조화 추출"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_MODEL = "claude-sonnet-4-5"

_SYSTEM_PROMPT = """\
당신은 금융·경제 뉴스 분석 전문가입니다.
주어진 텍스트에서 투자 관련 이벤트를 JSON 배열로 추출합니다.

응답 형식: 다음 JSON 배열 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

[
  {
    "event_type": "policy",
    "summary": "한 문장 요약",
    "affected_industries": ["산업명"],
    "affected_companies": ["회사명"],
    "sentiment": 0.5,
    "confidence": 0.8
  }
]

주의:
- JSON 배열만 출력
- 이벤트 없으면 빈 배열 []
- JSON 블록 마크다운 사용 금지
"""


@dataclass
class ExtractedEvent:
    event_type: str
    summary: str
    affected_industries: list[str]
    affected_companies: list[str]
    sentiment: float
    confidence: float


def extract_events(text: str, source_name: str = "") -> list[ExtractedEvent]:
    """텍스트에서 이벤트 목록 추출. API 실패 시 3회 재시도."""
    client = Anthropic()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"[출처: {source_name}]\n\n{text[:4000]}",
                    }
                ],
            )
            raw = response.content[0].text
            return _parse_response(raw)
        except Exception as exc:
            last_exc = exc
            logger.warning("Claude 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)

    logger.error("이벤트 추출 실패: %s", last_exc)
    raise RuntimeError("이벤트 추출 실패") from last_exc


def _parse_response(raw: str) -> list[ExtractedEvent]:
    try:
        data = json.loads(raw)
        items = data if isinstance(data, list) else data.get("events", [])
        events: list[ExtractedEvent] = []
        for item in items:
            events.append(
                ExtractedEvent(
                    event_type=item.get("event_type", "other"),
                    summary=item.get("summary", ""),
                    affected_industries=item.get("affected_industries", []),
                    affected_companies=item.get("affected_companies", []),
                    sentiment=float(item.get("sentiment", 0.0)),
                    confidence=float(item.get("confidence", 0.5)),
                )
            )
        return events
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Claude 응답 파싱 실패: %s | raw=%s", exc, raw[:200])
        return []
