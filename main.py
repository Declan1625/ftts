"""main.py — FTTS 메인 진입점"""

import argparse
import logging
import sys

from monitoring.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main() -> int:
    """메인 함수."""
    parser = argparse.ArgumentParser(
        description="자가 진단형 주식 자동매매 시스템 (FTTS)",
    )
    parser.add_argument(
        "command",
        choices=["init-db", "scheduler", "dashboard", "server"],
        help="실행할 명령어",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=20,
        help="스케줄러 간격 (분, 기본값: 20)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="API 서버 호스트 (기본값: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API 서버 포트 (기본값: 8000)",
    )

    args = parser.parse_args()

    if args.command == "init-db":
        logger.info("DB 초기화 중...")
        from database.db_manager import init_db
        init_db()
        logger.info("✅ DB 초기화 완료")
        return 0

    elif args.command == "scheduler":
        logger.info("스케줄러 시작 (간격: %d분)", args.interval)
        start_scheduler(interval_minutes=args.interval)
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("스케줄러 중지")
            stop_scheduler()
        return 0

    elif args.command == "dashboard":
        logger.info("대시보드 시작 (localhost:8501)")
        import subprocess
        subprocess.run(
            ["streamlit", "run", "monitoring/dashboard.py", "--logger.level=info"],
        )
        return 0

    elif args.command == "server":
        logger.info("API 서버 시작 (http://%s:%d)", args.host, args.port)
        import uvicorn
        uvicorn.run(
            "api.server:app",
            host=args.host,
            port=args.port,
            reload=False,
            log_level="info",
        )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
