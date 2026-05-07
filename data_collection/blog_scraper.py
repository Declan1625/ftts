"""data_collection/blog_scraper.py — 메르 네이버 블로그 스크래퍼"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BLOG_ID = "ranto28"
_POST_LIST_URL = "https://blog.naver.com/PostList.naver"
_POST_VIEW_URL = "https://blog.naver.com/PostView.naver"
_MAX_RETRIES = 3
_RETRY_DELAY = 2
_REQUEST_INTERVAL = 1.0  # 서버 부하 방지

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://blog.naver.com/",
}


@dataclass
class BlogPost:
    blog_id: str
    post_no: str
    title: str
    content: str
    published_at: datetime
    url: str


def fetch_recent_posts(count: int = 10) -> list[BlogPost]:
    """메르 블로그 최근 포스트 수집."""
    post_nos = _get_post_list(count)
    posts: list[BlogPost] = []
    for no in post_nos:
        try:
            post = _fetch_post(no)
            if post:
                posts.append(post)
            time.sleep(_REQUEST_INTERVAL)
        except Exception as exc:
            logger.error("포스트 수집 실패 no=%s: %s", no, exc)
    return posts


def fetch_posts_since(since: datetime, max_posts: int = 100) -> list[BlogPost]:
    """특정 날짜 이후 포스트만 수집."""
    post_nos = _get_post_list(max_posts)
    posts: list[BlogPost] = []
    for no in post_nos:
        try:
            post = _fetch_post(no)
            if post is None:
                continue
            if post.published_at < since:
                break
            posts.append(post)
            time.sleep(_REQUEST_INTERVAL)
        except Exception as exc:
            logger.error("포스트 수집 실패 no=%s: %s", no, exc)
    return posts


def _get_post_list(count: int) -> list[str]:
    """포스트 번호 목록 반환."""
    params = {
        "blogId": _BLOG_ID,
        "currentPage": 1,
        "viewdate": "",
        "categoryNo": "",
        "countPerPage": count,
    }
    resp = _get_with_retry(_POST_LIST_URL, params=params)
    soup = BeautifulSoup(resp.text, "html.parser")

    post_nos: list[str] = []
    for a in soup.select("a[href*='logNo=']"):
        href = a.get("href", "")
        for part in href.split("&"):
            if part.startswith("logNo="):
                post_nos.append(part.split("=")[1])
                break

    return list(dict.fromkeys(post_nos))[:count]


def _fetch_post(post_no: str) -> BlogPost | None:
    params = {"blogId": _BLOG_ID, "logNo": post_no}
    resp = _get_with_retry(_POST_VIEW_URL, params=params)
    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.select_one(".se-title-text") or soup.select_one(".htitle")
    content_tag = soup.select_one(".se-main-container") or soup.select_one("#postViewArea")
    date_tag = soup.select_one(".se_publishDate") or soup.select_one(".date")

    if not title_tag or not content_tag:
        logger.warning("파싱 실패 — post_no=%s", post_no)
        return None

    title = title_tag.get_text(strip=True)
    content = content_tag.get_text(separator="\n", strip=True)
    published_at = _parse_date(date_tag.get_text(strip=True) if date_tag else "")
    url = f"https://blog.naver.com/{_BLOG_ID}/{post_no}"

    return BlogPost(
        blog_id=_BLOG_ID,
        post_no=post_no,
        title=title,
        content=content,
        published_at=published_at,
        url=url,
    )


def _parse_date(text: str) -> datetime:
    for fmt in ("%Y. %m. %d.", "%Y.%m.%d.", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _get_with_retry(url: str, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("HTTP 재시도 %d/%d — %s: %s", attempt, _MAX_RETRIES, url, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
    raise RuntimeError(f"요청 실패 ({_MAX_RETRIES}회): {url}") from last_exc
