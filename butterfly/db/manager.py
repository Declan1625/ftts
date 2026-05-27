from __future__ import annotations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from .models import Base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./butterfly.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    poolclass=NullPool,
)
SessionLocal = sessionmaker(bind=engine)

_MIGRATIONS = [
    "ALTER TABLE trades ADD COLUMN company_name TEXT",
    "ALTER TABLE trades ADD COLUMN current_price REAL",
    "ALTER TABLE trades ADD COLUMN target_price REAL",
    "ALTER TABLE trades ADD COLUMN stop_loss_price REAL",
    "ALTER TABLE trades ADD COLUMN pnl_pct REAL DEFAULT 0",
    "ALTER TABLE trades ADD COLUMN status TEXT DEFAULT 'open'",
    "ALTER TABLE trades ADD COLUMN risk_tier TEXT DEFAULT 'MEDIUM'",
    "ALTER TABLE signals ADD COLUMN risk_tier TEXT DEFAULT 'MEDIUM'",
    # v2: 피드백 루프 + 패턴 연결
    "ALTER TABLE signals ADD COLUMN pattern_id INTEGER REFERENCES causal_patterns(id)",
]


def init_db():
    Base.metadata.create_all(engine)
    if "sqlite" in DATABASE_URL:
        with engine.connect() as conn:
            for sql in _MIGRATIONS:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass


def get_session() -> Session:
    return SessionLocal()
