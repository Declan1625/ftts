"""Reuters RSS 수집기"""
from __future__ import annotations
import feedparser
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.reuters.com/reuters/worldNews",
]


def fetch() -> list[dict]:
    items = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                published = None
                if hasattr(e, "published"):
                    try:
                        published = parsedate_to_datetime(e.published)
                    except Exception:
                        pass
                items.append({
                    "source": "reuters",
                    "title": e.get("title", ""),
                    "body": e.get("summary", ""),
                    "url": e.get("link", ""),
                    "published_at": published,
                })
        except Exception:
            pass
    return items
