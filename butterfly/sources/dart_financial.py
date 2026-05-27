"""DART 재무데이터 조회 (산업분석 레이어용)
stock_code → 핵심 재무지표 (PER, 부채비율, 영업이익률, ROE)
"""
from __future__ import annotations
import httpx
import logging
from functools import lru_cache
from butterfly.config import DART_API_KEY

logger = logging.getLogger(__name__)
BASE = "https://opendart.fss.or.kr/api"


@lru_cache(maxsize=200)
def get_corp_code(stock_code: str) -> str | None:
    """종목코드 → DART corp_code 변환"""
    if not stock_code or not DART_API_KEY:
        return None
    try:
        r = httpx.get(f"{BASE}/company.json",
                      params={"crtfc_key": DART_API_KEY, "stock_code": stock_code},
                      timeout=8)
        d = r.json()
        if d.get("status") == "000":
            return d.get("corp_code")
    except Exception as e:
        logger.debug("corp_code 조회 실패 [%s]: %s", stock_code, e)
    return None


def get_financials(stock_code: str) -> dict:
    """핵심 재무지표 반환. 실패 시 빈 dict."""
    corp_code = get_corp_code(stock_code)
    if not corp_code:
        return {}
    try:
        import datetime
        year = datetime.date.today().year - 1  # 전년도 사업보고서
        r = httpx.get(f"{BASE}/fnlttSinglAcnt.json", params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",  # 사업보고서
        }, timeout=10)
        d = r.json()
        if d.get("status") != "000":
            return {}
        items = {row["account_nm"]: row for row in d.get("list", [])}

        def _val(name: str) -> float | None:
            row = items.get(name)
            if not row:
                return None
            try:
                return float(str(row.get("thstrm_amount", "")).replace(",", ""))
            except Exception:
                return None

        revenue  = _val("매출액") or _val("영업수익")
        op_profit = _val("영업이익")
        net_profit = _val("당기순이익")
        total_assets = _val("자산총계")
        total_debt = _val("부채총계")
        equity = _val("자본총계")

        result = {}
        if revenue and op_profit and revenue != 0:
            result["operating_margin_pct"] = round(op_profit / revenue * 100, 1)
        if total_debt and equity and equity != 0:
            result["debt_ratio_pct"] = round(total_debt / equity * 100, 1)
        if net_profit and equity and equity != 0:
            result["roe_pct"] = round(net_profit / equity * 100, 1)
        if total_assets:
            result["total_assets_b"] = round(total_assets / 1e8, 0)  # 억원
        return result
    except Exception as e:
        logger.debug("재무지표 조회 실패 [%s]: %s", stock_code, e)
        return {}


def enrich_signals(signals: list[dict]) -> list[dict]:
    """신호 목록에 재무지표 추가"""
    enriched = []
    for s in signals:
        ticker = s.get("ticker", "")
        fin = get_financials(ticker) if ticker else {}
        enriched.append({**s, "financials": fin})
    return enriched
