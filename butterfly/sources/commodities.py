"""실물 선행지표 - 금/구리/유가/BDI - 메르식 나비효과의 핵심"""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)

# Yahoo Finance 무료 API (인증 불필요)
# ticker: (이름, 한국 주식 나비효과)
TICKERS = {
    "HG=F":  ("구리 선물",      "경기 선행지표 → 소재/화학/전선"),
    "GC=F":  ("금 선물",        "안전자산 수요 → 위험자산 역관계"),
    "BZ=F":  ("브렌트유",       "정유/화학/항공 나비효과"),
    "CL=F":  ("WTI 원유",       "에너지 섹터 + 물가 나비효과"),
    "SI=F":  ("은 선물",        "산업용 수요 → 전자/배터리"),
}

# BDI는 Yahoo에 없으므로 stooq.com CSV 활용
_BDI_URL = "https://stooq.com/q/d/l/?s=bdi&i=d"

_YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def fetch() -> list[dict]:
    items = []
    items.extend(_fetch_yahoo())
    items.extend(_fetch_bdi())
    return items


def _fetch_yahoo() -> list[dict]:
    items = []
    for ticker, (name, reason) in TICKERS.items():
        try:
            r = httpx.get(
                _YF_BASE.format(ticker=ticker),
                params={"interval": "1d", "range": "3d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            data = r.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                continue
            latest, prev = closes[-1], closes[-2]
            change_pct = (latest - prev) / prev * 100
            direction = "상승" if change_pct > 0 else "하락"
            title = f"[원자재] {name} {direction} {change_pct:+.2f}%: ${latest:,.2f}"
            items.append({
                "source": "commodities",
                "title": title,
                "body": f"{name}({ticker}) 현재=${latest:.2f}, 전일대비{change_pct:+.2f}%. 나비효과: {reason}",
                "url": f"https://finance.yahoo.com/quote/{ticker}",
                "published_at": None,
            })
        except Exception as e:
            logger.debug("Yahoo Finance %s 실패: %s", ticker, e)
    return items


def _fetch_bdi() -> list[dict]:
    try:
        r = httpx.get(_BDI_URL, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        lines = [l for l in r.text.strip().splitlines() if l and not l.startswith("Date")]
        if len(lines) < 2:
            return []
        last = lines[-1].split(",")
        prev = lines[-2].split(",")
        val = float(last[4])    # Close
        prev_val = float(prev[4])
        change = val - prev_val
        direction = "상승" if change > 0 else "하락"
        title = f"[BDI] 발틱운임지수 {direction}: {prev_val:.0f} → {val:.0f} ({change:+.0f})"
        return [{
            "source": "commodities",
            "title": title,
            "body": f"BDI(발틱운임지수)={val:.0f}. 나비효과: 해운/조선 수요 선행지표 → HMM/HD현대중공업",
            "url": "https://www.balticexchange.com/en/data-services/market-information0/the-baltic-indices.html",
            "published_at": None,
        }]
    except Exception as e:
        logger.debug("BDI 수집 실패: %s", e)
        return []
