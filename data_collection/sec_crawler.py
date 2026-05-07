"""data_collection/sec_crawler.py — SEC EDGAR 미국 상장사 공시 수집"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_SEC_API_URL = "https://data.sec.gov/api/xbrl"
_SEC_CIKS_URL = "https://www.sec.gov/files/company_tickers.json"
_MAX_RETRIES = 3
_RETRY_DELAY = 2
_TIMEOUT = 10


def fetch_company_filings(
    ticker: str,
    form_types: list[str] | None = None,
    days_back: int = 30,
) -> list[dict]:
    """
    특정 상장사의 최근 공시.

    Args:
        ticker: 미국 주식 티커 (e.g., "AAPL")
        form_types: 공시 유형 (e.g., ["10-K", "8-K", "10-Q"])
        days_back: 며칠 전 공시까지

    Returns:
        [{"ticker", "form_type", "filing_date", "accession_number", ...}]
    """
    if form_types is None:
        form_types = ["10-K", "10-Q", "8-K"]

    cik = _get_cik_from_ticker(ticker)
    if not cik:
        logger.warning("CIK 조회 실패: %s", ticker)
        return []

    results: list[dict] = []
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            filings = data.get("filings", {}).get("recent", {})
            forms = filings.get("form", [])
            accession = filings.get("accessionNumber", [])
            file_date = filings.get("filingDate", [])

            cutoff = (datetime.now() - timedelta(days=days_back)).date()

            for i, form in enumerate(forms):
                if form in form_types:
                    filing_dt = datetime.strptime(file_date[i], "%Y-%m-%d").date()
                    if filing_dt >= cutoff:
                        results.append({
                            "ticker": ticker,
                            "form_type": form,
                            "filing_date": file_date[i],
                            "accession_number": accession[i],
                            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=exclude&count=100",
                        })

            return results
        except Exception as exc:
            last_exc = exc
            logger.warning("SEC 공시 조회 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)

    logger.error("SEC 공시 조회 실패: %s", last_exc)
    return []


def fetch_filing_text(accession_number: str) -> str | None:
    """공시 전문 조회."""
    accession_clean = accession_number.replace("-", "")
    url = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={accession_clean[:10]}&accession_number={accession_number}&xbrl_type=v"

    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text[:5000]
    except Exception as exc:
        logger.error("SEC 공시 전문 조회 실패: %s", exc)
        return None


def _get_cik_from_ticker(ticker: str) -> str | None:
    """티커 → CIK 변환."""
    try:
        resp = requests.get(_SEC_CIKS_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)

        return None
    except Exception as exc:
        logger.error("CIK 조회 실패: %s", exc)
        return None
