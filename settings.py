import os
from dotenv import load_dotenv

load_dotenv()

# --- Required ---
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
USER_CHAT_ID: int = int(os.getenv("USER_CHAT_ID", "0"))

# --- Localisation ---
TIMEZONE: str = os.getenv("TIMEZONE", "America/Sao_Paulo")

# --- Scheduling ---
PLANNING_TIME: str = os.getenv("PLANNING_TIME", "23:30")        # HH:MM nightly planning
WEEKLY_REVIEW_DAY: str = os.getenv("WEEKLY_REVIEW_DAY", "sunday")      # monday | sunday

# --- Database ---
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/orion.db")

# --- Anthropic models ---
DEFAULT_MODEL: str = "claude-haiku-4-5"     # used for all interactions except /decidir
DECISION_MODEL: str = "claude-sonnet-4-5"   # used for /decidir (complex reasoning)

MAX_TOKENS_DEFAULT: int = 1024
MAX_TOKENS_DECISION: int = 2048
