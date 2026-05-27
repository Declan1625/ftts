"""모든 소스에서 이벤트 수집 후 DB 저장"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from butterfly.db.models import Event
from butterfly.sources import bbc, dart, fed, eia, bok, bls, moef, hankyung, yna, mer, fred, commodities

logger = logging.getLogger(__name__)
SOURCES = [bbc, dart, fed, eia, bok, bls, moef, hankyung, yna, mer, fred, commodities]


def collect_and_save(session: Session) -> int:
    saved = 0
    for source in SOURCES:
        try:
            items = source.fetch()
            if not items:
                continue
            src_name = items[0]["source"]
            existing = {
                title for (title,) in
                session.query(Event.title).filter_by(source=src_name).all()
            }
            for item in items:
                if item["title"] in existing:
                    continue
                session.add(Event(**{k: v for k, v in item.items() if k != "ticker"}))
                saved += 1
            session.commit()
        except Exception as e:
            logger.error("수집 오류 [%s]: %s", source.__name__, e)
            session.rollback()
    logger.info("새 이벤트 %d건 저장", saved)
    return saved
