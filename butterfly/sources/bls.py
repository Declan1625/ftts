"""BLS (미국 노동통계국) - 고용, CPI, PPI 발표"""
from __future__ import annotations
import httpx
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

FEEDS = [
    "https://www.bls.gov/feed/bls_latest.rss",
]


def fetch() -> list[dict]:
    items = []
    for url in FEEDS:
        try:
            r = httpx.get(url, timeout=10, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:10]:
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
                    "source": "bls",
                    "title": f"[BLS] {title}",
                    "body": desc,
                    "url": link,
                    "published_at": published,
                })
        except Exception:
            pass
    return items
