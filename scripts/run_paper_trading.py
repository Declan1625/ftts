#!/usr/bin/env python3
"""모의투자 파이프라인 실행 스크립트.

사용:
    python scripts/run_paper_trading.py
    python scripts/run_paper_trading.py --companies 삼성전자 SK하이닉스
    python scripts/run_paper_trading.py --report
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from database.db_manager import get_session
from core.causal_graph import CausalGraph
from data.kis_api import create_kis_client_from_env, KISAuthError
from monitoring.accuracy_tracker import AccuracyTracker
from trading.paper_trading_pipeline import PaperTradingPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="FTTS 모의투자 파이프라인")
    parser.add_argument("--report", action="store_true", help="정확도 리포트만 출력")
    parser.add_argument("--days", type=int, help="리포트 기간 (일)")
    parser.add_argument(
        "--companies",
        nargs="+",
        help="대상 기업명 (미지정하면 활성 기업 모두)",
    )
    parser.add_argument("--test", action="store_true", help="테스트 모드 (KIS 연결 없음)")
    args = parser.parse_args()

    try:
        with get_session() as session:
            if args.report:
                # 정확도 리포트
                tracker = AccuracyTracker(session)
                report = tracker.report(days=args.days)
                print("\n".join(report.summary_lines()))
                return

            if args.test:
                logger.info("🧪 테스트 모드: KIS API 없이 실행")
                run_test_pipeline(session)
                return

            # 정상 실행: KIS API 연결
            logger.info("🚀 모의투자 파이프라인 시작...")
            try:
                kis = create_kis_client_from_env(mock=True)
            except ValueError as e:
                logger.error("KIS 설정 오류: %s", e)
                logger.info("테스트 모드로 실행하려면 --test 플래그 사용")
                sys.exit(1)
            except KISAuthError as e:
                logger.error("KIS 인증 실패: %s", e)
                logger.info("테스트 모드로 실행하려면 --test 플래그 사용")
                sys.exit(1)

            # 그래프 초기화 (DB의 인과관계 엣지는 별도 로드)
            graph = CausalGraph()

            # 파이프라인 실행
            pipeline = PaperTradingPipeline(kis, graph, session)
            result = pipeline.run_daily()

            # 결과 출력
            print("\n" + "=" * 60)
            print("📈 모의투자 실행 결과")
            print("=" * 60)
            print(f"처리 기업:      {result['companies_processed']}")
            print(f"생성 신호:      {result['signals_generated']}")
            print(f"체결 매매:      {result['trades_executed']}")
            print(f"평가 결정:      {result['outcomes_evaluated']}")
            if result["errors"]:
                print(f"\n⚠️  에러 ({len(result['errors'])}개):")
                for err in result["errors"]:
                    print(f"  - {err}")
            print("=" * 60)

    except Exception as e:
        logger.error("파이프라인 실패: %s", e, exc_info=True)
        sys.exit(1)


def run_test_pipeline(session):
    """테스트 모드: 샘플 데이터로 파이프라인 시뮬레이션."""
    from database.models import Company, Event, Source

    logger.info("테스트 파이프라인 시작...")

    # 샘플 기업 및 이벤트 확인
    companies = session.query(Company).filter_by(is_active=True).limit(3).all()
    logger.info("샘플 기업 %d개", len(companies))

    for company in companies:
        events = (
            session.query(Event)
            .filter_by(company_id=company.id)
            .order_by(Event.occurred_at.desc())
            .limit(5)
            .all()
        )
        logger.info(
            "  - %s (%s): 최근 이벤트 %d개",
            company.name,
            company.ticker,
            len(events),
        )

    # 그래프 초기화
    graph = CausalGraph()
    logger.info("✅ 그래프 초기화 완료")

    # 정확도 리포트
    tracker = AccuracyTracker(session)
    report = tracker.report()
    logger.info("📊 현재 정확도: %.1f%% (%d/%d)", report.accuracy * 100, report.correct, report.total_evaluated)


if __name__ == "__main__":
    main()
