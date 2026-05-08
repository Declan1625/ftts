"""
DB 연결, 세션 관리, 테이블 초기화.

사용:
    python -m database.db_manager --init   # 테이블 생성
    python -m database.db_manager --drop   # 테이블 전체 삭제 (주의)
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import DATABASE_URL
from database.models import Base

logger = logging.getLogger(__name__)

_engine_kwargs = {"echo": False}
if not DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    })

_engine = create_engine(DATABASE_URL, **_engine_kwargs)

_SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    if DATABASE_URL.startswith("postgresql"):
        with _engine.connect() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            conn.commit()
    Base.metadata.create_all(_engine)
    logger.info("DB 초기화 완료 — 테이블 %d개 생성", len(Base.metadata.tables))


def drop_db() -> None:
    Base.metadata.drop_all(_engine)
    logger.warning("DB 전체 삭제 완료")


# ── CRUD 헬퍼 ────────────────────────────────────────────────

def get_or_create(session: Session, model, defaults: dict | None = None, **kwargs):
    """존재하면 반환, 없으면 생성 후 반환. (instance, created) 튜플."""
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance, False
    params = {**kwargs, **(defaults or {})}
    instance = model(**params)
    session.add(instance)
    session.flush()
    return instance, True


def bulk_insert(session: Session, objects: list) -> None:
    session.add_all(objects)
    session.flush()


def upsert_causal_edge(
    session: Session,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    weight: float,
    confidence: float,
    direction: int,
    observation_count: int = 1,
) -> None:
    """인과관계 엣지 upsert (존재하면 업데이트, 없으면 생성)."""
    from database.models import CausalEdge

    existing = (
        session.query(CausalEdge)
        .filter_by(
            from_type=from_type,
            from_id=from_id,
            to_type=to_type,
            to_id=to_id,
        )
        .first()
    )

    if existing:
        existing.weight = weight
        existing.confidence = confidence
        existing.direction = direction
        existing.observation_count = observation_count
    else:
        edge = CausalEdge(
            from_type=from_type,
            from_id=from_id,
            to_type=to_type,
            to_id=to_id,
            weight=weight,
            confidence=confidence,
            direction=direction,
            observation_count=observation_count,
        )
        session.add(edge)

    session.flush()

# ── CLI ──────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FTTS DB 관리")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="테이블 생성")
    group.add_argument("--drop", action="store_true", help="테이블 전체 삭제")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()
    if args.init:
        init_db()
    elif args.drop:
        confirm = input("정말 모든 테이블을 삭제합니까? (yes/no): ")
        if confirm.strip().lower() == "yes":
            drop_db()
        else:
            print("취소됨")
