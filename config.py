"""
config.py - Central configuration.

All values come from environment variables (loaded from .env by python-dotenv).
Import this module anywhere: `import config; config.BOT_TOKEN`.
"""
import os
from pathlib import Path
from typing import List, Union

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
SESSION_DIR = BASE_DIR / "sessions"
LOG_DIR.mkdir(exist_ok=True)
SESSION_DIR.mkdir(exist_ok=True)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _int_list(raw: str) -> List[int]:
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _channel_list(raw: str) -> List[Union[int, str]]:
    """Accepts numeric IDs (-100...) or @usernames, comma separated."""
    channels: List[Union[int, str]] = []
    for item in raw.replace(" ", "").split(","):
        if not item:
            continue
        if item.lstrip("-").isdigit():
            channels.append(int(item))
        else:
            channels.append(item.lstrip("@"))
    return channels


# --- Telegram -------------------------------------------------------------
API_ID = int(_required("API_ID"))
API_HASH = _required("API_HASH")
BOT_TOKEN = _required("BOT_TOKEN")
DB_CHANNEL_ID = int(_required("DB_CHANNEL_ID"))
ADMINS = _int_list(_required("ADMINS"))

# --- Database -------------------------------------------------------------
MONGO_URI = _required("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "filesharebot")

# --- Behaviour ------------------------------------------------------------
FORCE_SUB_CHANNELS = _channel_list(os.getenv("FORCE_SUB_CHANNELS", ""))
AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "600"))   # 0 = disabled
PROTECT_CONTENT = _bool("PROTECT_CONTENT", True)
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "100"))

# --- Anti-flood -----------------------------------------------------------
FLOOD_MAX_MESSAGES = int(os.getenv("FLOOD_MAX_MESSAGES", "6"))        # messages...
FLOOD_WINDOW_SECONDS = int(os.getenv("FLOOD_WINDOW_SECONDS", "10"))   # ...per window
FLOOD_BLOCK_SECONDS = int(os.getenv("FLOOD_BLOCK_SECONDS", "60"))     # temp-block length
