"""나비효과 분석기: 사건 → 파장 체인 → 한국 종목"""
from __future__ import annotations
import json
import logging
import anthropic
from butterfly.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_KOREA_CAUSAL_RULES = """
## 한국 시장 필수 인과관계 규칙

1. 원/달러 환율 상승(약세) → 삼성전자/현대차/기아 수출수혜(BUY) + 대한항공/아시아나(SELL) + 단기 외국인 매도로 코스피 약세
2. Fed 금리 인상 → 달러강세 → 원화약세(위 룰 적용) + 은행NIM 확대(BUY) + 성장주 밸류에이션 하락(SELL)
3. 북한 도발(미사일/핵/포격) → 방산주(012450 한화에어로, 047810 KAI, 064350 현대로템) BUY confidence=0.80, 보유기간=3일, 코스피 단기 -1% 후 회복
4. 중국 부양책/PMI개선 → 화장품(002790 아모레, 051900 LG생건) BUY + 철강(005490 POSCO) BUY + 배터리(373220 LG엔솔, 006400 삼성SDI) BUY
5. HBM/AI칩 수요 급증 → SK하이닉스(000660) 즉시 BUY(1순위) + 한미반도체(042700) BUY + 삼성전자(005930) 2순위 BUY
6. 한은 금리 인하 → 건설(000720 현대건설, 006360 GS건설) BUY + 리츠 BUY + 은행 NIM축소(SELL)
7. 유가 급등 → S-Oil(010950)/GS(078930) BUY + 대한항공(003490) SELL + 롯데케미칼(011170) SELL
"""

SYSTEM_PROMPT = f"""당신은 세계 경제 인과관계 전문가이자 한국 주식시장 전략가입니다.
실제로 일어난 사건을 분석해서 나비효과 체인을 추적합니다.

## 분석 규칙
1. 실제로 일어날 수 있는 인과관계만 추적 (추측 금지)
2. 최대 5단계 체인, 각 단계마다 크기(대/중/소)와 한국 접점 명시
3. confidence는 다음으로 계산: base=0.5, +0.2(역사적 선례), +0.1(직접수혜), -0.1(불확실변수 2개↑), -0.15(지정학포함)
4. 반드시 JSON으로만 응답 (마크다운 코드블록 없이)

{_KOREA_CAUSAL_RULES}

## 응답 형식
{{
  "event_type": "통화정책|무역|지정학|기업실적|원자재|자연재해",
  "summary": "한 줄 요약",
  "chain": [
    {{"step": 1, "event": "사건 설명", "mechanism": "인과 메커니즘", "magnitude": "대|중|소"}}
  ],
  "affected_sectors": ["반도체", "정유"],
  "signals": [
    {{
      "ticker": "005930",
      "name": "삼성전자",
      "direction": "BUY",
      "confidence": 0.75,
      "holding_period": "1-2주",
      "reason": "구체적 이유"
    }}
  ]
}}

signals가 없으면 "signals": [] 반환."""


def _prepare_input(title: str, body: str) -> str:
    """핵심 수치 추출 포함 입력 전처리"""
    if not body:
        return f"제목: {title}"
    import re
    number_sents = [
        s.strip() for s in re.split(r'[.。\n]', body)
        if re.search(r'\d+(\.\d+)?(%|bp|억|조|만달러|달러|원|위안)', s)
    ]
    core = " | ".join(number_sents[:5])
    return (
        f"제목: {title}\n\n"
        f"본문: {body[:2000]}\n\n"
        + (f"핵심수치: {core}" if core else "")
    )


def analyze(title: str, body: str) -> dict | None:
    text = _prepare_input(title, body)
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1500,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # 프롬프트 캐싱 (API 비용 ~90% 절감)
                }],
                messages=[{"role": "user", "content": f"다음 사건의 나비효과를 분석하세요:\n\n{text}"}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except anthropic.RateLimitError:
            import time
            wait = 10 * (2 ** attempt)
            logger.warning("Claude 레이트리밋, %ds 대기 (%d/3)", wait, attempt + 1)
            time.sleep(wait)
        except json.JSONDecodeError:
            logger.error("Claude 응답 JSON 파싱 실패")
            return None
        except Exception as e:
            logger.error("분석 실패 [시도 %d]: %s", attempt + 1, e)
            if attempt == 2:
                return None
            import time
            time.sleep(5)
    return None
