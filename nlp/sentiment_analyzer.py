"""nlp/sentiment_analyzer.py — Claude Sonnet 4.6 기반 감성 분석 (-1 ~ +1)"""

from __future__ import annotations

import json
import logging

from anthropic import Anthropic

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_MODEL = "claude-opus-4-1-20250805"

_SYSTEM_PROMPT = """\
당신은 금융 텍스트 감성 분석 전문가입니다.
주어진 텍스트의 투자 관점 감성을 JSON으로 반환하세요.

형식:
{
  "score": -1.0 ~ 1.0,
  "label": "positive|neutral|negative",
  "reasoning": "한 문장 근거"
}

score 기준:
  +1.0: 매우 긍정 (강한 매수 신호)
   0.0: 중립
  -1.0: 매우 부정 (강한 매도 신호)

JSON만 출력하세요.
"""


def analyze(text: str) -> float:
    """텍스트 감성 점수 반환 (-1.0 ~ 1.0). 실패 시 0.0."""
    result = analyze_with_detail(text)
    return result["score"]


def analyze_with_detail(text: str) -> dict:
    """score, label, reasoning 포함 상세 결과 반환."""
    client = Anthropic()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": text[:3000]},
                ],
            )
            raw = response.content[0].text
            return _parse(raw)
        except Exception as exc:
            last_exc = exc
            logger.warning("감성 분석 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)

    logger.error("감성 분석 최종 실패: %s", last_exc)
    return {"score": 0.0, "label": "neutral", "reasoning": "분석 실패"}


def _parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
        score = float(data.get("score", 0.0))
        score = max(-1.0, min(1.0, score))
        return {
            "score": score,
            "label": data.get("label", "neutral"),
            "reasoning": data.get("reasoning", ""),
        }
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("감성 분석 파싱 실패: %s | raw=%s", exc, raw[:100])
        return {"score": 0.0, "label": "neutral", "reasoning": "파싱 실패"}
