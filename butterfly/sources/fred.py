"""FRED (미 연준 경제데이터) - 거시 나비효과 핵심 지표"""
from __future__ import annotations
import logging
import httpx
from butterfly import config

logger = logging.getLogger(__name__)

# 나비효과에서 중요한 지표들
# (series_id, 설명, 왜 중요한가)
SERIES = [
    ("DGS10",    "미 10년물 국채금리",    "성장주 할인율 → 코스닥 나비효과"),
    ("FEDFUNDS", "연준 기준금리",         "전세계 유동성 → 한국 외국인 수급"),
    ("DEXKOUS",  "원/달러 환율",          "수출기업 실적 직결"),
    ("CPIAUCSL", "미국 CPI(물가)",        "금리 방향 결정 → 전체 시장"),
    ("UNRATE",   "미국 실업률",           "경기 사이클 판단"),
    ("DEXCHUS",  "위안/달러 환율",        "중국 경기 → 한국 소재/반도체"),
]

BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch() -> list[dict]:
    if not config.FRED_API_KEY:
        logger.debug("FRED_API_KEY 미설정, 스킵")
        return []

    items = []
    for series_id, name, reason in SERIES:
        try:
            r = httpx.get(BASE, params={
                "series_id": series_id,
                "api_key": config.FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 2,
            }, timeout=10)
            data = r.json()
            obs = data.get("observations", [])
            if len(obs) >= 2:
                latest = obs[0]
                prev = obs[1]
                val = latest.get("value", ".")
                prev_val = prev.get("value", ".")
                if val == "." or prev_val == ".":
                    continue
                change = float(val) - float(prev_val)
                direction = "상승" if change > 0 else "하락"
                title = f"[FRED] {name} {direction}: {prev_val} → {val} ({change:+.3f})"
                items.append({
                    "source": "fred",
                    "title": title,
                    "body": f"{name}({series_id}) 최신값={val}, 전일={prev_val}. 나비효과: {reason}",
                    "url": f"https://fred.stlouisfed.org/series/{series_id}",
                    "published_at": None,
                })
        except Exception as e:
            logger.warning("FRED %s 수집 실패: %s", series_id, e)

    return items
