"""모의투자 REST API 서버.

엔드포인트:
- POST   /api/paper-trading/run           모의투자 실행
- GET    /api/paper-trading/status        현재 상태
- GET    /api/accuracy/report             정확도 리포트
- GET    /api/positions/current           현재 포지션
- GET    /api/health                      헬스 체크

사용:
    uvicorn api.paper_trading_api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import settings
from core.causal_graph import CausalGraph
from data.kis_api import KISClient, KISAuthError, KISAPIError
from database.db_manager import get_session
from database.models import Company, Position
from monitoring.accuracy_tracker import AccuracyTracker
from trading.paper_trader import PaperTrader
from trading.paper_trading_pipeline import PaperTradingPipeline

logger = logging.getLogger(__name__)

app = FastAPI(
    title="FTTS 모의투자 API",
    description="인과관계 기반 주식 AI 모의투자 시스템",
    version="1.0.0",
)


# ── Pydantic Models ───────────────────────────────────────────
class PaperTradingRunRequest(BaseModel):
    """모의투자 실행 요청."""
    market: str = "KR"  # "KR" 또는 "US"
    dry_run: bool = False  # True이면 실제 실행 없이 시뮬레이션


class PaperTradingRunResponse(BaseModel):
    """모의투자 실행 결과."""
    success: bool
    timestamp: datetime
    market: str
    companies_processed: int
    signals_generated: int
    trades_executed: int
    outcomes_evaluated: int
    portfolio_value: Optional[float] = None
    total_return: Optional[float] = None
    errors: list[str] = []


class AccuracyReportResponse(BaseModel):
    """정확도 리포트 응답."""
    total_evaluated: int
    correct: int
    accuracy: float
    live_gate_passed: bool
    by_signal: dict = {}
    by_company: dict = {}
    period_days: Optional[int] = None
    mercer_accuracy: Optional[float] = None
    buffett_accuracy: Optional[float] = None


class PositionResponse(BaseModel):
    """포지션 응답."""
    company_ticker: str
    company_name: str
    quantity: int
    avg_buy_price: float
    current_price: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_return: Optional[float]


class HealthResponse(BaseModel):
    """헬스 체크 응답."""
    status: str
    timestamp: datetime
    database: bool
    kis_kr: bool
    kis_us: bool


# ── 초기화 ───────────────────────────────────────────────────
_kis_clients: dict[str, Optional[KISClient]] = {}


def get_kis_client(market: str = "KR") -> KISClient:
    """시장별 KIS 클라이언트 반환."""
    global _kis_clients
    if market not in _kis_clients:
        try:
            if market == "KR":
                app_key = os.getenv("KIS_APP_KEY_KR")
                app_secret = os.getenv("KIS_APP_SECRET_KR")
                account_no = os.getenv("KIS_ACCOUNT_NO_KR")
            elif market == "US":
                app_key = os.getenv("KIS_APP_KEY_US")
                app_secret = os.getenv("KIS_APP_SECRET_US")
                account_no = os.getenv("KIS_ACCOUNT_NO_US")
            else:
                raise ValueError(f"Unknown market: {market}")

            if not all([app_key, app_secret, account_no]):
                raise ValueError(f"Missing KIS credentials for {market}")

            client = KISClient(app_key, app_secret, account_no, mock=True)
            client.authenticate()
            _kis_clients[market] = client
        except Exception as e:
            logger.error(f"KIS 클라이언트 초기화 실패 ({market}): {e}")
            _kis_clients[market] = None

    if _kis_clients[market] is None:
        raise HTTPException(status_code=503, detail=f"KIS {market} 서비스 불가")
    return _kis_clients[market]


# ── 헬스 체크 ─────────────────────────────────────────────────
@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """서버 및 외부 서비스 상태 확인."""
    db_ok = False
    kis_kr_ok = False
    kis_us_ok = False

    try:
        with get_session() as session:
            session.execute("SELECT 1")
            db_ok = True
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}")

    try:
        client = get_kis_client("KR")
        kis_kr_ok = client.is_token_valid()
    except Exception:
        pass

    try:
        client = get_kis_client("US")
        kis_us_ok = client.is_token_valid()
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        timestamp=datetime.now(timezone.utc),
        database=db_ok,
        kis_kr=kis_kr_ok,
        kis_us=kis_us_ok,
    )


# ── 모의투자 실행 ─────────────────────────────────────────────
@app.post("/api/paper-trading/run", response_model=PaperTradingRunResponse)
def run_paper_trading(request: PaperTradingRunRequest) -> PaperTradingRunResponse:
    """모의투자 파이프라인 실행."""
    try:
        kis = get_kis_client(request.market)
        now = datetime.now(timezone.utc)

        with get_session() as session:
            # 그래프 초기화
            graph = CausalGraph()

            # 파이프라인 실행
            pipeline = PaperTradingPipeline(kis, graph, session)
            result = pipeline.run_daily(now=now)

            # 포트폴리오 가치 계산
            price_map = pipeline.price_fetcher.get_latest_prices(
                [c.id for c in pipeline._get_active_companies()]
            )
            portfolio_value = pipeline.paper_trader.portfolio_value(price_map)
            total_return = pipeline.paper_trader.total_return(price_map)

            return PaperTradingRunResponse(
                success=True,
                timestamp=now,
                market=request.market,
                companies_processed=result["companies_processed"],
                signals_generated=result["signals_generated"],
                trades_executed=result.get("trades_executed", 0),
                outcomes_evaluated=result["outcomes_evaluated"],
                portfolio_value=portfolio_value,
                total_return=total_return,
                errors=result["errors"],
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"모의투자 실행 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── 정확도 리포트 ─────────────────────────────────────────────
@app.get("/api/accuracy/report", response_model=AccuracyReportResponse)
def get_accuracy_report(days: Optional[int] = Query(None)) -> AccuracyReportResponse:
    """정확도 리포트 조회."""
    try:
        with get_session() as session:
            tracker = AccuracyTracker(session)
            report = tracker.report(days=days)

            return AccuracyReportResponse(
                total_evaluated=report.total_evaluated,
                correct=report.correct,
                accuracy=report.accuracy,
                live_gate_passed=report.live_gate_passed,
                by_signal=report.by_signal,
                by_company={k: v for k, v in list(report.by_company.items())[:5]},
                period_days=report.period_days,
                mercer_accuracy=report.mercer_accuracy,
                buffett_accuracy=report.buffett_accuracy,
            )
    except Exception as e:
        logger.error(f"정확도 리포트 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 현재 포지션 ───────────────────────────────────────────────
@app.get("/api/positions/current", response_model=list[PositionResponse])
def get_current_positions(market: str = Query("KR")) -> list[PositionResponse]:
    """현재 모의투자 포지션 조회."""
    try:
        with get_session() as session:
            positions = (
                session.query(Position)
                .filter(Position.mode == "paper", Position.is_open == True)
                .all()
            )

            result = []
            for pos in positions:
                company = pos.company or session.get(Company, pos.company_id)
                if company is None:
                    continue

                # 현재 가격
                from data.price_fetcher import PriceFetcher
                kis = get_kis_client(market)
                fetcher = PriceFetcher(kis, session)
                current_price = fetcher.get_latest_price(pos.company_id)

                unrealized_pnl = None
                unrealized_return = None
                if current_price and pos.avg_buy_price:
                    unrealized_pnl = (current_price - pos.avg_buy_price) * pos.quantity
                    unrealized_return = (current_price - pos.avg_buy_price) / pos.avg_buy_price

                result.append(
                    PositionResponse(
                        company_ticker=company.ticker,
                        company_name=company.name,
                        quantity=pos.quantity,
                        avg_buy_price=float(pos.avg_buy_price or 0),
                        current_price=current_price,
                        unrealized_pnl=unrealized_pnl,
                        unrealized_return=unrealized_return,
                    )
                )

            return result

    except Exception as e:
        logger.error(f"포지션 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 상태 조회 ─────────────────────────────────────────────────
@app.get("/api/paper-trading/status")
def get_status(market: str = Query("KR")) -> dict:
    """모의투자 상태 조회."""
    try:
        with get_session() as session:
            kis = get_kis_client(market)
            trader = PaperTrader(session)

            positions = trader.open_positions()
            return {
                "status": "running",
                "market": market,
                "cash": trader.cash,
                "open_positions": len(positions),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 오류 핸들링 ───────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


if __name__ == "__main__":
    import os
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "api.paper_trading_api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False,
    )
