"""매일경제 RSS"""
from __future__ import annotations
import httpx
import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

FEEDS = [
    "http://file.mk.co.kr/news/rss/rss_30100041.xml",  # 경제
    "http://file.mk.co.kr/news/rss/rss_50200011.xml",  # 증권
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
                pub = item.findtext("pubDate", "")
                published = None
                if pub:
                    try:
                        published = parsedate_to_datetime(pub)
                    except Exception as e:
                        logger.warning("날짜 파싱 실패: %s", e)
                if title:
                    items.append({
                        "source": "mk",
                        "title": title,
                        "body": desc,
                        "url": link,
                        "published_at": published,
                    })
        except Exception as e:
            logger.warning("수집 실패 [%s]: %s", url, e)
    return items
