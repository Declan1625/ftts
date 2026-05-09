"""nlp/mer_analyzer.py — 메르 블로그 글의 메르식 투자법 분석 (사건 → 정보원 → 인과관계)"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_MODEL = "claude-sonnet-4-5"

_SYSTEM_PROMPT = """\
당신은 메르식 투자법 분석 전문가입니다.

메르식 투자법의 핵심은:
1. 실제 사건 (event) 발견
2. 사건을 알게 된 정보원 (primary source) 파악
3. 글에서 참고한 다른 정보원들 (reference sources) 수집
4. 정보원 간 관계 분석 (상충, 확인, 보완)
5. 영향받는 산업 & 회사 식별
6. 인과관계 체인 구성 (사건 → 산업 → 주가)

주어진 메르 블로그 글을 분석하여 다음을 추출하세요:

응답 형식: 아래 JSON 객체를 정확히 제공하세요. 다른 텍스트는 절대 포함하지 마세요.

{
  "events": ["사건1", "사건2"],
  "primary_source": "정보원 (예: FT, WSJ, Reuters, DART, SEC)",
  "reference_sources": ["참고정보원1", "참고정보원2"],
  "source_correlations": [
    {"from": "FT", "to": "WSJ", "relation": "confirm", "weight": 0.9},
    {"from": "FT", "to": "한국경제", "relation": "conflict", "weight": -0.5}
  ],
  "affected_industries": ["산업1", "산업2"],
  "affected_companies": ["회사1", "회사2"],
  "causal_chain": "사건 → 산업 영향 → 주가 영향 방향 (한 문장)",
  "confidence": 0.75,
  "summary": "글의 핵심 한 문장 요약"
}

주의:
- events, reference_sources: 빈 배열 []이어도 됨
- primary_source: 반드시 1개 (없으면 "Unknown")
- source_correlations: relation은 "confirm", "conflict", "complement" 중 하나
- confidence: 0.0~1.0
- JSON 객체만 출력 (마크다운 블록 금지)
"""


@dataclass
class MerAnalysis:
    """메르식 분석 결과."""
    events: list[str]
    primary_source: str
    reference_sources: list[str]
    source_correlations: list[dict]
    affected_industries: list[str]
    affected_companies: list[str]
    causal_chain: str
    confidence: float
    summary: str


def analyze_mer_blog(
    title: str,
    content: str,
    source_name: str = "메르 블로그",
) -> MerAnalysis:
    """메르 블로그 글을 메르식으로 분석. API 실패 시 3회 재시도."""
    client = Anthropic()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            prompt = f"[제목] {title}\n\n[본문]\n{content[:5000]}"
            response = client.messages.create(
                model=_MODEL,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            raw = response.content[0].text
            return _parse_response(raw)
        except Exception as exc:
            last_exc = exc
            logger.warning("메르식 분석 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)

    logger.error("메르식 분석 실패 (최종): %s", last_exc)
    logger.warning("FALLBACK: 분석을 건너뛰고 기본 값 반환")
    # 구조 검증용 기본값 반환 (실제 운영에서는 에러)
    return MerAnalysis(
        events=[],
        primary_source="Unknown",
        reference_sources=[],
        source_correlations=[],
        affected_industries=[],
        affected_companies=[],
        causal_chain="",
        confidence=0.0,
        summary=f"API 인증 오류. 제목: {title[:50]}",
    )


def _parse_response(raw: str) -> MerAnalysis:
    """Claude 응답을 MerAnalysis로 파싱."""
    try:
        data = json.loads(raw)
        return MerAnalysis(
            events=data.get("events", []),
            primary_source=data.get("primary_source", "Unknown"),
            reference_sources=data.get("reference_sources", []),
            source_correlations=data.get("source_correlations", []),
            affected_industries=data.get("affected_industries", []),
            affected_companies=data.get("affected_companies", []),
            causal_chain=data.get("causal_chain", ""),
            confidence=float(data.get("confidence", 0.5)),
            summary=data.get("summary", ""),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Claude 응답 파싱 실패: %s | raw=%s", exc, raw[:200])
        return MerAnalysis(
            events=[],
            primary_source="Unknown",
            reference_sources=[],
            source_correlations=[],
            affected_industries=[],
            affected_companies=[],
            causal_chain="",
            confidence=0.0,
            summary="",
        )
