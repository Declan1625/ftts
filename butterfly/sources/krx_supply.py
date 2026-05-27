"""KRX 투자자별 수급 데이터
외국인·기관 순매수 방향으로 신호 신뢰도 보정
pykrx 사용: pip install pykrx
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)


def _recent_dates() -> tuple[str, str]:
    """최근 5거래일 범위"""
    end = datetime.today()
    start = end - timedelta(days=10)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


@lru_cache(maxsize=300)
def _fetch(ticker: str, start: str, end: str) -> dict:
    try:
        from pykrx import stock
        df = stock.get_market_trading_value_by_investor(start, end, ticker)
        if df is None or df.empty:
            return {}

        # 컬럼명 정규화
        col_foreign = next((c for c in df.columns if "외국인" in c), None)
        col_inst = next((c for c in df.columns if "기관" in c and "합계" in c), \
                        next((c for c in df.columns if "기관" in c), None))

        foreign_net = float(df[col_foreign].sum()) if col_foreign else 0.0
        inst_net    = float(df[col_inst].sum())    if col_inst    else 0.0

        def _dir(v: float) -> str:
            return "BUY" if v > 0 else ("SELL" if v < 0 else "NEUTRAL")

        total = abs(foreign_net) + abs(inst_net) or 1
        score = (foreign_net * 0.6 + inst_net * 0.4) / total

        return {
            "foreign":      _dir(foreign_net),
            "institution":  _dir(inst_net),
            "foreign_net":  int(foreign_net),
            "inst_net":     int(inst_net),
            "score":        round(score, 3),  # -1(강매도) ~ +1(강매수)
        }
    except Exception as e:
        logger.debug("수급 조회 실패 [%s]: %s", ticker, e)
        return {}


def get_supply(ticker: str) -> dict:
    s, e = _recent_dates()
    return _fetch(ticker, s, e)


def adjust_confidence(ticker: str, confidence: float) -> float:
    """수급 기반 신뢰도 보정 (±15%)"""
    supply = get_supply(ticker)
    if not supply:
        return confidence
    score = supply.get("score", 0)
    adjusted = confidence * (1 + score * 0.15)
    result = round(min(1.0, max(0.0, adjusted)), 3)
    if abs(score) > 0.1:
        logger.info("📊 수급보정 [%s] 외국인:%s 기관:%s score:%.2f → %.2f→%.2f",
                    ticker, supply["foreign"], supply["institution"],
                    score, confidence, result)
    return result
