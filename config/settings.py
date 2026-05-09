import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./ftts.db")

# ── Learning & Thresholds ────────────────────────────────────
LEARNING_RATE: float = float(os.getenv("LEARNING_RATE", "0.1"))
BUY_THRESHOLD: float = float(os.getenv("BUY_THRESHOLD", "0.6"))
SELL_THRESHOLD: float = float(os.getenv("SELL_THRESHOLD", "-0.5"))
RECENCY_DECAY_LAMBDA: float = float(os.getenv("RECENCY_DECAY_LAMBDA", "0.05"))

# ── Source Grade Weights ─────────────────────────────────────
GRADE_WEIGHTS: dict[str, float] = {
    "S": float(os.getenv("GRADE_WEIGHT_S", "1.0")),
    "A": float(os.getenv("GRADE_WEIGHT_A", "0.8")),
    "B": float(os.getenv("GRADE_WEIGHT_B", "0.6")),
    "C": float(os.getenv("GRADE_WEIGHT_C", "0.4")),
    "D": float(os.getenv("GRADE_WEIGHT_D", "0.2")),
}
GRADE_THRESHOLDS: dict[str, float] = {
    "S": float(os.getenv("GRADE_THRESHOLD_S", "0.90")),
    "A": float(os.getenv("GRADE_THRESHOLD_A", "0.75")),
    "B": float(os.getenv("GRADE_THRESHOLD_B", "0.60")),
    "C": float(os.getenv("GRADE_THRESHOLD_C", "0.45")),
}
MIN_PREDICTIONS_FOR_GRADE: int = int(os.getenv("MIN_PREDICTIONS_FOR_GRADE", "10"))
NEUTRAL_WEIGHT_BELOW_MIN: float = float(os.getenv("NEUTRAL_WEIGHT_BELOW_MIN", "0.5"))

# ── Source Auto-disable ───────────────────────────────────────
CONSECUTIVE_D_DISABLE: int = int(os.getenv("CONSECUTIVE_D_DISABLE", "3"))

# ── Accuracy Gate ─────────────────────────────────────────────
LIVE_TRADING_ACCURACY_GATE: float = float(os.getenv("LIVE_TRADING_ACCURACY_GATE", "0.80"))

# ── Paper Trading ─────────────────────────────────────────────
PAPER_INITIAL_CASH: float = float(os.getenv("PAPER_INITIAL_CASH", "10000000"))  # 1천만 원
