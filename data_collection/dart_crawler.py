"""data_collection/dart_crawler.py — DART API 한국 공시 수집"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_DART_API_KEY = "DART_API_KEY"  # .env에서 로드 필요
_DART_BASE_URL = "https://opendart.fss.or.kr/api"
_MAX_RETRIES = 3
_RETRY_DELAY = 2
_TIMEOUT = 10


def fetch_recent_disclosures(
    days_back: int = 7,
    company_codes: list[str] | None = None,
) -> list[dict]:
    """
    최근 공시 목록 조회.

    Args:
        days_back: 며칠 전 공시까지 수집
        company_codes: 특정 기업 코드 필터 (없으면 전체)

    Returns:
        공시 정보 리스트 [{"crp_code", "title", "disclosure_date", "report_nm", ...}]
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back)

    params = {
        "crtfc_key": _DART_API_KEY,
        "bgn_de": start_date.strftime("%Y%m%d"),
        "end_de": end_date.strftime("%Y%m%d"),
        "last_reprt_at": "Y",
        "page_count": 100,
    }

    if company_codes:
        params["crp_cd"] = ";".join(company_codes)

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(
                f"{_DART_BASE_URL}/list.json",
                params=params,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "000":
                logger.warning("DART API 오류: %s", data.get("message"))
                return []

            return data.get("list", [])
        except Exception as exc:
            last_exc = exc
            logger.warning("DART 조회 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)

    logger.error("DART 조회 실패: %s", last_exc)
    return []


def fetch_disclosure_content(report_code: str) -> str | None:
    """특정 공시의 상세 내용 조회."""
    params = {
        "crtfc_key": _DART_API_KEY,
        "rcp_no": report_code,
    }

    try:
        resp = requests.get(
            f"{_DART_BASE_URL}/document.json",
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "000":
            return None

        return data.get("document", "")
    except Exception as exc:
        logger.error("DART 상세 조회 실패: %s", exc)
        return None


def get_company_code(company_name: str) -> str | None:
    """기업명 → DART 코드 조회."""
    params = {
        "crtfc_key": _DART_API_KEY,
        "keyword": company_name,
        "page_count": 10,
    }

    try:
        resp = requests.get(
            f"{_DART_BASE_URL}/corpCode.json",
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "000":
            return None

        items = data.get("list", [])
        if items:
            return items[0].get("corp_code")
        return None
    except Exception as exc:
        logger.error("기업 코드 조회 실패: %s", exc)
        return None
