"""모의투자 파이프라인 (Paper Trading Pipeline).

흐름:
1. 활성 기업 목록 조회
2. 각 기업의 최근 이벤트 → weight_engine 신호 생성
3. 신호 실행 (paper_trader)
4. outcomes 테이블에 현재 가격 기록
5. N일 뒤 자동 평가

주요 진입점:
- PaperTradingPipeline.run_daily() — 매일 실행
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from core.causal_graph import CausalGraph, EdgeData
from core.weight_engine import EventInput, WeightEngine
from data.price_fetcher import PriceFetcher
from data.kis_api import KISClient
from database.db_manager import get_session
from database.models import CausalEdge, Company, Decision, Event, Outcome, StockPrice
from trading.paper_trader import PaperTrader

logger = logging.getLogger(__name__)


class PaperTradingPipeline:
    """모의투자 전체 파이프라인."""

    OUTCOME_EVAL_DAYS = 5  # 5일 뒤 자동 평가

    def __init__(
        self,
        kis_client: KISClient,
        causal_graph: CausalGraph,
        session: Session,
    ) -> None:
        self.kis = kis_client
        self.graph = causal_graph
        self._s = session
        self.price_fetcher = PriceFetcher(kis_client, session)
        self.weight_engine = WeightEngine(causal_graph)
        self.paper_trader = PaperTrader(session)

        # DB의 인과관계 엣지를 그래프로 로드
        self._load_causal_edges()

    def run_daily(self, *, now: Optional[datetime] = None) -> dict:
        """
        일일 모의투자 실행.

        Returns:
            {
                "companies_processed": int,
                "signals_generated": int,
                "trades_executed": int,
                "outcomes_evaluated": int,
                "errors": list[str],
            }
        """
        now = now or datetime.now(timezone.utc)
        logger.info("=" * 60)
        logger.info("📊 모의투자 파이프라인 시작 (%s)", now.strftime("%Y-%m-%d %H:%M"))
        logger.info("=" * 60)

        result = {
            "companies_processed": 0,
            "signals_generated": 0,
            "trades_executed": 0,
            "outcomes_evaluated": 0,
            "errors": [],
        }

        try:
            # 1. 주가 수집
            logger.info("1️⃣ 실시간 주가 수집 중...")
            self.price_fetcher.fetch_and_save()

            # 2. 활성 기업 조회
            companies = self._get_active_companies()
            result["companies_processed"] = len(companies)
            logger.info("   %d개 기업 처리 대상", len(companies))

            # 3. 각 기업별 신호 생성 및 실행
            logger.info("2️⃣ 신호 생성 및 실행 중...")
            for company in companies:
                try:
                    self._process_company(company, now)
                    result["signals_generated"] += 1
                except Exception as e:
                    logger.error("기업 처리 실패 (id=%d, name=%s): %s", company.id, company.name, e)
                    result["errors"].append(f"{company.name}: {e}")

            # 4. 기존 결정 평가 (N일 뒤)
            logger.info("3️⃣ 기존 결정 평가 중...")
            eval_count = self._evaluate_old_outcomes(now)
            result["outcomes_evaluated"] = eval_count
            logger.info("   %d개 결정 평가 완료", eval_count)

            # DB 커밋
            self._s.commit()
            logger.info("=" * 60)
            logger.info("✅ 파이프라인 완료")
            logger.info("=" * 60)

        except Exception as e:
            logger.error("파이프라인 실패: %s", e)
            self._s.rollback()
            result["errors"].append(f"전체 파이프라인: {e}")

        return result

    def _process_company(self, company: Company, now: datetime) -> None:
        """
        특정 기업에 대한 신호 생성 및 실행.

        1. 최근 이벤트 조회
        2. weight_engine 신호 결정
        3. paper_trader 실행
        4. decision + outcome 저장
        """
        # 최신 주가
        current_price = self.price_fetcher.get_latest_price(company.id)
        if current_price is None or current_price <= 0:
            logger.warning("주가 없음 (company_id=%d)", company.id)
            return

        # 최근 이벤트 조회 (최근 7일)
        since = now - timedelta(days=7)
        events = (
            self._s.query(Event)
            .filter(
                Event.company_id == company.id,
                Event.occurred_at >= since,
            )
            .all()
        )

        if not events:
            logger.debug("최근 이벤트 없음 (company_id=%d)", company.id)
            return

        # EventInput 생성
        event_inputs = []
        for event in events:
            if event.sentiment is None:
                continue
            source = event.source
            grade_weight = source.grade_weight if source else 0.4
            event_inputs.append(
                EventInput(
                    event_node=("event", event.id),
                    sentiment=float(event.sentiment),
                    source_grade_weight=grade_weight,
                    occurred_at=event.occurred_at,
                )
            )

        if not event_inputs:
            logger.debug("처리 가능한 이벤트 없음 (company_id=%d)", company.id)
            return

        # 신호 결정
        company_node = ("company", company.id)
        decision_result = self.weight_engine.decide(
            company_node,
            event_inputs,
            now=now,
        )

        # 신호 저장
        decision = Decision(
            company_id=company.id,
            signal=decision_result.signal,
            event_score=decision_result.event_score,
            predicted_weight=decision_result.predicted_weight,
            confidence=decision_result.confidence,
            logic_snapshot=decision_result.snapshot,
            decided_at=now,
        )
        self._s.add(decision)
        self._s.flush()

        logger.info(
            "신호 생성: %s | %s | score=%.3f | conf=%.2f | events=%d",
            company.ticker,
            decision_result.signal,
            decision_result.event_score,
            decision_result.confidence,
            len(event_inputs),
        )

        # 신호 실행 (paper_trader)
        try:
            trade = self.paper_trader.execute(
                decision_result,
                current_price,
                company_db_id=company.id,
                decision_db_id=decision.id,
                now=now,
            )

            if trade:
                logger.info(
                    "매매 체결: %s | %s | qty=%d | 가격=%.0f",
                    company.ticker,
                    trade.side,
                    trade.quantity,
                    trade.price,
                )

                # Outcome 생성 (즉시 기록 → N일 뒤 평가)
                outcome = Outcome(
                    decision_id=decision.id,
                    company_id=company.id,
                    price_at_decision=current_price,
                    evaluated_at=now + timedelta(days=self.OUTCOME_EVAL_DAYS),
                )
                self._s.add(outcome)
                logger.debug("Outcome 대기 중 (company_id=%d, eval_date=%s)", company.id, outcome.evaluated_at)
        except Exception as e:
            logger.error("매매 실행 실패 (company_id=%d): %s", company.id, e)

    def _evaluate_old_outcomes(self, now: datetime) -> int:
        """
        N일 경과한 기존 결정들을 평가.

        조건: evaluated_at <= now and is_correct is NULL
        """
        outcomes = (
            self._s.query(Outcome)
            .filter(
                Outcome.evaluated_at <= now,
                Outcome.is_correct.is_(None),
            )
            .all()
        )

        evaluated = 0
        for outcome in outcomes:
            try:
                self._evaluate_single_outcome(outcome, now)
                evaluated += 1
            except Exception as e:
                logger.error("Outcome 평가 실패 (id=%d): %s", outcome.id, e)

        return evaluated

    def _evaluate_single_outcome(self, outcome: Outcome, now: datetime) -> None:
        """
        단일 Outcome 평가.

        BUY 신호 → 실제 상승했나?
        SELL 신호 → 실제 하락했나?
        """
        if outcome.price_at_decision is None:
            logger.warning("결정 시점 가격 없음 (outcome_id=%d)", outcome.id)
            return

        # 결정 이후 최신 가격 조회
        latest_price = self.price_fetcher.get_latest_price(outcome.company_id)
        if latest_price is None:
            logger.warning("최신 가격 없음 (company_id=%d)", outcome.company_id)
            return

        outcome.price_at_outcome = latest_price
        decision = outcome.decision

        # 신호에 맞게 평가
        if decision.signal == "BUY":
            # BUY: 실제로 상승했으면 정답
            outcome.is_correct = latest_price > outcome.price_at_decision
            outcome.actual_return = (latest_price - outcome.price_at_decision) / outcome.price_at_decision
        elif decision.signal == "SELL":
            # SELL: 실제로 하락했으면 정답
            outcome.is_correct = latest_price < outcome.price_at_decision
            outcome.actual_return = (outcome.price_at_decision - latest_price) / outcome.price_at_decision
        else:
            # HOLD: 무조건 정답으로 처리
            outcome.is_correct = True
            outcome.actual_return = 0.0

        outcome.actual_weight = abs(outcome.actual_return)
        outcome.evaluation_note = f"{decision.signal} 신호: 결정가={outcome.price_at_decision:.0f}, 평가가={latest_price:.0f}"

        logger.info(
            "Outcome 평가: %s | %s | 결정가=%.0f, 평가가=%.0f | 정답=%s",
            outcome.decision.company.ticker,
            decision.signal,
            outcome.price_at_decision,
            latest_price,
            outcome.is_correct,
        )

    def _get_active_companies(self) -> list[Company]:
        """활성 기업 목록 반환 (최근 주가 있는 것만)."""
        return (
            self._s.query(Company)
            .filter(Company.is_active == True)
            .all()
        )

    def _load_causal_edges(self) -> None:
        """DB의 인과관계 엣지를 메모리 그래프로 로드."""
        edges = self._s.query(CausalEdge).all()
        if not edges:
            logger.debug("로드할 인과관계 엣지가 없습니다")
            return

        loaded = 0
        for edge in edges:
            src = (edge.from_type, edge.from_id)
            dst = (edge.to_type, edge.to_id)
            self.graph.add_node(src)
            self.graph.add_node(dst)
            self.graph.add_edge(
                src,
                dst,
                weight=float(edge.weight),
                confidence=float(edge.confidence),
                direction=edge.direction,
                edge_id=edge.id,
            )
            loaded += 1

        logger.info("인과관계 그래프 로드: %d개 엣지 추가됨", loaded)
