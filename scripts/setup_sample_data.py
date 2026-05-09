#!/usr/bin/env python3
"""샘플 데이터 생성 (테스트용).

모의투자 파이프라인을 테스트하기 위한 샘플 데이터:
- 기업 5개
- 각 기업 당 이벤트 8개
- 인과관계 엣지 30개
- 최근 주가 5개

사용:
    python -m scripts.setup_sample_data
    python -m scripts.setup_sample_data --clean  # 기존 데이터 삭제 후 재생성
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

from database.db_manager import get_session
from database.models import Company, CausalEdge, Event, Industry, Source, StockPrice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def setup_sample_data(clean: bool = False):
    """샘플 데이터 생성."""
    with get_session() as session:
        if clean:
            logger.info("🗑️  기존 데이터 삭제 중...")
            session.query(StockPrice).delete()
            session.query(Event).delete()
            session.query(CausalEdge).delete()
            session.query(Company).delete()
            session.query(Industry).delete()
            session.query(Source).delete()
            session.commit()
            logger.info("✅ 삭제 완료")

        logger.info("📋 샘플 데이터 생성 중...")

        # 1. Industry
        industries = {
            "반도체": Industry(code="SEM", name="반도체", sector="전자"),
            "에너지": Industry(code="ENR", name="에너지", sector="소재"),
            "금융": Industry(code="FIN", name="금융", sector="금융"),
        }
        for ind in industries.values():
            session.add(ind)
        session.flush()
        logger.info("✅ 산업 %d개 생성", len(industries))

        # 2. Company
        companies = {
            "삼성전자": Company(
                ticker="005930",
                name="삼성전자",
                market="KOSPI",
                industry_id=industries["반도체"].id,
                is_active=True,
            ),
            "SK하이닉스": Company(
                ticker="000660",
                name="SK하이닉스",
                market="KOSPI",
                industry_id=industries["반도체"].id,
                is_active=True,
            ),
            "LG에너지솔루션": Company(
                ticker="373220",
                name="LG에너지솔루션",
                market="KOSPI",
                industry_id=industries["에너지"].id,
                is_active=True,
            ),
            "삼성금융": Company(
                ticker="006400",
                name="삼성금융",
                market="KOSPI",
                industry_id=industries["금융"].id,
                is_active=True,
            ),
            "현대차": Company(
                ticker="005380",
                name="현대차",
                market="KOSPI",
                industry_id=None,
                is_active=True,
            ),
        }
        for co in companies.values():
            session.add(co)
        session.flush()
        logger.info("✅ 기업 %d개 생성", len(companies))

        # 3. Source
        sources = {
            "메르블로그": Source(
                name="메르블로그",
                url="https://mersblog.com",
                type="blog",
                grade="B",
                grade_weight=0.6,
                is_active=True,
            ),
            "연합뉴스": Source(
                name="연합뉴스",
                url="https://yonhapnews.com",
                type="news",
                grade="A",
                grade_weight=0.8,
                is_active=True,
            ),
            "이투데이": Source(
                name="이투데이",
                url="https://etoday.co.kr",
                type="news",
                grade="C",
                grade_weight=0.4,
                is_active=True,
            ),
        }
        for src in sources.values():
            session.add(src)
        session.flush()
        logger.info("✅ 소스 %d개 생성", len(sources))

        # 4. Event (기업별 8개씩)
        now = datetime.now(timezone.utc)
        event_templates = [
            ("AI 투자 확대", 0.7),
            ("실적 부진", -0.6),
            ("신제품 출시", 0.6),
            ("원자재 비용 상승", -0.5),
            ("정부 지원금 확정", 0.8),
            ("기술 혁신 발표", 0.7),
            ("공급망 차질", -0.7),
            ("시장 점유율 확대", 0.8),
        ]

        events_created = 0
        for company_name, company in companies.items():
            for idx, (title, sentiment) in enumerate(event_templates):
                event = Event(
                    title=f"{company_name} - {title}",
                    content=f"Sample event for testing: {title}",
                    source_id=list(sources.values())[idx % len(sources)].id,
                    company_id=company.id,
                    industry_id=company.industry_id,
                    event_type="earnings" if "실적" in title else "macro",
                    sentiment=sentiment,
                    raw_score=abs(sentiment),
                    occurred_at=now - timedelta(days=7 - (idx % 7)),
                )
                session.add(event)
                events_created += 1
        session.flush()
        logger.info("✅ 이벤트 %d개 생성", events_created)

        # 5. CausalEdge (인과관계)
        # 기본: event → industry → company
        edges = []
        event_id_offset = 1
        for company_idx, (company_name, company) in enumerate(companies.items()):
            # 이 회사의 이벤트들
            start_event_id = event_id_offset + (company_idx * len(event_templates))

            for i in range(len(event_templates)):
                event_id = start_event_id + i
                industry_id = company.industry_id or industries["반도체"].id

                # event → industry
                edges.append(
                    CausalEdge(
                        from_type="event",
                        from_id=event_id,
                        to_type="industry",
                        to_id=industry_id,
                        weight=0.6 + (i % 3) * 0.1,
                        confidence=0.7,
                        direction=1 if i % 2 == 0 else -1,
                    )
                )

                # industry → company
                edges.append(
                    CausalEdge(
                        from_type="industry",
                        from_id=industry_id,
                        to_type="company",
                        to_id=company.id,
                        weight=0.5 + (i % 3) * 0.15,
                        confidence=0.8,
                        direction=1 if i % 2 == 0 else -1,
                    )
                )

        for edge in edges:
            session.add(edge)
        session.flush()
        logger.info("✅ 인과관계 엣지 %d개 생성", len(edges))

        # 6. StockPrice (각 기업별 최근 5일)
        prices = {
            "삼성전자": 75000,
            "SK하이닉스": 128000,
            "LG에너지솔루션": 350000,
            "삼성금융": 55000,
            "현대차": 120000,
        }

        stock_prices_created = 0
        for company_name, base_price in prices.items():
            company = companies[company_name]
            for day_offset in range(5, 0, -1):
                price = base_price + (5 - day_offset) * 1000  # 매일 상승 추세
                sp = StockPrice(
                    company_id=company.id,
                    price_date=(now - timedelta(days=day_offset)).date(),
                    open=price - 500,
                    high=price + 1000,
                    low=price - 1000,
                    close=price,
                    volume=1000000 + (day_offset * 100000),
                    adj_close=price,
                )
                session.add(sp)
                stock_prices_created += 1
        session.flush()
        logger.info("✅ 주가 데이터 %d개 생성", stock_prices_created)

        # Commit
        session.commit()
        logger.info("\n" + "=" * 60)
        logger.info("✅ 샘플 데이터 생성 완료!")
        logger.info("=" * 60)
        logger.info("기업:        %d개", len(companies))
        logger.info("소스:        %d개", len(sources))
        logger.info("이벤트:      %d개", events_created)
        logger.info("인과관계:    %d개", len(edges))
        logger.info("주가:        %d개", stock_prices_created)
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="샘플 데이터 생성")
    parser.add_argument("--clean", action="store_true", help="기존 데이터 삭제 후 재생성")
    args = parser.parse_args()

    try:
        setup_sample_data(clean=args.clean)
    except Exception as e:
        logger.error("샘플 데이터 생성 실패: %s", e, exc_info=True)
        exit(1)


if __name__ == "__main__":
    main()
