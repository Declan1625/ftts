"""Fed(연준) 발표 RSS 수집기"""
from __future__ import annotations
import httpx
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

FEEDS = [
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.federalreserve.gov/feeds/speeches.xml",
]


def fetch() -> list[dict]:
    items = []
    for url in FEEDS:
        try:
            r = httpx.get(url, timeout=10, follow_redirects=True)
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                link = item.findtext("link", "")
                pub = item.findtext("pubDate", "")
                published = None
                if pub:
                    try:
                        published = parsedate_to_datetime(pub)
                    except Exception:
                        pass
                items.append({
                    "source": "fed",
                    "title": title,
                    "body": desc,
                    "url": link,
                    "published_at": published,
                })
        except Exception:
            pass
    return items
