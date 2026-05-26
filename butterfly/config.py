import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# KIS
KIS_APP_KEY: str = os.getenv("KIS_APP_KEY_KR", "")
KIS_APP_SECRET: str = os.getenv("KIS_APP_SECRET_KR", "")
KIS_ACCOUNT: str = os.getenv("KIS_ACCOUNT_NO_KR", "")

# Trading
PAPER_INITIAL_CASH: float = float(os.getenv("PAPER_INITIAL_CASH", "10000000"))
BUY_CONFIDENCE_MIN: float = float(os.getenv("BUY_CONFIDENCE_MIN", "0.65"))
POSITION_SIZE_RATIO: float = float(os.getenv("POSITION_SIZE_RATIO", "0.1"))  # 포지션당 자산의 10%

# Sources
DART_API_KEY: str = os.getenv("DART_API_KEY", "")
DISCORD_WEBHOOK: str = os.getenv("DISCORD_WEBHOOK_URL", "")
