"""나비효과 분석기: 사건 → 파장 체인 → 한국 종목"""
from __future__ import annotations
import json
import logging
import re
import anthropic
from butterfly.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_KOREA_CAUSAL_RULES = """
## 한국 시장 인과관계 룰북 (v2.0)

### A. 미국 통화/금리 (Fed)
A1. Fed 금리 인상 → 달러강세 → 원/달러 상승 → 외국인 코스피 매도, 수출주 환차익 BUY (005930 삼성전자, 000270 기아), 성장주 멀티플 축소 SELL (035420 NAVER, 035720 카카오)
A2. Fed 금리 인하 → 달러약세 → 원화강세 → 외국인 순매수 복귀, 코스피 +2~5%, 성장주/바이오 BUY (035420, 207940 삼성바이오), 수출주 단기 약세
A3. FOMC 점도표 매파 전환 → 장기금리 급등 → 부동산/리츠 SELL (395400 SK리츠), 은행NIM 확대 BUY (105560 KB금융, 055550 신한지주)
A4. FOMC 비둘기 신호 → 위험자산 랠리 → 2차전지/바이오 BUY (373220 LG에너지솔루션, 006400 삼성SDI), 코스닥 +3%↑
A5. 미 CPI 서프라이즈 상회 → 금리 인상 베팅 → 달러강세 + 성장주 SELL, 다음날 코스피 -1.5%
A6. 미 CPI 하회 → 인하 베팅 → 코스피 +2%, 외국인 선물 매수, 반도체/바이오 BUY
A7. 미 고용 NFP 호조 + 임금상승 → 인플레 우려 → 안전자산(원화약세), 수출주 BUY
A8. 잭슨홀/파월 매파 발언 → 단기 코스피 -2%, 환율 +20원, 성장주 단기 SELL

### B. 한국 통화/금리 (BOK)
B1. 한은 금리 인상 → 가계대출 위축 → 건설 SELL (000720 현대건설, 047040 대우건설), 은행 NIM 확대 BUY (105560)
B2. 한은 금리 인하 → 부동산/리츠 BUY (395400 SK리츠, 088260 이리츠코크렙), 내수소비주 BUY (097950 CJ제일제당, 069960 현대백화점)
B3. 한은 동결 + 매파 톤 → 환율 +10원 단기 상승, 변동성 확대
B4. 한미 금리차 200bp 이상 확대 → 외국인 채권자금 유출 → 코스피 약세, 환율 +30원

### C. 환율 (USD/KRW, JPY, CNY)
C1. 원/달러 1,400원 돌파 → 수출 비중 70%+ 기업 BUY (005930, 000270, 005380 현대차), 항공/여행 SELL (003490 대한항공, 020560 아시아나)
C2. 원/달러 급락(원강세) → 외국인 차익실현 → 수출주 SELL, 내수주 BUY (097950 CJ제일제당)
C3. 엔화약세(USD/JPY 155+) → 일본車/철강과 가격경쟁 심화 → 현대차/POSCO 단기 SELL
C4. 위안화약세 → 화장품 SELL (090430 아모레퍼시픽), 화학 SELL (009830 한화솔루션)
C5. 위안화강세 → K-뷰티/면세 BUY (090430, 008770 호텔신라)

### D. 원자재
D1. WTI 80달러 돌파 → 정유 BUY (010950 S-Oil, 096770 SK이노베이션, 078930 GS), 항공 SELL (003490)
D2. WTI 급락(60$ 이하) → 항공/해운 BUY (003490, 011200 HMM), 정유 SELL
D3. 천연가스 급등 → LNG선 수요 → 조선 BUY (009540 HD한국조선해양, 042660 한화오션)
D4. 리튬가격 반등 → 2차전지 양극재 BUY (003670 포스코퓨처엠, 247540 에코프로비엠)
D5. 구리 급등 → 글로벌 경기회복 신호 → 비철금속 BUY (010130 고려아연), 코스피 위험선호
D6. 금 사상최고 → 안전자산 선호 → 코스피 변동성 확대
D7. 철광석 급등 + 중국 부양책 → 철강 BUY (005490 POSCO홀딩스, 004020 현대제철)
D8. 우라늄 가격 상승 → 원전 BUY (034020 두산에너빌리티, 052690 한전기술)

### E. 지정학
E1. 북한 미사일 발사 → 방산 BUY (012450 한화에어로스페이스, 047810 KAI, 064350 현대로템), 보유기간 3-5일, 코스피 단기 -1% 후 회복
E2. 북한 핵실험 → 방산 BUY 강하게 + 외국인 일시 이탈 → 1주 후 회복
E3. 우크라이나 정전협상 → 방산 단기 SELL, 곡물/에너지 SELL
E4. 우크라이나 분쟁 격화 → 방산 BUY + 곡물가/에너지 상승 → 정유 BUY
E5. 대만해협 긴장 → TSMC 리스크 → 삼성/하이닉스 반사이익 BUY (005930, 000660)
E6. 중동 분쟁 격화 → 유가 급등 → 정유 BUY, 항공 SELL, 방산 BUY
E7. 미중 무역분쟁 격화 → 중국매출 비중 높은 기업 SELL (090430 아모레, 003670 포스코퓨처엠)
E8. 미국 對中 반도체 제재 강화 → 삼성/하이닉스 단기 충격 SELL → 중장기 반사이익 BUY
E9. 한미일 안보협력 강화 → 방산 + 반도체 BUY

### F. 반도체 (FTTS 핵심 섹터)
F1. HBM 수요 급증/공급부족 → 1순위 SK하이닉스(000660) BUY conf=0.85, 2순위 삼성전자(005930) BUY conf=0.70, 한미반도체(042700) BUY conf=0.75
F2. DRAM 현물가 반등 → 메모리 사이클 회복 → 삼성/하이닉스 BUY + 솔브레인(357780) BUY
F3. DRAM 현물가 하락 → 메모리 약세 → 삼성/하이닉스 단기 SELL, 단 -20%↑ 누적 시 저가매수 BUY
F4. NVIDIA 실적 서프라이즈 → HBM 공급사 BUY 강하게 (000660, 042700)
F5. NVIDIA 가이던스 하향 → AI 사이클 우려 → 반도체 전반 SELL 단기
F6. TSMC 가동률 상승 → 한국 파운드리 경쟁 → 삼성전자 단기 약세
F7. 마이크론 실적 호조 → 메모리 동조 → SK하이닉스 BUY
F8. 미국 반도체법(CHIPS) 보조금 발표 → 삼성/하이닉스 미국공장 수혜 BUY
F9. AI 데이터센터 CapEx 확대 (MSFT/META/GOOGL) → HBM/네트워킹 BUY (000660, 042700, 058470 리노공업)
F10. 낸드 가격 반등 → 삼성전자 BUY (낸드 비중 30%+)

### G. 2차전지/EV
G1. 미국 EV 세액공제(IRA) 확대 → 배터리 3사 BUY (373220 LG엔솔, 006400 삼성SDI, 247540 에코프로비엠)
G2. IRA 후퇴/축소 → 배터리 SELL 강하게
G3. 테슬라 출하량 호조 → LG에너지솔루션 BUY (테슬라향 공급)
G4. 중국 CATL 점유율 상승 → 한국 배터리 SELL 단기
G5. LFP 채용 확대 → NCM 위주 한국 배터리 우려 → 단 양극재/분리막은 중립
G6. 전고체 배터리 진척 → 삼성SDI BUY
G7. 현대차 EV 판매 호조 → 부품주 BUY (009830 한화솔루션)
G8. 폭스바겐/포드 EV 감산 → 한국 배터리 단기 SELL

### H. 자동차
H1. 미국 신차 판매 호조 → 현대차/기아 BUY (005380, 000270)
H2. 미국 자동차 관세 부과 → 현대차/기아 SELL 강하게 + 부품주 SELL
H3. 현대차 미국 공장 증설 발표 → 부품주 BUY (011210 현대위아, 018880 한온시스템)
H4. 유럽 신차 판매 부진 → 기아 SELL (유럽 비중 25%+)
H5. 중국 시장 점유율 회복 → 현대차 BUY

### I. 조선/원전
I1. LNG선 발주 급증 → HD한국조선해양(009540) BUY, 한화오션(042660) BUY, 삼성중공업(010140) BUY
I2. 컨테이너선 운임(SCFI) 급등 → HMM(011200) BUY 강하게
I3. 친환경선박 규제 강화(IMO) → 조선 3사 BUY 중장기
I4. 중국 조선 수주 점유율 확대 → 한국 조선 SELL 단기
I5. 원전 수출 수주(체코/폴란드) → 두산에너빌리티(034020) BUY, 한전기술(052690) BUY

### J. 바이오/제약
J1. FDA 임상3상 성공 발표 → 해당 기업 BUY 강하게 conf=0.85, 보유 3-7일
J2. FDA 신약 승인 → BUY conf=0.80
J3. 임상 실패/CRL 수령 → SELL 강하게 conf=0.85
J4. 빅파마 기술이전(L/O) 계약 → BUY conf=0.80 (128940 한미약품, 195940 HK이노엔)
J5. 셀트리온 바이오시밀러 미국 출시 → 셀트리온(068270) BUY
J6. 美 IRA 약가협상 우려 → K-바이오 SELL 단기

### K. 방산
K1. 폴란드/사우디/UAE 무기수출 계약 → 한화에어로(012450) BUY 강하게, KAI(047810) BUY
K2. K2전차 추가수주 → 현대로템(064350) BUY conf=0.85
K3. K9자주포 수출 → 한화에어로 BUY
K4. T-50 전투기 수출 → KAI BUY
K5. 미 국방예산 확대 → 방산 전반 BUY 중장기

### L. 화장품/K-콘텐츠
L1. 중국 단체관광 재개 → 아모레(090430), LG생건(051900), 호텔신라(008770) BUY
L2. K-팝 글로벌 흥행 → 하이브(352820), JYP(035900), SM(041510), YG(122870) BUY
L3. 중국 한한령 완화 → 화장품/콘텐츠 BUY 강하게
L4. 면세점 매출 회복 → 호텔신라(008770), 신세계(004170) BUY
L5. 넷플릭스 한국 콘텐츠 흥행 → 스튜디오드래곤(253450), 콘텐트리중앙(036420) BUY

### M. 화학/철강
M1. 중국 부양책 발표 → POSCO(005490), 현대제철(004020), LG화학(051910), 롯데케미칼(011170) BUY
M2. 중국 PMI 50 회복 → 화학/철강 BUY
M3. 중국 부동산 위기 심화 → 철강/화학 SELL
M4. 미국 인프라법 집행 → 강관/철강 BUY

### N. 금융/건설
N1. 부동산 PF 부실 우려 → 증권사 SELL
N2. 은행 배당확대 정책 → 금융지주 BUY (105560 KB, 055550 신한, 086790 하나, 316140 우리)
N3. 보험사 IFRS17 호조 → 삼성생명(032830), 한화생명(088350) BUY
N4. 부동산 규제 완화 → 건설 BUY (000720 현대건설, 028050 삼성E&A)
N5. 사우디 네옴시티 진척 → 건설/플랜트 BUY (000720, 028050)

### O. 통신/유틸/AI인프라
O1. 5G/6G 투자확대 → 통신장비 BUY (017670 SKT, 030200 KT)
O2. AI 데이터센터 전력 수요 → 한전(015760), 두산에너빌리티(034020) BUY
O3. 전기료 인상 → 한전 BUY, 제조원가 부담주 SELL

### P. 게임/엔터
P1. 신작 흥행 → 해당 게임사 BUY 단기 (036570 엔씨소프트, 251270 넷마블, 293490 카카오게임즈)
P2. 중국 판호 발급 → 게임사 BUY 강하게
P3. 신작 출시 지연/실패 → SELL

### Q. 계절성/수급
Q1. 3-4월 배당락 전 고배당주 매수 강세 → 통신/금융 BUY
Q2. 갤럭시 S 시리즈 출시(1-2월) → 삼성전자/부품주 BUY
Q3. 미 블랙프라이데이 → 가전/디스플레이 BUY (066570 LG전자)
Q4. 중국 광군제 → 화장품/면세 BUY
Q5. 외국인 5일 연속 순매수/매도 → 코스피 모멘텀 동조
Q6. MSCI 정기변경 편입/편출 → 해당 종목 ±5~10% 단기

## confidence 계산 (개정)
- base = 0.5
- +0.20: 룰북 직접 매칭 (예: HBM 룰 F1)
- +0.15: 역사적 선례 3회 이상
- +0.10: 직접 수혜 (간접 영향은 +0.05)
- +0.10: 환율/유가 등 거시 동조
- -0.10: 불확실 변수 2개 이상
- -0.15: 지정학 리스크 포함
- -0.10: 이미 시장 반영(48h+ 경과)
상한 0.95, 하한 0.30 미만은 신호 생성 불가
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


def _extract_json(raw: str) -> dict | None:
    """Claude 응답에서 JSON 객체 추출 — 코드블록/앞뒤 텍스트 무시"""
    text = re.sub(r"```(?:json)?", "", raw).strip()
    # 첫 { 부터 추출 시도 (JSONDecoder 자동 경계 탐지)
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return obj
    except json.JSONDecodeError:
        pass
    # fallback: greedy 매치 후 파싱
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


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
    from butterfly.config import CLAUDE_ENABLED
    if not CLAUDE_ENABLED:
        logger.info("🔇 CLAUDE_ENABLED=false — Claude 호출 차단")
        return None
    text = _prepare_input(title, body)
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # 프롬프트 캐싱 (API 비용 ~90% 절감)
                }],
                messages=[{"role": "user", "content": f"다음 사건의 나비효과를 분석하세요:\n\n{text}"}],
            )
            raw = resp.content[0].text.strip()
            extracted = _extract_json(raw)
            if extracted is None:
                logger.error("Claude JSON 파싱 실패 | 원문(200자): %s", raw[:200])
                if attempt < 2:
                    import time; time.sleep(5)
                    continue
                return None
            return extracted
        except anthropic.RateLimitError:
            import time
            wait = 10 * (2 ** attempt)
            logger.warning("Claude 레이트리밋, %ds 대기 (%d/3)", wait, attempt + 1)
            time.sleep(wait)
        except anthropic.BadRequestError as e:
            # 크레딧 부족 등 재시도 불가 에러 → 즉시 중단
            msg = str(e)
            if "credit balance" in msg or "billing" in msg.lower():
                logger.error("🚨 Anthropic 크레딧 부족 — console.anthropic.com에서 충전 필요")
                return None  # 파이프라인 전체 멈추지 않게 None 반환
            logger.error("분석 실패 (재시도불가): %s", e)
            return None
        except Exception as e:
            logger.error("분석 실패 [시도 %d]: %s", attempt + 1, e)
            if attempt == 2:
                return None
            import time
            time.sleep(5)
    return None


def analyze_batch(events_data: list[tuple[str, str]]) -> list[dict | None]:
    """여러 이벤트를 Batch API로 한 번에 분석 — 50% 비용 절감"""
    from butterfly.config import CLAUDE_ENABLED
    if not CLAUDE_ENABLED:
        logger.info("🔇 CLAUDE_ENABLED=false — Batch API 차단 (%d건 스킵)", len(events_data))
        return [None] * len(events_data)
    if not events_data:
        return []
    import time
    requests_list = [
        {
            "custom_id": f"ev-{i}",
            "params": {
                "model": ANTHROPIC_MODEL,
                "max_tokens": 2000,
                "system": [{"type": "text", "text": SYSTEM_PROMPT,
                             "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content":
                               f"다음 사건의 나비효과를 분석하세요:\n\n{_prepare_input(t, b)}"}],
            }
        }
        for i, (t, b) in enumerate(events_data)
    ]
    try:
        batch = client.messages.batches.create(requests=requests_list)
        logger.info("Batch API 제출: %d건 (id=%s)", len(events_data), batch.id)

        deadline = time.time() + 300  # 5분 타임아웃
        while time.time() < deadline:
            batch = client.messages.batches.retrieve(batch.id)
            if batch.processing_status == "ended":
                break
            time.sleep(10)
        else:
            logger.warning("Batch API 타임아웃 — 개별 분석으로 fallback")
            return [analyze(t, b) for t, b in events_data]

        results: list[dict | None] = [None] * len(events_data)
        for item in client.messages.batches.results(batch.id):
            idx = int(item.custom_id.split("-")[1])
            if item.result.type == "succeeded":
                raw = item.result.message.content[0].text.strip()
                results[idx] = _extract_json(raw)
        return results
    except Exception as e:
        logger.error("Batch API 실패 (%s) — 개별 분석으로 fallback", e)
        return [analyze(t, b) for t, b in events_data]
