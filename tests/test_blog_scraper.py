"""tests/test_blog_scraper.py"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from data_collection.blog_scraper import (
    BlogPost,
    _parse_date,
    fetch_recent_posts,
    fetch_posts_since,
)


class TestParseDate:
    def test_parses_naver_format(self):
        dt = _parse_date("2024. 03. 15.")
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.day == 15

    def test_parses_iso_format(self):
        dt = _parse_date("2024-01-10")
        assert dt.year == 2024

    def test_returns_now_on_empty(self):
        dt = _parse_date("")
        assert isinstance(dt, datetime)

    def test_returns_now_on_invalid(self):
        dt = _parse_date("잘못된 날짜")
        assert isinstance(dt, datetime)


class TestFetchRecentPosts:
    def _make_post(self, post_no="12345", days_ago=0):
        from datetime import timedelta
        return BlogPost(
            blog_id="ranto28",
            post_no=post_no,
            title=f"테스트 포스트 {post_no}",
            content="내용",
            published_at=datetime.utcnow() - timedelta(days=days_ago),
            url=f"https://blog.naver.com/ranto28/{post_no}",
        )

    @patch("data_collection.blog_scraper._fetch_post")
    @patch("data_collection.blog_scraper._get_post_list")
    @patch("data_collection.blog_scraper.time.sleep")
    def test_returns_posts(self, mock_sleep, mock_list, mock_fetch):
        mock_list.return_value = ["111", "222"]
        mock_fetch.side_effect = [self._make_post("111"), self._make_post("222")]

        result = fetch_recent_posts(count=2)

        assert len(result) == 2
        assert result[0].post_no == "111"

    @patch("data_collection.blog_scraper._fetch_post")
    @patch("data_collection.blog_scraper._get_post_list")
    @patch("data_collection.blog_scraper.time.sleep")
    def test_skips_failed_posts(self, mock_sleep, mock_list, mock_fetch):
        mock_list.return_value = ["111", "222"]
        mock_fetch.side_effect = [Exception("파싱 오류"), self._make_post("222")]

        result = fetch_recent_posts(count=2)
        assert len(result) == 1
        assert result[0].post_no == "222"


class TestFetchPostsSince:
    @patch("data_collection.blog_scraper._fetch_post")
    @patch("data_collection.blog_scraper._get_post_list")
    @patch("data_collection.blog_scraper.time.sleep")
    def test_filters_by_date(self, mock_sleep, mock_list, mock_fetch):
        from datetime import timedelta
        now = datetime.utcnow()

        post_new = BlogPost("ranto28", "200", "새글", "", now - timedelta(days=1), "")
        post_old = BlogPost("ranto28", "100", "옛글", "", now - timedelta(days=10), "")

        mock_list.return_value = ["200", "100"]
        mock_fetch.side_effect = [post_new, post_old]

        result = fetch_posts_since(since=now - timedelta(days=3))
        assert len(result) == 1
        assert result[0].post_no == "200"
