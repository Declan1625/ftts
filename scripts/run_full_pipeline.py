"""scripts/run_full_pipeline.py — 메르 블로그 전체 크롤링 → 분석 → DB 주입 → 그래프 연결"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

JSONL_PATH = Path(__file__).parent.parent / "data/raw/mer_analysis.jsonl"
MAX_PAGES = 100
SLEEP_BETWEEN = 1.0  # 포스트 간 딜레이(초)


def load_seen_post_nos() -> set[str]:
    seen = set()
    if JSONL_PATH.exists():
        with open(JSONL_PATH) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["post_no"])
                except Exception:
                    pass
    return seen


def step1_crawl_and_analyze():
    """블로그 포스트 수집 + Claude 분석 → JSONL 저장."""
    from data_collection.blog_scraper import _get_all_post_nos, _fetch_post
    from nlp.mer_analyzer import analyze_mer_blog

    seen = load_seen_post_nos()
    logger.info("기존 분석 포스트: %d개", len(seen))

    all_nos = _get_all_post_nos(max_pages=MAX_PAGES)
    new_nos = [n for n in all_nos if n not in seen]
    logger.info("전체 포스트: %d개 / 신규: %d개", len(all_nos), len(new_nos))

    if not new_nos:
        logger.info("분석할 신규 포스트 없음")
        return 0

    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = 0

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        for i, post_no in enumerate(new_nos, 1):
            try:
                post = _fetch_post(post_no)
                if not post:
                    logger.warning("[%d/%d] 포스트 수집 실패: %s", i, len(new_nos), post_no)
                    continue

                analysis = analyze_mer_blog(
                    title=post.title,
                    content=post.content,
                    source_name="메르 블로그",
                )

                record = {
                    "post_no": post_no,
                    "title": post.title,
                    "published_at": post.published_at.isoformat(),
                    "url": post.url,
                    "is_investment_related": analysis.is_investment_related,
                    "events": analysis.events,
                    "primary_source": analysis.primary_source,
                    "reference_sources": analysis.reference_sources,
                    "source_correlations": analysis.source_correlations,
                    "affected_industries": analysis.affected_industries,
                    "affected_companies": analysis.affected_companies,
                    "causal_chain": analysis.causal_chain,
                    "confidence": analysis.confidence,
                    "summary": analysis.summary,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                saved += 1

                inv = "✅" if analysis.is_investment_related else "⬜"
                logger.info(
                    "[%d/%d] %s %s | 사건:%d개 산업:%d개 기업:%d개",
                    i, len(new_nos), inv, post.title[:40],
                    len(analysis.events), len(analysis.affected_industries),
                    len(analysis.affected_companies),
                )

                time.sleep(SLEEP_BETWEEN)

            except KeyboardInterrupt:
                logger.info("중단 요청 — 저장된 포스트: %d개", saved)
                break
            except Exception as e:
                logger.error("[%d/%d] 오류 post_no=%s: %s", i, len(new_nos), post_no, e)
                continue

    logger.info("STEP1 완료: %d개 저장 → %s", saved, JSONL_PATH)
    return saved


def step2_ingest():
    """JSONL → DB + CausalGraph 주입."""
    from core.causal_graph import CausalGraph
    from core.mer_ingest import ingest_jsonl
    from database.db_manager import get_session

    graph = CausalGraph()
    with get_session() as session:
        results = ingest_jsonl(str(JSONL_PATH), session, graph)

    logger.info("STEP2 완료: %d건 주입 | 노드:%d 엣지:%d", len(results), graph.node_count, graph.edge_count)
    return graph


def step3_link_graph():
    """industry→company 엣지 자동 연결 + DB 동기화."""
    from core.causal_graph import CausalGraph
    from core.event_processor import EventProcessor
    from database.db_manager import get_session
    from database.models import CausalEdge

    with get_session() as session:
        # DB의 모든 엣지로 그래프 재구성
        graph = CausalGraph()
        for e in session.query(CausalEdge).all():
            graph.add_edge(
                (e.from_type, e.from_id), (e.to_type, e.to_id),
                weight=float(e.weight), direction=e.direction, confidence=float(e.confidence),
            )

        processor = EventProcessor(session)
        processor.graph = graph

        n_edges = processor.apply_industry_hierarchy()
        logger.info("industry→company 연결: %d개 엣지 생성", n_edges)

        synced = processor.sync_graph_to_db()
        logger.info("STEP3 완료: %d개 엣지 DB 동기화", synced)

        return graph


def step4_test_signals(graph):
    """신호 산출 테스트."""
    from core.weight_engine import WeightEngine, EventInput
    from database.db_manager import get_session
    from database.models import Company, Event
    from datetime import datetime, timezone
    from config import settings

    with get_session() as session:
        engine = WeightEngine(graph)
        real_events = session.query(Event).filter(
            ~Event.content.like("%Sample event%")
        ).all()

        event_inputs = []
        for ev in real_events:
            grade = ev.source.grade if ev.source else "C"
            ei = EventInput(
                event_node=("event", ev.id),
                sentiment=0.5,
                source_grade_weight=settings.GRADE_WEIGHTS.get(grade, 0.5),
                occurred_at=ev.occurred_at or datetime.now(timezone.utc),
            )
            event_inputs.append(ei)

        companies = session.query(Company).filter(Company.is_active == True).all()
        buy, sell, hold = [], [], []
        for co in companies:
            d = engine.decide(("company", co.id), event_inputs)
            row = (co.name, co.ticker, d.signal, round(d.event_score, 4), round(d.confidence, 4))
            if d.signal == "BUY":
                buy.append(row)
            elif d.signal == "SELL":
                sell.append(row)
            else:
                hold.append(row)

        logger.info("=== 신호 산출 결과 ===")
        logger.info("BUY=%d SELL=%d HOLD=%d", len(buy), len(sell), len(hold))

        for r in sorted(buy, key=lambda x: -x[3])[:10]:
            logger.info("🟢 BUY  %s (%s) score=%.4f conf=%.2f", r[0], r[1], r[3], r[4])
        for r in sorted(sell, key=lambda x: x[3])[:10]:
            logger.info("🔴 SELL %s (%s) score=%.4f conf=%.2f", r[0], r[1], r[3], r[4])


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("FTTS 전체 파이프라인 시작")
    logger.info("=" * 60)

    # STEP1: 크롤링 + 분석
    saved = step1_crawl_and_analyze()

    # STEP2: DB 주입
    graph = step2_ingest()

    # STEP3: 그래프 연결
    graph = step3_link_graph()

    # STEP4: 신호 테스트
    step4_test_signals(graph)

    logger.info("=" * 60)
    logger.info("전체 파이프라인 완료")
    logger.info("=" * 60)
