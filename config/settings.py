import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────
DATABASE_URL: str = os.environ["DATABASE_URL"]  # e.g. postgresql+psycopg2://user:pass@host/dbname

# ── Learning & Thresholds ────────────────────────────────────
LEARNING_RATE: float = float(os.getenv("LEARNING_RATE", "0.1"))
BUY_THRESHOLD: float = float(os.getenv("BUY_THRESHOLD", "0.6"))
SELL_THRESHOLD: float = float(os.getenv("SELL_THRESHOLD", "-0.3"))
RECENCY_DECAY_LAMBDA: float = float(os.getenv("RECENCY_DECAY_LAMBDA", "0.05"))

# ── Source Grade Weights ─────────────────────────────────────
GRADE_WEIGHTS: dict[str, float] = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2}
GRADE_THRESHOLDS: dict[str, float] = {"S": 0.90, "A": 0.75, "B": 0.60, "C": 0.45}
MIN_PREDICTIONS_FOR_GRADE: int = int(os.getenv("MIN_PREDICTIONS_FOR_GRADE", "10"))
NEUTRAL_WEIGHT_BELOW_MIN: float = 0.5

# ── Source Auto-disable ───────────────────────────────────────
CONSECUTIVE_D_DISABLE: int = int(os.getenv("CONSECUTIVE_D_DISABLE", "3"))

# ── Accuracy Gate ─────────────────────────────────────────────
LIVE_TRADING_ACCURACY_GATE: float = float(os.getenv("LIVE_TRADING_ACCURACY_GATE", "0.80"))

# ── Paper Trading ─────────────────────────────────────────────
PAPER_INITIAL_CASH: float = float(os.getenv("PAPER_INITIAL_CASH", "10000000"))  # 1천만 원
