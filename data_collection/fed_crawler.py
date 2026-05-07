"""data_collection/fed_crawler.py — Fed 연설, FOMC 의사록 수집"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2
_TIMEOUT = 10


def fetch_recent_speeches(days_back: int = 30) -> list[dict]:
    """
    Fed 의장/위원 최근 연설 목록.

    Returns:
        [{"title", "speaker", "date", "url", "summary"}, ...]
    """
    url = "https://www.federalreserve.gov/newsevents/pressreleases.htm"
    results: list[dict] = []

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")

            items = soup.select("div.news-item")
            for item in items[:20]:
                try:
                    title_tag = item.select_one("a")
                    date_tag = item.select_one("span.date")

                    if not title_tag or not date_tag:
                        continue

                    title = title_tag.get_text(strip=True)
                    date_str = date_tag.get_text(strip=True)
                    link = title_tag.get("href", "")

                    if "speech" in title.lower() or "testimony" in title.lower():
                        results.append({
                            "title": title,
                            "date": date_str,
                            "url": link if link.startswith("http") else f"https://www.federalreserve.gov{link}",
                            "source": "Fed",
                        })
                except Exception:
                    continue

            return results
        except Exception as exc:
            last_exc = exc
            logger.warning("Fed 연설 조회 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)

    logger.error("Fed 연설 조회 실패: %s", last_exc)
    return []


def fetch_fomc_minutes(meeting_year: int | None = None) -> list[dict]:
    """
    FOMC 회의 의사록.

    Returns:
        [{"title", "date", "url"}, ...]
    """
    url = "https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm"
    results: list[dict] = []

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")

            links = soup.select("a[href*='minutes']")
            for link in links[:15]:
                try:
                    text = link.get_text(strip=True)
                    href = link.get("href", "")

                    if "minutes" in href.lower() or "minutes" in text.lower():
                        results.append({
                            "title": f"FOMC Minutes - {text}",
                            "url": href if href.startswith("http") else f"https://www.federalreserve.gov{href}",
                            "source": "FOMC",
                        })
                except Exception:
                    continue

            return results
        except Exception as exc:
            last_exc = exc
            logger.warning("FOMC 의사록 조회 재시도 %d/%d: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)

    logger.error("FOMC 의사록 조회 실패: %s", last_exc)
    return []


def fetch_fed_rate_decision() -> dict | None:
    """최근 Fed 금리 결정 발표."""
    url = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm"

    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        title = soup.select_one("h3")
        content = soup.select_one("div.col-xs-12")

        if title and content:
            return {
                "title": title.get_text(strip=True),
                "content": content.get_text(strip=True)[:2000],
                "date": datetime.now().isoformat(),
                "source": "Fed",
            }
        return None
    except Exception as exc:
        logger.error("Fed 금리 결정 조회 실패: %s", exc)
        return None
