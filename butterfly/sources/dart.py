"""DART 공시 수집기 (본문 포함)"""
from __future__ import annotations
import httpx
import logging
from datetime import datetime, timedelta, timezone
from butterfly.config import DART_API_KEY

logger = logging.getLogger(__name__)
BASE = "https://opendart.fss.or.kr/api"

IMPORTANT_REPORTS = [
    "영업(잠정)실적", "유상증자", "무상증자", "합병", "분할", "영업양수도",
    "자기주식취득", "전환사채", "신주인수권", "최대주주변경", "상장폐지",
]


def fetch() -> list[dict]:
    bgn_de = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    try:
        r = httpx.get(f"{BASE}/list.json", params={
            "crtfc_key": DART_API_KEY,
            "bgn_de": bgn_de,
            "page_count": 40,
        }, timeout=10)
        data = r.json()
        if data.get("status") != "000":
            return []
        items = []
        for doc in data.get("list", []):
            report_nm = doc.get("report_nm", "")
            if not any(k in report_nm for k in IMPORTANT_REPORTS):
                continue
            body = _fetch_body(doc.get("rcept_no", ""))
            items.append({
                "source": "dart",
                "title": f"[{doc['corp_name']}] {report_nm}",
                "body": body,
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={doc['rcept_no']}",
                "published_at": _parse_date(doc.get("rcept_dt", "")),
                "ticker": doc.get("stock_code", ""),
            })
        return items
    except Exception as e:
        logger.error("DART 수집 실패: %s", e)
        return []


def _fetch_body(rcept_no: str) -> str:
    try:
        r = httpx.get(f"{BASE}/document.json", params={
            "crtfc_key": DART_API_KEY,
            "rcept_no": rcept_no,
        }, timeout=10)
        data = r.json()
        return data.get("body", "")[:3000]
    except Exception:
        return ""


def _parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None
