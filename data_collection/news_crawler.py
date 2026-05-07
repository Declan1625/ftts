"""data_collection/news_crawler.py — RSS 기반 뉴스 실시간 수집"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2
_REQUEST_INTERVAL = 0.5

_RSS_FEEDS: dict[str, str] = {
    "한국경제": "https://www.hankyung.com/feed/economy",
    "매일경제": "https://www.mk.co.kr/rss/30100041/",
    "연합뉴스 경제": "https://www.yna.co.kr/rss/economy.xml",
    "연합뉴스 증권": "https://www.yna.co.kr/rss/stock.xml",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FTTS-NewsBot/1.0)"
    )
}


@dataclass
class NewsArticle:
    source_name: str
    title: str
    url: str
    summary: str
    published_at: datetime


def crawl_all(max_per_feed: int = 20) -> list[NewsArticle]:
    """등록된 모든 RSS 피드에서 뉴스 수집."""
    articles: list[NewsArticle] = []
    for source_name, feed_url in _RSS_FEEDS.items():
        try:
            fetched = crawl_feed(source_name, feed_url, max_per_feed)
            articles.extend(fetched)
            logger.info("수집 완료 — %s: %d건", source_name, len(fetched))
            time.sleep(_REQUEST_INTERVAL)
        except Exception as exc:
            logger.error("피드 수집 실패 — %s: %s", source_name, exc)
    return articles


def crawl_feed(source_name: str, feed_url: str, max_items: int = 20) -> list[NewsArticle]:
    """단일 RSS 피드 파싱."""
    resp = _get_with_retry(feed_url)
    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")[:max_items]

    articles: list[NewsArticle] = []
    for item in items:
        title = _text(item, "title")
        url = _text(item, "link") or _text(item, "guid")
        summary = _text(item, "description") or ""
        pub_date = _parse_rss_date(_text(item, "pubDate"))

        if not title or not url:
            continue

        articles.append(
            NewsArticle(
                source_name=source_name,
                title=title,
                url=url,
                summary=BeautifulSoup(summary, "html.parser").get_text(strip=True),
                published_at=pub_date,
            )
        )
    return articles


def crawl_since(since: datetime, max_per_feed: int = 50) -> list[NewsArticle]:
    """특정 시각 이후 기사만 반환."""
    all_articles = crawl_all(max_per_feed)
    return [a for a in all_articles if a.published_at >= since]


def _text(tag, name: str) -> str:
    el = tag.find(name)
    return el.get_text(strip=True) if el else ""


def _parse_rss_date(text: str) -> datetime:
    if not text:
        return datetime.utcnow()
    try:
        return parsedate_to_datetime(text).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def _get_with_retry(url: str) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("HTTP 재시도 %d/%d — %s: %s", attempt, _MAX_RETRIES, url, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
    raise RuntimeError(f"요청 실패 ({_MAX_RETRIES}회): {url}") from last_exc
