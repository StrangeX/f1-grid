from __future__ import annotations

import os


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


API_BASE = getenv("F1_API_BASE", "https://api.jolpi.ca/ergast/f1").rstrip("/")
SEASON = getenv("F1_SEASON", "current")
CACHE_TTL_SEC = int(getenv("F1_CACHE_TTL", "21600") or "21600")
REDIS_URL = getenv("REDIS_URL")

OPENAI_API_KEY = getenv("OPENAI_API_KEY")
OPENAI_MODEL = getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
SIMS = int(getenv("F1_SIMS", "4000") or "4000")
POLL_IDLE_SEC = int(getenv("F1_POLL_IDLE_SEC", "1800") or "1800")
POLL_RACE_SEC = int(getenv("F1_POLL_RACE_SEC", "600") or "600")
