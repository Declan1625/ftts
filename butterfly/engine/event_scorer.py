"""이벤트 중요도 점수화 - 중요한 이벤트를 먼저 처리"""
from __future__ import annotations
import re
from butterfly.db.models import Event

_TIER1 = {
    "fomc", "연준", "금리결정", "기준금리", "테이퍼링", "양적긴축", "qe",
    "긴급", "쇼크", "붕괴", "디폴트", "파산", "전쟁선포", "핵실험",
    "무역전쟁", "관세폭탄", "반도체수출금지", "북한", "미사일",
}
_TIER2 = {
    "금리인상", "금리인하", "gdp", "실업률", "cpi", "ppi", "인플레이션",
    "실적발표", "어닝쇼크", "어닝서프라이즈", "유가", "환율", "원달러",
    "공급망", "수출", "반도체", "배터리", "hbm",
}
_SOURCE_W = {
    "fed": 1.0, "dart": 0.9, "bok": 0.8, "moef": 0.7,
    "reuters": 0.7, "eia": 0.6, "bls": 0.6,
    "hankyung": 0.7, "mk": 0.65, "yna": 0.65,
}

QUICK_SECTOR_HINT = {
    "반도체": ["반도체", "메모리", "HBM", "D램", "낸드", "TSMC", "엔비디아", "AI칩", "파운드리"],
    "정유": ["유가", "원유", "WTI", "OPEC", "정유", "휘발유"],
    "철강": ["철강", "포스코", "철광석", "열연"],
    "자동차": ["자동차", "전기차", "현대차", "기아", "EV"],
    "금융": ["금리", "Fed", "연준", "기준금리", "은행", "FOMC"],
    "바이오": ["바이오", "제약", "FDA", "임상", "신약"],
    "배터리": ["배터리", "2차전지", "양극재", "음극재", "리튬", "전기차"],
    "방산": ["방위", "미사일", "북한", "무기", "방산", "전차"],
    "화학": ["화학", "나프타", "에틸렌", "폴리에틸렌"],
    "화장품": ["화장품", "K뷰티", "아모레", "중국관광", "면세"],
    "건설": ["건설", "주택", "아파트", "분양", "PF", "DSR"],
}


def score_event(event: Event) -> float:
    text = f"{event.title} {event.body or ''}".lower()
    src_w = _SOURCE_W.get(event.source, 0.5)
    if any(k in text for k in _TIER1):
        kw_score = 1.0
    elif any(k in text for k in _TIER2):
        kw_score = 0.6
    else:
        kw_score = 0.2
    nums = len(re.findall(r'\d+\.?\d*%', text))
    specificity = min(0.2, nums * 0.04)
    return kw_score * src_w + specificity


def quick_sectors(title: str) -> list[str]:
    """Claude 호출 없이 제목에서 빠른 섹터 추출"""
    found = []
    for sector, keywords in QUICK_SECTOR_HINT.items():
        if any(kw in title for kw in keywords):
            found.append(sector)
    return found
