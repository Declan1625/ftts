"""메르 블로그 (ranto28) - 나비효과 인사이트 원천"""
from __future__ import annotations
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# data_collection 경로를 import 가능하도록 추가
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def fetch() -> list[dict]:
    try:
        from data_collection.blog_scraper import fetch_recent_posts
    except ImportError as e:
        logger.warning("메르 스크래퍼 import 실패: %s", e)
        return []

    items = []
    try:
        posts = fetch_recent_posts(count=3)  # 5→3: 서버 부하 + 속도
        for p in posts:
            items.append({
                "source": "mer",
                "title": p.title,
                "body": p.content[:2000],  # 본문 앞 2000자만
                "url": p.url,
                "published_at": p.published_at,
            })
        if items:
            logger.info("메르 블로그 %d건 수집", len(items))
    except Exception as e:
        logger.warning("메르 수집 실패: %s", e)

    return items
