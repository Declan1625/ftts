"""data_collection/trump_scraper.py — 트럼프 X(트위터) 포스팅 스크래퍼"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2
_TIMEOUT = 10

# 트럼프 X 계정: @realDonaldTrump (또는 @Trump)
_TRUMP_HANDLES = ["realDonaldTrump", "Trump"]


def fetch_trump_posts(
    days_back: int = 7,
    limit: int = 20,
) -> list[dict]:
    """
    트럼프 X 포스팅 수집 (API 없이 웹 스크래핑).

    Returns:
        [{"text", "date", "url", "likes", "retweets", "source": "Trump X"}, ...]

    주의: X API는 인증 필요. 여기서는 공개 정보 기반 스크래핑.
    """
    results: list[dict] = []

    # nitter (X 미러) 또는 공개 API 사용
    # 실제 구현: twitter-api-v2 또는 tweepy 라이브러리 권장
    # 여기서는 폴백 구현 (모의 데이터)

    try:
        for handle in _TRUMP_HANDLES:
            posts = _fetch_from_mirror(handle, days_back, limit)
            results.extend(posts)
        return results
    except Exception as exc:
        logger.error("Trump X 포스팅 수집 실패: %s", exc)
        return []


def _fetch_from_mirror(handle: str, days_back: int, limit: int) -> list[dict]:
    """
    공개 X 미러 (nitter) 또는 fallback에서 데이터 수집.

    실제 운영 환경에서는:
    - twitter-api-v2 (Elon 공식 API) 또는
    - tweepy 라이브러리 사용 권장
    """
    results: list[dict] = []
    last_exc: Exception | None = None

    # Nitter 공개 인스턴스 (API 가 필요 없는 웹 스크래핑)
    nitter_instances = [
        "https://nitter.poast.org",
        "https://nitter.lunar.icu",
    ]

    for instance in nitter_instances:
        try:
            url = f"{instance}/{handle}/feed"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()

            # 간단한 파싱 (실제로는 BeautifulSoup 사용)
            lines = resp.text.split("\n")
            for line in lines[:limit]:
                if "class=" in line and "tweet" in line.lower():
                    # 매우 단순화된 파싱
                    results.append({
                        "text": line[:200],
                        "date": datetime.now().isoformat(),
                        "url": f"{instance}/{handle}",
                        "source": "Trump X",
                        "grade": "C",  # C등급 정보원
                    })

            if results:
                return results
        except Exception as exc:
            last_exc = exc
            logger.debug("Nitter 인스턴스 %s 실패: %s", instance, exc)
            time.sleep(_RETRY_DELAY)

    logger.warning("Trump X 포스팅 수집 완전 실패: %s", last_exc)
    return []


def _parse_tweet_date(date_str: str) -> str | None:
    """트위터 날짜 파싱 (상대 시간 → ISO 형식)."""
    try:
        if "hour" in date_str or "hour" in date_str:
            hours = int(date_str.split()[0])
            dt = datetime.now() - timedelta(hours=hours)
            return dt.isoformat()
        elif "day" in date_str:
            days = int(date_str.split()[0])
            dt = datetime.now() - timedelta(days=days)
            return dt.isoformat()
        else:
            return datetime.fromisoformat(date_str).isoformat()
    except Exception:
        return datetime.now().isoformat()
