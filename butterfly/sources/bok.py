"""한국은행 (BOK) - 금리 결정, 경제전망, 보도자료"""
from __future__ import annotations
import httpx
import xml.etree.ElementTree as ET

FEEDS = [
    "https://www.bok.or.kr/portal/bbs/P0000559/list.do?menuNo=200690&pageIndex=1&searchCnd=1&searchKwd=&rssYn=Y",
]


def fetch() -> list[dict]:
    items = []
    for url in FEEDS:
        try:
            r = httpx.get(url, timeout=10, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:10]:
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                link = item.findtext("link", "")
                items.append({
                    "source": "bok",
                    "title": f"[한국은행] {title}",
                    "body": desc,
                    "url": link,
                    "published_at": None,
                })
        except Exception:
            pass
    return items
