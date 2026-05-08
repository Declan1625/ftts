"""outcome_evaluator.py — N일 후 자동 평가 (is_correct 설정).

역할:
1. DB에서 is_correct=None인 Outcome 중 결정일로부터 N일 이상 경과한 것을 조회
2. yfinance로 결정일 → 평가일의 주가 수익률 계산
3. 신호별로 정답/오답 판정:
   - BUY: 수익률 > 0 → is_correct=True / ≤ 0 → False
   - SELL: 수익률 < 0 → is_correct=True / ≥ 0 → False
4. Outcome 레코드 업데이트, Source 통계 재계산

사용:
    python -m monitoring.outcome_evaluator --eval
    python -m monitoring.outcome_evaluator --eval --eval-days 3
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database.db_manager import get_session
from database.models import Company, Decision, Outcome, Source

logger = logging.getLogger(__name__)

_DEFAULT_EVAL_DAYS = 5


class OutcomeEvaluator:
    """미평가 Outcome의 수익률 기반 정답/오답 판정 자동화."""

    def __init__(self, session: Session, eval_days: int = _DEFAULT_EVAL_DAYS) -> None:
        self._s = session
        self.eval_days = eval_days

    def evaluate_pending(self) -> int:
        """미평가 Outcome 전체 처리. 처리된 건수 반환."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.eval_days)

        # is_correct=None이고 결정일이 N일 이전인 것만
        q = (
            self._s.query(Outcome)
            .filter(Outcome.is_correct.is_(None))
            .join(Decision)
            .filter(Decision.decided_at < cutoff)
        )
        outcomes = q.all()

        if not outcomes:
            logger.info(f"평가 대상 Outcome 없음 (평가일 기준: {self.eval_days}일)")
            return 0

        processed = 0
        for outcome in outcomes:
            try:
                self._evaluate_one(outcome, now)
                processed += 1
            except Exception as e:
                logger.warning(f"Outcome {outcome.id} 평가 실패: {e}")
                continue

        # 변경된 Source의 통계 재계산
        self._refresh_source_stats()

        logger.info(f"Outcome 평가 완료: {processed}/{len(outcomes)}건")
        return processed

    def _evaluate_one(self, outcome: Outcome, now: datetime) -> None:
        """단일 Outcome 평가."""
        decision = outcome.decision
        company = outcome.company

        if not decision or not company:
            logger.warning(f"Outcome {outcome.id}: decision or company 없음")
            return

        ticker = company.ticker
        if not ticker:
            logger.warning(f"Outcome {outcome.id}: 기업 {company.id}의 ticker 없음")
            return

        # 결정일 → 평가일 주가 수익률
        decided_date = decision.decided_at.date()
        eval_date = min((now.date()), decided_date + timedelta(days=self.eval_days))

        try:
            price_start, price_end = self._fetch_price(ticker, decided_date, eval_date)
        except Exception as e:
            logger.warning(f"Ticker {ticker} 주가 조회 실패: {e}")
            return

        if price_start is None or price_end is None:
            logger.warning(f"Ticker {ticker}의 {decided_date}~{eval_date} 주가 없음")
            return

        actual_return = (price_end - price_start) / price_start
        is_correct = self._judge_outcome(decision.signal, actual_return)

        outcome.price_at_decision = float(price_start)
        outcome.price_at_outcome = float(price_end)
        outcome.actual_return = float(actual_return)
        outcome.is_correct = is_correct
        outcome.evaluated_at = now

        # Source 통계 업데이트
        source = decision.company.events[0].source if decision.company.events else None
        if source:
            source.total_predictions += 1
            if is_correct:
                source.correct_predictions += 1
            if source.total_predictions > 0:
                source.accuracy = source.correct_predictions / source.total_predictions

        self._s.flush()

    def _judge_outcome(self, signal: str, actual_return: float) -> bool:
        """신호별 정답 판정."""
        if signal == "BUY":
            return actual_return > 0.0
        elif signal == "SELL":
            return actual_return < 0.0
        else:  # HOLD
            return False

    def _fetch_price(self, ticker: str, from_date: date, to_date: date) -> tuple[float | None, float | None]:
        """yfinance로 주가 조회. (시작가, 종료가) 반환."""
        try:
            # 한국 종목 처리 (KOSPI/KOSDAQ는 .KS 접미사)
            symbol = ticker
            if not any(symbol.endswith(x) for x in [".KS", ".KQ", "F"]):
                # KOSPI 기본값 (나중에 market 컬럼 사용하면 더 정확해짐)
                if not any(c.isdigit() for c in symbol):
                    symbol = f"{ticker}.KS"

            df = yf.download(symbol, start=from_date, end=to_date + timedelta(days=1), progress=False)

            if df.empty:
                return None, None

            price_start = float(df.iloc[0]["Open"]) if len(df) > 0 else None
            price_end = float(df.iloc[-1]["Close"]) if len(df) > 0 else None

            return price_start, price_end
        except Exception as e:
            logger.debug(f"yfinance 오류 {ticker}: {e}")
            raise

    def _refresh_source_stats(self) -> None:
        """모든 Source의 total_predictions, correct_predictions, accuracy 업데이트."""
        sources = self._s.query(Source).filter(Source.is_active == True).all()
        for src in sources:
            evaluated = self._s.query(Outcome).join(Decision).filter(
                Outcome.is_correct.isnot(None),
                Decision.company.has(events__source_id=src.id),
            ).all()

            if evaluated:
                correct = sum(1 for o in evaluated if o.is_correct)
                src.total_predictions = len(evaluated)
                src.correct_predictions = correct
                src.accuracy = correct / len(evaluated)

        self._s.flush()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outcome 자동 평가")
    parser.add_argument("--eval", action="store_true", help="미평가 Outcome 평가")
    parser.add_argument("--eval-days", type=int, default=_DEFAULT_EVAL_DAYS, help="평가 기준 일수 (기본: 5)")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()

    with get_session() as session:
        evaluator = OutcomeEvaluator(session, eval_days=args.eval_days)

        if args.eval:
            n = evaluator.evaluate_pending()
            print(f"Outcome 평가 완료: {n}건")
