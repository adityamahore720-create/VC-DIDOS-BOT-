"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Configuration"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    admin_id: Optional[int]
    max_duration: int = 600
    max_threads: int = 100
    log_file: str = "bot.log"

    @classmethod
    def from_env(cls) -> "Config":
        required = {
            "API_ID":    os.getenv("API_ID"),
            "API_HASH":  os.getenv("API_HASH"),
            "BOT_TOKEN": os.getenv("BOT_TOKEN"),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing env vars: {', '.join(missing)}")

        return cls(
            api_id=int(required["API_ID"]),
            api_hash=str(required["API_HASH"]),
            bot_token=str(required["BOT_TOKEN"]),
            admin_id=int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None,
            max_duration=min(int(os.getenv("MAX_DURATION", "600")), 600),
            max_threads=min(int(os.getenv("MAX_THREADS", "100")), 500),
        )
