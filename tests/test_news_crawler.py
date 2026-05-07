"""tests/test_news_crawler.py"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from data_collection.news_crawler import (
    NewsArticle,
    _parse_rss_date,
    crawl_feed,
    crawl_since,
)


class TestParseRssDate:
    def test_parses_rfc2822(self):
        dt = _parse_rss_date("Thu, 01 Feb 2024 09:00:00 +0900")
        assert dt.year == 2024
        assert dt.month == 2

    def test_returns_now_on_empty(self):
        dt = _parse_rss_date("")
        assert isinstance(dt, datetime)

    def test_returns_now_on_invalid(self):
        dt = _parse_rss_date("not-a-date")
        assert isinstance(dt, datetime)


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>금리 인하 가능성 높아져</title>
      <link>https://example.com/news/1</link>
      <description>한은, 기준금리 인하 검토 중</description>
      <pubDate>Thu, 01 Feb 2024 09:00:00 +0900</pubDate>
    </item>
    <item>
      <title>반도체 수출 증가</title>
      <link>https://example.com/news/2</link>
      <description>1월 반도체 수출 30% 증가</description>
      <pubDate>Thu, 01 Feb 2024 10:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>"""


class TestCrawlFeed:
    @patch("data_collection.news_crawler._get_with_retry")
    def test_returns_articles(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_SAMPLE.encode()
        mock_get.return_value = mock_resp

        result = crawl_feed("테스트", "https://example.com/rss")

        assert len(result) == 2
        assert result[0].title == "금리 인하 가능성 높아져"
        assert result[0].source_name == "테스트"

    @patch("data_collection.news_crawler._get_with_retry")
    def test_respects_max_items(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_SAMPLE.encode()
        mock_get.return_value = mock_resp

        result = crawl_feed("테스트", "https://example.com/rss", max_items=1)
        assert len(result) == 1

    @patch("data_collection.news_crawler._get_with_retry")
    def test_raises_on_request_failure(self, mock_get):
        mock_get.side_effect = RuntimeError("요청 실패 (3회)")
        with pytest.raises(RuntimeError):
            crawl_feed("테스트", "https://example.com/rss")


class TestCrawlSince:
    @patch("data_collection.news_crawler.crawl_all")
    def test_filters_old_articles(self, mock_crawl):
        now = datetime.utcnow()
        mock_crawl.return_value = [
            NewsArticle("A", "새기사", "url1", "", now - timedelta(hours=1)),
            NewsArticle("A", "옛기사", "url2", "", now - timedelta(days=2)),
        ]
        result = crawl_since(since=now - timedelta(hours=6))
        assert len(result) == 1
        assert result[0].title == "새기사"
