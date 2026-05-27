"""산업/기업 분석 레이어
나비효과 1차 분석(섹터) → 2차 분석(기업 선별)
밸류체인 포지션 + DART 재무지표 → 신호 신뢰도 정제
"""
from __future__ import annotations
import json
import logging
import os
import anthropic

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


# 섹터별 밸류체인 힌트 (Claude 컨텍스트 강화용)
_SECTOR_CHAIN: dict[str, str] = {
    "반도체": "장비(ASML·한미반도체)→소재(솔브레인·동진쎄미켐)→파운드리(삼성·DB하이텍)→팹리스→메모리(삼성·SK하이닉스)",
    "배터리": "리튬·니켈 원재료→양극재(에코프로·포스코퓨처엠)→음극재·전해액→셀(LG엔솔·삼성SDI)→팩→완성차",
    "방산": "원자재→부품(한화시스템·LIG넥스원)→체계종합(한국항공우주·현대로템)→수출",
    "자동차": "철강·알루미늄→부품(현대모비스·만도)→완성차(현대·기아)→딜러·할부금융",
    "바이오": "원료의약품→임상CRO→신약개발→CMO(삼성바이오)→유통",
    "조선": "철강→기자재(HSD엔진·한화오션)→조선소(HD현대·삼성중공업)→운영",
    "전력": "발전설비(두산에너빌리티)→송배전(LS전선)→스마트그리드→수요",
    "화장품": "원료→ODM(코스맥스·한국콜마)→브랜드(아모레·LG생활건강)→유통·면세",
}


def _build_prompt(event: str, sectors: list[str], signals: list[dict]) -> str:
    chain_hints = "\n".join(
        f"- {sec}: {_SECTOR_CHAIN[sec]}"
        for sec in sectors if sec in _SECTOR_CHAIN
    )

    fin_summary = []
    for s in signals:
        fin = s.get("financials", {})
        parts = [f"{s.get('name', s.get('ticker', ''))}({s.get('ticker', '')})"]
        if fin.get("operating_margin_pct") is not None:
            parts.append(f"영업이익률 {fin['operating_margin_pct']}%")
        if fin.get("debt_ratio_pct") is not None:
            parts.append(f"부채비율 {fin['debt_ratio_pct']}%")
        if fin.get("roe_pct") is not None:
            parts.append(f"ROE {fin['roe_pct']}%")
        fin_summary.append(" / ".join(parts))

    return f"""한국 주식 시장 산업/기업 분석 전문가로서 답하라.

[이벤트]
{event}

[영향 섹터]
{', '.join(sectors)}

[밸류체인 구조]
{chain_hints or '일반 섹터'}

[후보 종목 및 재무지표]
{chr(10).join(fin_summary) if fin_summary else '재무데이터 없음'}

각 후보 종목에 대해 아래를 분석하라:
1. 밸류체인 내 포지션 (직접 수혜/간접/무관)
2. 이벤트 직접 노출도 (HIGH/MEDIUM/LOW)
3. 재무 안정성 (부채비율, 수익성 기반)
4. 최종 신뢰도 조정 점수 (0.0~1.0)

반드시 아래 JSON만 출력하라:
{{
  "analysis": "2줄 요약",
  "signals": [
    {{
      "ticker": "종목코드",
      "value_chain_pos": "직접수혜|간접수혜|무관",
      "exposure": "HIGH|MEDIUM|LOW",
      "financial_score": 0.0~1.0,
      "adjusted_confidence": 0.0~1.0,
      "reason": "한줄 근거"
    }}
  ]
}}"""


def analyze(event: str, sectors: list[str], signals: list[dict]) -> list[dict]:
    """
    signals: enrich_signals()로 재무데이터가 추가된 신호 목록
    반환: adjusted_confidence가 갱신된 신호 목록
    """
    if not signals:
        return signals

    # 재무데이터나 섹터 없으면 스킵 (비용 절약)
    has_fin = any(s.get("financials") for s in signals)
    has_chain = any(sec in _SECTOR_CHAIN for sec in sectors)
    if not has_fin and not has_chain:
        logger.debug("산업분석 스킵: 재무데이터·밸류체인 정보 없음")
        return signals

    try:
        prompt = _build_prompt(event, sectors, signals)
        resp = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",   # 비용 최적화 (단순 분류 작업)
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

        # JSON 파싱
        start = raw.find("{")
        if start == -1:
            return signals
        import json as _json
        result, _ = _json.JSONDecoder().raw_decode(raw, start)

        adj_map = {
            r["ticker"]: r
            for r in result.get("signals", [])
            if "ticker" in r
        }

        refined = []
        for s in signals:
            adj = adj_map.get(s.get("ticker", ""))
            if adj:
                new_conf = adj.get("adjusted_confidence", s.get("confidence", 0.5))
                refined.append({
                    **s,
                    "confidence": new_conf,
                    "value_chain_pos": adj.get("value_chain_pos", ""),
                    "exposure": adj.get("exposure", ""),
                    "industry_reason": adj.get("reason", ""),
                })
                logger.info("🏭 산업분석 [%s] %s → 신뢰도 %.2f→%.2f",
                            s.get("ticker"), adj.get("value_chain_pos", ""),
                            s.get("confidence", 0), new_conf)
            else:
                refined.append(s)

        logger.info("산업분석 완료: %s | %s", result.get("analysis", "")[:50],
                    " ".join(f"{r['ticker']}:{r.get('adjusted_confidence',0):.2f}"
                             for r in result.get("signals", [])))
        return refined

    except Exception as e:
        logger.warning("산업분석 실패 (원본 신호 유지): %s", e)
        return signals
