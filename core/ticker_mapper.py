"""core/ticker_mapper.py — 기업명 → ticker/market 매핑 (Claude API 기반).

두 가지 기능:
1. map_tickers: OTHER 마켓 기업 → ticker 매핑
   - 단일 기업: 직접 매핑
   - 복수 기업 통칭 ("SK이노베이션, GS칼텍스 등"): 개별 기업으로 분해 후 각각 매핑
   - 기관/국제기구/가상기업: is_active=False 처리

2. extract_event_dates: events 텍스트에서 사건 발생일 추출
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from anthropic import Anthropic
from sqlalchemy.orm import Session

from config.settings import ANTHROPIC_MODEL
from database.models import Company, Event

logger = logging.getLogger(__name__)

_BATCH_SIZE = 15


@dataclass
class TickerInfo:
    company_id: int
    original_name: str
    ticker: Optional[str]
    market: Optional[str]
    normalized_name: Optional[str]
    expanded: list[dict] = field(default_factory=list)  # 분해된 개별 기업들


# ── 시스템 프롬프트 ────────────────────────────────────────────────

_TICKER_SYSTEM = """\
당신은 주식 ticker 전문가입니다.

기업명 목록을 받아 각 항목에 대해 다음을 처리합니다:

1. 단일 상장 기업 → ticker, market 반환
2. 복수 기업 통칭 ("SK이노베이션, GS칼텍스 등") → expanded 배열로 각 기업 분해
3. 상장사가 아닌 것 (중앙은행, 국제기구, 군대, 가상기업, 업종 전체) → ticker=null

ticker 형식:
- 한국: 6자리 숫자 (예: 096770)
- 미국: 알파벳 (예: XOM)
- 상장 불가: null

market: KOSPI / KOSDAQ / NYSE / NASDAQ / null

응답 (JSON 배열만, 다른 텍스트 없이):
[
  {"id": 1, "ticker": "096770", "market": "KOSPI", "name": "SK이노베이션", "expanded": []},
  {"id": 2, "ticker": null, "market": null, "name": null, "expanded": [
    {"ticker": "096770", "market": "KOSPI", "name": "SK이노베이션"},
    {"ticker": "078930", "market": "KOSPI", "name": "GS칼텍스(GS홀딩스)"},
    {"ticker": "010950", "market": "KOSPI", "name": "S-Oil"}
  ]},
  {"id": 3, "ticker": null, "market": null, "name": null, "expanded": []}
]
"""

_DATE_SYSTEM = """\
주어진 사건이 실제로 발생한 날짜를 찾아주세요.
web_search 도구로 검색해서 정확한 날짜를 확인하세요.

