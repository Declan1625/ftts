"""모든 소스에서 이벤트 수집 후 DB 저장"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Event
from butterfly.sources import reuters, dart, fed, eia, bok, bls, moef, hankyung, mk, yna, mer, fred, commodities

logger = logging.getLogger(__name__)
SOURCES = [reuters, dart, fed, eia, bok, bls, moef, hankyung, mk, yna, mer, fred, commodities]


def collect_and_save(session: Session) -> int:
    saved = 0
    for source in SOURCES:
        try:
            items = source.fetch()
            for item in items:
                if _exists(session, item["source"], item["title"]):
                    continue
                session.add(Event(**{k: v for k, v in item.items() if k != "ticker"}))
                saved += 1
            session.commit()
        except Exception as e:
            logger.error("수집 오류 [%s]: %s", source.__name__, e)
            session.rollback()
    logger.info("새 이벤트 %d건 저장", saved)
    return saved


def _exists(session: Session, source: str, title: str) -> bool:
    return session.query(Event).filter_by(source=source, title=title).first() is not None
