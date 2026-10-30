"""Application configuration and environment validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Immutable runtime settings."""

    api_id: int
    api_hash: str
    bot_token: str
    session_string: str
    admin_id: Optional[int]
    max_duration: int = 600
    max_threads: int = 100
    scan_limit: int = 50
    scan_cooldown_seconds: int = 10
    log_file: str = "bot.log"

    @classmethod
    def from_env(cls) -> "Config":
        required = {
            "API_ID": os.getenv("API_ID"),
            "API_HASH": os.getenv("API_HASH"),
            "BOT_TOKEN": os.getenv("BOT_TOKEN"),
            "SESSION_STRING": os.getenv("SESSION_STRING"),
        }

        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        max_duration = min(int(os.getenv("MAX_DURATION", "600")), 600)
        max_threads = min(int(os.getenv("MAX_THREADS", "100")), 100)
        scan_limit = max(1, min(int(os.getenv("SCAN_LIMIT", "50")), 50))

        return cls(
            api_id=int(required["API_ID"]),
            api_hash=str(required["API_HASH"]),
            bot_token=str(required["BOT_TOKEN"]),
            session_string=str(required["SESSION_STRING"]),
            admin_id=int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None,
            max_duration=max_duration,
            max_threads=max_threads,
            scan_limit=scan_limit,
        )
