"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Entry Point"""

from __future__ import annotations

import asyncio
import logging
import sys

from pyrogram import Client

from config import Config
from bot_handler import register

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass


def setup_logging(log_file: str) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def main() -> None:
    cfg = Config.from_env()
    setup_logging(cfg.log_file)
    log = logging.getLogger("main")

    bot = Client(
        "miss_chutki",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
    )

    register(bot, cfg)

    log.info(f"ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ starting — max_threads={cfg.max_threads} max_dur={cfg.max_duration}s")
    await bot.start()
    log.info("Bot online. Polling…")

    try:
        await asyncio.Event().wait()   # run forever
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await bot.stop()
        log.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
