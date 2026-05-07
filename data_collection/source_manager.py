"""data_collection/source_manager.py — 모든 정보원 통합 관리"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from data_collection import (
    blog_scraper,
    dart_crawler,
    fed_crawler,
    news_crawler,
    sec_crawler,
    trump_scraper,
)
from database.models import Event, Source

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SourceManager:
    """모든 정보원에서 데이터 수집 및 DB 저장."""

    def __init__(self, session: Session):
        self.session = session
        self._ensure_sources()
        self._source_cache: dict[str, int] = {}

    def _get_source_id(self, name: str) -> int:
        """정보원명 → ID 매핑 (캐시)."""
        if name not in self._source_cache:
            source = self.session.query(Source).filter_by(name=name).first()
            if source:
                self._source_cache[name] = source.id
            else:
                raise ValueError(f"Source not found: {name}")
        return self._source_cache[name]

    def _update_source_stats(self, source_id: int, event_count: int) -> None:
        """Source 통계 업데이트 (이벤트 수집 후)."""
        try:
            source = self.session.query(Source).filter_by(id=source_id).first()
            if source:
                # total_predictions 증가
                source.total_predictions += event_count
                self.session.commit()
                logger.info("Source %d 통계 업데이트: +%d predictions", source_id, event_count)
        except Exception as exc:
            logger.error("Source 통계 업데이트 실패: %s", exc)

    def _ensure_sources(self) -> None:
        """정보원 마스터 데이터 초기화."""
        source_specs = [
            {"name": "메르 블로그", "type": "blog", "grade": "A"},
            {"name": "뉴스 크롤러", "type": "news", "grade": "B"},
            {"name": "DART 공시", "type": "report", "grade": "A"},
            {"name": "Fed 발표", "type": "official", "grade": "S"},
            {"name": "SEC EDGAR", "type": "report", "grade": "A"},
            {"name": "Trump X", "type": "sns", "grade": "C"},
        ]

        for spec in source_specs:
            existing = self.session.query(Source).filter_by(name=spec["name"]).first()
            if not existing:
                source = Source(
                    name=spec["name"],
                    type=spec["type"],
                    grade=spec["grade"],
                    is_active=True,
                )
                self.session.add(source)
        self.session.commit()

    def collect_all(self) -> dict[str, int]:
        """모든 정보원에서 수집."""
        stats = {}

        stats["blog"] = self._collect_blog()
        stats["news"] = self._collect_news()
        stats["dart"] = self._collect_dart()
        stats["fed"] = self._collect_fed()
        stats["sec"] = self._collect_sec()
        stats["trump"] = self._collect_trump()

        logger.info("수집 완료: %s", stats)
        return stats

    def _collect_blog(self) -> int:
        """메르 블로그 포스팅 수집."""
        try:
            posts = blog_scraper.fetch_recent_posts(days_back=7)
            source_id = self._get_source_id("메르 블로그")
            count = 0
            for post in posts:
                event = Event(
                    source_id=source_id,
                    title=post.get("title", ""),
                    content=post.get("content", "")[:2000],
                    event_type="macro",
                    occurred_at=datetime.now(),
                    collected_at=datetime.now(),
                )
                self.session.add(event)
                count += 1

            self.session.commit()
            # Source 통계 업데이트
            self._update_source_stats(source_id, count)
            return count
        except Exception as exc:
            logger.error("블로그 수집 실패: %s", exc)
            return 0

    def _collect_news(self) -> int:
        """뉴스 크롤러 수집."""
        try:
            articles = news_crawler.fetch_news(days_back=1)
            source_id = self._get_source_id("뉴스 크롤러")
            count = 0
            for article in articles:
                event = Event(
                    source_id=source_id,
                    title=article.get("title", ""),
                    content=article.get("content", "")[:2000],
                    event_type="other",
                    occurred_at=datetime.now(),
                    collected_at=datetime.now(),
                )
                self.session.add(event)
                count += 1
            self.session.commit()
            self._update_source_stats(source_id, count)
            return count
        except Exception as exc:
            logger.error("뉴스 수집 실패: %s", exc)
            return 0

    def _collect_dart(self) -> int:
        """DART 공시 수집."""
        try:
            disclosures = dart_crawler.fetch_recent_disclosures(days_back=7)
            source_id = self._get_source_id("DART 공시")
            count = 0
            for disclosure in disclosures:
                event = Event(
                    source_id=source_id,
                    title=disclosure.get("report_nm", ""),
                    content=disclosure.get("title", "")[:2000],
                    event_type="earnings",
                    occurred_at=datetime.now(),
                    collected_at=datetime.now(),
                )
                self.session.add(event)
                count += 1
            self.session.commit()
            self._update_source_stats(source_id, count)
            return count
        except Exception as exc:
            logger.error("DART 수집 실패: %s", exc)
            return 0

    def _collect_fed(self) -> int:
        """Fed 발표 수집."""
        try:
            speeches = fed_crawler.fetch_recent_speeches(days_back=30)
            minutes = fed_crawler.fetch_fomc_minutes()
            items = speeches + minutes
            source_id = self._get_source_id("Fed 발표")
            count = 0
            for item in items:
                event = Event(
                    source_id=source_id,
                    title=item.get("title", ""),
                    content=item.get("summary", "")[:2000],
                    event_type="policy",
                    occurred_at=datetime.now(),
                    collected_at=datetime.now(),
                )
                self.session.add(event)
                count += 1
            self.session.commit()
            self._update_source_stats(source_id, count)
            return count
        except Exception as exc:
            logger.error("Fed 수집 실패: %s", exc)
            return 0

    def _collect_sec(self) -> int:
        """SEC 공시 수집."""
        try:
            tickers = ["AAPL", "MSFT", "TSLA", "NVDA", "META"]
            source_id = self._get_source_id("SEC EDGAR")
            count = 0
            for ticker in tickers:
                filings = sec_crawler.fetch_company_filings(ticker, days_back=30)
                for filing in filings:
                    event = Event(
                        source_id=source_id,
                        title=f"{ticker} {filing.get('form_type', '')}",
                        content=f"{filing.get('filing_date', '')} {filing.get('accession_number', '')}"[:2000],
                        event_type="earnings",
                        occurred_at=datetime.now(),
                        collected_at=datetime.now(),
                    )
                    self.session.add(event)
                    count += 1
            self.session.commit()
            self._update_source_stats(source_id, count)
            return count
        except Exception as exc:
            logger.error("SEC 수집 실패: %s", exc)
            return 0

    def _collect_trump(self) -> int:
        """Trump X 포스팅 수집."""
        try:
            posts = trump_scraper.fetch_trump_posts(days_back=7)
            source_id = self._get_source_id("Trump X")
            count = 0
            for post in posts:
                event = Event(
                    source_id=source_id,
                    title="Trump X Post",
                    content=post.get("text", "")[:2000],
                    event_type="geopolitical",
                    occurred_at=datetime.now(),
                    collected_at=datetime.now(),
                )
                self.session.add(event)
                count += 1
            self.session.commit()
            self._update_source_stats(source_id, count)
            return count
        except Exception as exc:
            logger.error("Trump X 수집 실패: %s", exc)
            return 0
