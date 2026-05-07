"""nlp/entity_linker.py — 기업·산업명 정규화 및 DB 매핑"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from database.models import Company, Industry

logger = logging.getLogger(__name__)

_MIN_SIMILARITY = 0.75


def link_companies(session: Session, names: list[str]) -> dict[str, Company | None]:
    """기업명 목록 → {원본명: Company 객체} 매핑. 미매핑은 None."""
    all_companies = session.query(Company).filter(Company.is_active == True).all()
    result: dict[str, Company | None] = {}
    for name in names:
        result[name] = _find_best_company(name, all_companies)
    return result


def link_industries(session: Session, names: list[str]) -> dict[str, Industry | None]:
    """산업명 목록 → {원본명: Industry 객체} 매핑."""
    all_industries = session.query(Industry).all()
    result: dict[str, Industry | None] = {}
    for name in names:
        result[name] = _find_best_industry(name, all_industries)
    return result


def normalize_ticker(ticker: str, market: str) -> str:
    """티커 정규화: 공백 제거, 대문자 변환, 한국 종목 6자리 패딩."""
    ticker = ticker.strip().upper()
    if market in ("KOSPI", "KOSDAQ") and re.match(r"^\d{1,6}$", ticker):
        ticker = ticker.zfill(6)
    return ticker


def _find_best_company(name: str, companies: list[Company]) -> Company | None:
    name_clean = _clean(name)
    best_score = 0.0
    best: Company | None = None

    for company in companies:
        score = max(
            _similarity(name_clean, _clean(company.name)),
            _similarity(name_clean, _clean(company.ticker)),
        )
        if score > best_score:
            best_score = score
            best = company

    if best_score >= _MIN_SIMILARITY:
        logger.debug("기업 매핑: '%s' → '%s' (score=%.2f)", name, best.name, best_score)
        return best

    logger.debug("기업 미매핑: '%s' (best_score=%.2f)", name, best_score)
    return None


def _find_best_industry(name: str, industries: list[Industry]) -> Industry | None:
    name_clean = _clean(name)
    best_score = 0.0
    best: Industry | None = None

    for industry in industries:
        score = max(
            _similarity(name_clean, _clean(industry.name)),
            _similarity(name_clean, _clean(industry.code)),
        )
        if score > best_score:
            best_score = score
            best = industry

    if best_score >= _MIN_SIMILARITY:
        return best
    return None


def _clean(text: str) -> str:
    return re.sub(r"[\s\(\)\[\]·,.]", "", text).lower()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()
