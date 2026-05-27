"""백테스트 엔진
역사적 가격 데이터(yfinance)로 인과 논리 정확도 검증
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 종목코드 → Yahoo Finance 티커
_YF = {
    "005930": "005930.KS", "000660": "000660.KS", "373220": "373220.KS",
    "207940": "207940.KS", "006400": "006400.KS", "051910": "051910.KS",
    "035420": "035420.KS", "005380": "005380.KS", "000270": "000270.KS",
    "003670": "003670.KS", "086790": "086790.KS", "105560": "105560.KS",
    "055550": "055550.KS", "096770": "096770.KS", "010950": "010950.KS",
    "034020": "034020.KS", "047810": "047810.KS", "012450": "012450.KS",
    "000880": "000880.KS", "LIG": "079550.KS",
}

# 검증된 역사적 케이스
# (이벤트유형, 섹터, 종목코드, 방향, 날짜, 설명)
CASES = [
    ("통화정책", "은행",   "105560", "BUY",  "2022-02-01", "한은 기준금리 인상 → KB금융"),
    ("통화정책", "은행",   "086790", "BUY",  "2022-07-13", "연준 자이언트스텝 → 하나금융"),
    ("무역",     "반도체", "000660", "SELL", "2022-10-10", "미 반도체 수출규제 → SK하이닉스"),
    ("무역",     "반도체", "000660", "BUY",  "2023-05-10", "AI 수요 HBM 급등 → SK하이닉스"),
    ("지정학",   "방산",   "047810", "BUY",  "2022-03-01", "러-우 전쟁 → 한국항공우주"),
    ("지정학",   "방산",   "012450", "BUY",  "2023-10-09", "이스라엘-하마스 → 한화에어로"),
    ("원자재",   "정유",   "010950", "BUY",  "2022-03-07", "유가 급등 → S-Oil"),
    ("원자재",   "정유",   "010950", "SELL", "2022-11-28", "유가 하락 전환 → S-Oil"),
    ("기업실적", "배터리", "373220", "BUY",  "2023-01-30", "LG엔솔 실적 서프라이즈"),
    ("무역",     "배터리", "373220", "SELL", "2023-08-17", "IRA 세부조항 불확실성"),
    ("통화정책", "반도체", "005930", "BUY",  "2022-09-27", "원달러 환율 급등 → 삼성전자"),
    ("지정학",   "방산",   "012450", "BUY",  "2024-01-02", "북한 도발 긴장 → 한화에어로"),
]


def _get_return(ticker: str, entry_date: str, hold_days: int) -> dict:
    yf_ticker = _YF.get(ticker, f"{ticker}.KS")
    try:
        import yfinance as yf
        start = datetime.strptime(entry_date, "%Y-%m-%d")
        end = start + timedelta(days=hold_days + 15)
        df = yf.download(
            yf_ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False, auto_adjust=True,
        )
        if df.empty or len(df) < 2:
            return {"error": "데이터 없음"}
        entry_price = float(df["Close"].iloc[0])
        exit_idx = min(hold_days, len(df) - 1)
        exit_price = float(df["Close"].iloc[exit_idx])
        ret = (exit_price - entry_price) / entry_price * 100
        return {
            "entry_price": round(entry_price, 0),
            "exit_price": round(exit_price, 0),
            "return_pct": round(ret, 2),
        }
    except Exception as e:
        return {"error": str(e)}


def run(hold_days: int = 10) -> dict:
    """CASES 전체 백테스트 실행"""
    results = []
    for event_type, sector, ticker, direction, date, desc in CASES:
        r = _get_return(ticker, date, hold_days)
        if "error" not in r:
            ret = r["return_pct"]
            correct = (direction == "BUY" and ret > 0.5) or (direction == "SELL" and ret < -0.5)
            r.update({"is_correct": correct})
            logger.info("%s [%s %s %s] %.2f%% %s",
                        "✅" if correct else "❌", ticker, direction, date, ret, desc[:20])
        results.append({
            "event_type": event_type, "sector": sector, "ticker": ticker,
            "direction": direction, "entry_date": date, "description": desc,
            **r,
        })

    valid = [r for r in results if "error" not in r]
    correct = [r for r in valid if r.get("is_correct")]

    # 섹터별 집계
    by_sector: dict[str, dict] = {}
    for r in valid:
        s = r["sector"]
        bs = by_sector.setdefault(s, {"total": 0, "correct": 0, "returns": []})
        bs["total"] += 1
        if r.get("is_correct"):
            bs["correct"] += 1
        bs["returns"].append(r.get("return_pct", 0))

    sector_stats = {
        s: {
            "accuracy_pct": round(v["correct"] / v["total"] * 100, 1),
            "avg_return_pct": round(sum(v["returns"]) / len(v["returns"]), 2),
            "sample": v["total"],
        }
        for s, v in by_sector.items()
    }

    return {
        "hold_days": hold_days,
        "total": len(CASES),
        "valid": len(valid),
        "correct": len(correct),
        "accuracy_pct": round(len(correct) / len(valid) * 100, 1) if valid else 0,
        "avg_return_pct": round(
            sum(r.get("return_pct", 0) for r in valid) / len(valid), 2
        ) if valid else 0,
        "by_sector": sector_stats,
        "details": results,
    }


def run_from_db(session, hold_days: int = 10) -> dict:
    """DB 실제 청산 거래로 백테스트"""
    from butterfly.db.models import Trade
    closed = session.query(Trade).filter_by(status="closed").all()
    if not closed:
        return {"error": "청산 거래 없음", "details": []}

    results = []
    for t in closed:
        if not t.entered_at or not t.ticker:
            continue
        date_str = t.entered_at.strftime("%Y-%m-%d")
        r = _get_return(t.ticker, date_str, hold_days)
        if "error" not in r:
            ret = r["return_pct"]
            correct = (t.direction == "BUY" and ret > 0.5) or (t.direction == "SELL" and ret < -0.5)
            r["is_correct"] = correct
        results.append({
            "ticker": t.ticker, "direction": t.direction,
            "entry_date": date_str,
            "actual_pnl_pct": round(t.pnl_pct or 0, 2),
            "actual_correct": t.is_correct,
            **r,
        })

    valid = [r for r in results if "error" not in r]
    correct_bt = [r for r in valid if r.get("is_correct")]
    correct_actual = [t for t in closed if t.is_correct]

    return {
        "hold_days": hold_days,
        "total_trades": len(closed),
        "valid": len(valid),
        "backtest_accuracy_pct": round(len(correct_bt) / len(valid) * 100, 1) if valid else 0,
        "actual_accuracy_pct": round(len(correct_actual) / len(closed) * 100, 1) if closed else 0,
        "details": results,
    }
