"""Fed(연준) 발표 RSS 수집기"""
from __future__ import annotations
import feedparser
from email.utils import parsedate_to_datetime

FEEDS = [
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.federalreserve.gov/feeds/speeches.xml",
]


def fetch() -> list[dict]:
    items = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                published = None
                if hasattr(e, "published"):
                    try:
                        published = parsedate_to_datetime(e.published)
                    except Exception:
                        pass
                items.append({
                    "source": "fed",
                    "title": e.get("title", ""),
                    "body": e.get("summary", ""),
                    "url": e.get("link", ""),
                    "published_at": published,
                })
        except Exception:
            pass
    return items
