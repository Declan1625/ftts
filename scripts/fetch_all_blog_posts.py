"""scripts/fetch_all_blog_posts.py — 메르 블로그 전체 글 수집 (최초 1회)"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_collection import blog_scraper
from database.db_manager import get_session
from database.models import Event, Source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_and_save_all_posts(max_pages: int = 50) -> int:
    """메르 블로그 전체 글 수집 후 DB 저장."""
    try:
        with get_session() as session:
            logger.info("=" * 60)
            logger.info("메르 블로그 전체 글 수집 시작 (최대 %d페이지)", max_pages)
            logger.info("=" * 60)

            # 1. 메르 블로그 정보원 확인
            source = session.query(Source).filter_by(name="메르 블로그").first()
            if not source:
                logger.error("메르 블로그 정보원이 없습니다. DB를 먼저 초기화하세요.")
                return 0

            logger.info("정보원: %s (ID=%d, 등급=%s)", source.name, source.id, source.grade)

            # 2. 전체 포스트 번호 수집
            logger.info("포스트 목록 수집 중...")
            post_nos = blog_scraper._get_all_post_nos(max_pages)
            logger.info("수집된 포스트 번호: %d개", len(post_nos))

            if not post_nos:
                logger.warning("수집된 포스트가 없습니다.")
                return 0

            # 3. 각 포스트 상세 정보 수집 및 저장
            saved_count = 0
            skipped_count = 0
            error_count = 0

            for i, post_no in enumerate(post_nos, 1):
                try:
                    post = blog_scraper._fetch_post(post_no)
                    if not post:
                        logger.warning("[%d/%d] 파싱 실패: %s", i, len(post_nos), post_no)
                        error_count += 1
                        continue

                    # 중복 체크 (title + source_id)
                    existing = (
                        session.query(Event)
                        .filter_by(source_id=source.id, title=post.title)
                        .first()
                    )
                    if existing:
                        logger.debug("[%d/%d] 이미 저장됨: %s", i, len(post_nos), post.title[:30])
                        skipped_count += 1
                        continue

                    # 새 이벤트 저장
                    event = Event(
                        source_id=source.id,
                        title=post.title,
                        content=post.content[:2000],
                        event_type="macro",
                        occurred_at=post.published_at,
                        collected_at=datetime.now(),
                    )
                    session.add(event)
                    saved_count += 1

                    if i % 10 == 0:
                        session.commit()
                        logger.info(
                            "[%d/%d] 진행 중... (저장됨: %d, 중복: %d, 오류: %d)",
                            i,
                            len(post_nos),
                            saved_count,
                            skipped_count,
                            error_count,
                        )

                except Exception as exc:
                    logger.error("[%d/%d] 처리 실패: %s: %s", i, len(post_nos), post_no, exc)
                    error_count += 1

            # 최종 커밋
            session.commit()

            logger.info("=" * 60)
            logger.info("✅ 수집 완료")
            logger.info("  저장됨: %d개", saved_count)
            logger.info("  중복: %d개", skipped_count)
            logger.info("  오류: %d개", error_count)
            logger.info("=" * 60)

            # Source 통계 업데이트
            source.total_predictions += saved_count
            session.commit()

            return saved_count

    except Exception as exc:
        logger.error("❌ 전체 수집 실패: %s", exc, exc_info=True)
        return 0


if __name__ == "__main__":
    count = fetch_and_save_all_posts(max_pages=50)
    sys.exit(0 if count >= 0 else 1)