응답 (JSON만, 다른 텍스트 없이):
{"date": "2026-01-03"}  또는  {"date": null}
"""


# ── Claude 호출 ────────────────────────────────────────────────────

def _ask_tickers(client: Anthropic, batch: list[tuple[int, str]]) -> list[dict]:
    items = "\n".join(f"{i+1}. [id={cid}] {name}" for i, (cid, name) in enumerate(batch))
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        system=_TICKER_SYSTEM,
        messages=[{"role": "user", "content": f"다음 기업들을 처리해주세요:\n\n{items}"}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _ask_date(client: Anthropic, event_text: str, post_year: int) -> Optional[str]:
    """웹 검색으로 사건 발생 날짜 확인."""
    messages = [{"role": "user", "content": f"다음 사건의 실제 발생 날짜를 검색해서 알려주세요. 날짜만 JSON으로 응답: {event_text}"}]

    # 웹 검색 tool_use 루프
    for _ in range(5):
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=512,
            system=_DATE_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=messages,
        )

        # tool_use 처리
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",  # SDK가 자동으로 검색 결과 채움
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # 최종 텍스트 응답
        raw = ""
        for block in resp.content:
            if hasattr(block, "text"):
                raw += block.text
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw.strip()).get("date")
        except Exception:
            # JSON 파싱 실패 시 날짜 패턴 직접 추출
            m = re.search(r"\d{4}-\d{2}-\d{2}", raw)
            return m.group(0) if m else None

    return None


# ── 메인 함수 ──────────────────────────────────────────────────────

def map_tickers(session: Session, dry_run: bool = False) -> list[TickerInfo]:
    """OTHER 마켓 기업 → ticker 매핑. 통칭 기업은 분해해서 개별 등록."""
    companies = (
        session.query(Company)
        .filter_by(market="OTHER", is_active=True)
        .all()
    )
    if not companies:
        logger.info("매핑할 기업 없음")
        return []

    client = Anthropic()
    results: list[TickerInfo] = []

    for i in range(0, len(companies), _BATCH_SIZE):
        batch_companies = companies[i:i + _BATCH_SIZE]
        batch = [(c.id, c.name) for c in batch_companies]

        try:
            mapped = _ask_tickers(client, batch)
            id_to_result = {m["id"]: m for m in mapped}

            for cmp in batch_companies:
                m = id_to_result.get(cmp.id, {})
                ticker = m.get("ticker")
                market = m.get("market")
                norm_name = m.get("name")
                expanded = m.get("expanded", [])

                info = TickerInfo(
                    company_id=cmp.id,
                    original_name=cmp.name,
                    ticker=ticker,
                    market=market,
                    normalized_name=norm_name,
                    expanded=expanded,
                )
                results.append(info)

                if dry_run:
                    continue

                if ticker and market:
                    # 단일 기업 매핑
                    existing = session.query(Company).filter(
                        Company.ticker == ticker,
                        Company.id != cmp.id,
                    ).first()
                    if existing:
                        cmp.is_active = False
                    else:
                        cmp.ticker = ticker
                        cmp.market = market
                        if norm_name:
                            cmp.name = norm_name
                        logger.info("매핑: %s → %s (%s)", cmp.name, ticker, market)

                elif expanded:
                    # 통칭 기업 → 개별 등록
                    cmp.is_active = False  # 원본 비활성화
                    for exp in expanded:
                        exp_ticker = exp.get("ticker")
                        exp_market = exp.get("market")
                        exp_name = exp.get("name")
                        if not (exp_ticker and exp_market and exp_name):
                            continue
                        existing = session.query(Company).filter_by(ticker=exp_ticker).first()
                        if not existing:
                            new_cmp = Company(
                                ticker=exp_ticker,
                                name=exp_name,
                                market=exp_market,
                                industry_id=cmp.industry_id,
                            )
                            session.add(new_cmp)
                            logger.info("분해 등록: %s → %s (%s)", exp_name, exp_ticker, exp_market)
                    session.flush()

                else:
                    # 매핑 불가 (기관, 국제기구 등)
                    cmp.is_active = False
                    logger.info("매핑 불가 → 비활성화: %s", cmp.name)

        except Exception as exc:
            logger.error("배치 %d 실패: %s", i // _BATCH_SIZE + 1, exc)

    if not dry_run:
        session.commit()
        logger.info("ticker 매핑 완료: %d개 처리", len(results))

    return results


def extract_event_dates(session: Session) -> int:
    """occurred_at이 포스트 발행일로 설정된 Event들에서 실제 사건 날짜 추출 후 업데이트."""
    client = Anthropic()
    updated = 0

    events = session.query(Event).all()
    for ev in events:
        if not ev.title:
            continue

        post_year = ev.occurred_at.year if ev.occurred_at else datetime.now().year

        try:
            date_str = _ask_date(client, ev.title, post_year)
            if date_str:
                new_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                # 포스트 발행일보다 미래면 스킵 (파싱 오류)
                if ev.occurred_at and new_dt > ev.occurred_at:
                    continue
                ev.occurred_at = new_dt
                updated += 1
                logger.info("날짜 업데이트: [%s] → %s", ev.title[:40], date_str)
        except Exception as exc:
            logger.warning("날짜 추출 실패 ev_id=%d: %s", ev.id, exc)

    session.commit()
    logger.info("사건 날짜 업데이트 완료: %d건", updated)
    return updated


def mapping_report(results: list[TickerInfo]) -> dict:
    mapped = [r for r in results if r.ticker]
    expanded_list = [r for r in results if r.expanded]
    unmapped = [r for r in results if not r.ticker and not r.expanded]
    return {
        "total": len(results),
        "mapped": len(mapped),
        "expanded": len(expanded_list),
        "unmapped": len(unmapped),
        "mapped_list": [
            {"id": r.company_id, "name": r.original_name, "ticker": r.ticker, "market": r.market}
            for r in mapped
        ],
        "expanded_list": [
            {"id": r.company_id, "name": r.original_name, "companies": r.expanded}
            for r in expanded_list
        ],
        "unmapped_list": [{"id": r.company_id, "name": r.original_name} for r in unmapped],
    }
