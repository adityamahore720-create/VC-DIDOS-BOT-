"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Entry Point"""

from __future__ import annotations

import asyncio
import logging
import sys

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from pyrogram import Client, idle

from config import Config
from bot_handler import register


def setup_logging() -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


async def main() -> None:
    setup_logging()
    log = logging.getLogger("main")

    # ── config ─────────────────────────────────────────────────────────────────
    try:
        cfg = Config.from_env()
    except ValueError as exc:
        log.critical(f"❌ Config error: {exc}")
        log.critical("Set API_ID, API_HASH, BOT_TOKEN in Render → Environment tab")
        sys.exit(1)

    log.info(f"Config OK | threads={cfg.max_threads} | max_dur={cfg.max_duration}s")

    # ── client ─────────────────────────────────────────────────────────────────
    bot = Client(
        name="miss_chutki",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
        workdir="/tmp",          # writable on Render's ephemeral FS
        no_updates=False,
    )

    register(bot, cfg)

    # ── start ──────────────────────────────────────────────────────────────────
    log.info("Starting bot…")
    await bot.start()
    me = await bot.get_me()
    log.info(f"✅ Online as @{me.username} (id={me.id})")

    # ── keep alive ─────────────────────────────────────────────────────────────
    # pyrogram.idle() blocks until SIGINT/SIGTERM — correct for Render workers
    await idle()

    # ── shutdown ───────────────────────────────────────────────────────────────
    log.info("Shutting down…")
    await bot.stop()
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
