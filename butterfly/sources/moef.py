"""기획재정부 (MOEF) - 한국 정부 경제 정책 보도자료"""
from __future__ import annotations
import httpx
import xml.etree.ElementTree as ET

FEEDS = [
    "https://www.moef.go.kr/nw/nes/detailNesDtaView.do?searchBbsId=MOSFBBS_000000000028&menuNo=4010100&rssYn=Y",
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
                    "source": "moef",
                    "title": f"[기재부] {title}",
                    "body": desc,
                    "url": link,
                    "published_at": None,
                })
        except Exception:
            pass
    return items
