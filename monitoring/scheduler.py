"""monitoring/scheduler.py — APScheduler 자동화 파이프라인 (15-30분 간격)"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.event_processor import EventProcessor
from data_collection.source_manager import SourceManager
from database.db_manager import get_session

logger = logging.getLogger(__name__)


class FTTSScheduler:
    """FTTS 자동화 스케줄러."""

    def __init__(self, interval_minutes: int = 20):
        """
        Args:
            interval_minutes: 실행 간격 (기본값: 20분)
        """
        self.scheduler = BackgroundScheduler()
        self.interval = interval_minutes
        self.is_running = False

    def start(self) -> None:
        """스케줄러 시작."""
        if self.is_running:
            logger.warning("스케줄러가 이미 실행 중입니다")
            return

        # 주기적 작업 등록
        self.scheduler.add_job(
            self._run_pipeline,
            trigger=IntervalTrigger(minutes=self.interval),
            id="ftts_main_pipeline",
            name="FTTS 메인 파이프라인",
            replace_existing=True,
        )

        self.scheduler.start()
        self.is_running = True
        logger.info(
            "스케줄러 시작 — %d분 간격으로 자동 실행",
            self.interval,
        )

    def stop(self) -> None:
        """스케줄러 중지."""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("스케줄러 중지")

    def _run_pipeline(self) -> None:
        """메인 파이프라인 실행."""
        try:
            logger.info("=" * 60)
            logger.info("파이프라인 시작 — %s", datetime.now(timezone.utc).isoformat())
            logger.info("=" * 60)

            with get_session() as session:
                # 1️⃣ 모든 정보원에서 데이터 수집
                logger.info("[1/3] 데이터 수집 중...")
                source_mgr = SourceManager(session)
                collect_stats = source_mgr.collect_all()
                logger.info("수집 완료: %s", collect_stats)

                # 2️⃣ 이벤트 처리 및 인과관계 연결
                logger.info("[2/3] 이벤트 처리 중...")
                processor = EventProcessor(session)

                # 최근 이벤트 조회 및 처리
                from database.models import Event
                from sqlalchemy import desc

                recent_events = (
                    session.query(Event)
                    .order_by(desc(Event.collected_at))
                    .limit(10)
                    .all()
                )

                total_edges = 0
                for event in recent_events:
                    result = processor.process_event(
                        raw_text=event.content or "",
                        source_name=event.source.name if event.source else "",
                        source_id=event.source_id,
                        occurred_at=event.occurred_at,
                    )
                    total_edges += result["industry_edges"] + result["company_edges"]

                # 산업-회사 계층 자동 연결
                ind_edges = processor.apply_industry_hierarchy()
                total_edges += ind_edges

                logger.info("이벤트 처리 완료: %d개 엣지 생성", total_edges)

                # 3️⃣ 그래프 DB 동기화
                logger.info("[3/3] 그래프 DB 동기화 중...")
                sync_count = processor.sync_graph_to_db()
                logger.info("동기화 완료: %d개 엣지 저장", sync_count)

            logger.info("=" * 60)
            logger.info("파이프라인 완료 — %s", datetime.now(timezone.utc).isoformat())
            logger.info("=" * 60)

        except Exception as exc:
            logger.error("파이프라인 실행 중 오류: %s", exc, exc_info=True)


# ── 전역 스케줄러 인스턴스 ───────────────────────────────
_scheduler: FTTSScheduler | None = None


def get_scheduler(interval_minutes: int = 20) -> FTTSScheduler:
    """스케줄러 인스턴스 반환 (싱글톤)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = FTTSScheduler(interval_minutes=interval_minutes)
    return _scheduler


def start_scheduler(interval_minutes: int = 20) -> None:
    """스케줄러 시작."""
    scheduler = get_scheduler(interval_minutes=interval_minutes)
    scheduler.start()


def stop_scheduler() -> None:
    """스케줄러 중지."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    scheduler = get_scheduler(interval_minutes=20)
    scheduler.start()

    try:
        import time
        logger.info("스케줄러 실행 중... (Ctrl+C로 종료)")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("사용자 중단 요청")
        stop_scheduler()
