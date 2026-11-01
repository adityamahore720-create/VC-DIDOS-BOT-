"""Fixed VC detector — proper FloodWait handling, no crashes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import time
import ipaddress
from dataclasses import dataclass
from typing import Any, Optional, List, Set

from pyrogram import Client
from pyrogram.errors import BadRequest, ChatAdminRequired, FloodWait, UserAlreadyParticipant
from pyrogram.raw import functions, types

LOGGER = logging.getLogger(__name__)


@dataclass
class VCRecord:
    dialog_id: int
    title: str
    peer: Any
    call: Any
    chat_id: int


@dataclass
class VCConnectionInfo:
    ip: str
    port: int
    type: str
    region: str
    raw_endpoint: str
    source: str


class VCDetector:
    def __init__(self, user_client: Client, scan_cooldown_seconds: int = 10) -> None:
        self.user_client = user_client
        self.scan_cooldown_seconds = scan_cooldown_seconds
        self._last_scan = 0.0

    async def scan_active_voice_chats(self, limit: int = 50) -> list[VCRecord]:
        now = time.time()
        wait_remaining = self.scan_cooldown_seconds - (now - self._last_scan)
        if wait_remaining > 0:
            await asyncio.sleep(wait_remaining)

        self._last_scan = time.time()
        results: list[VCRecord] = []
        dialogs = []

        # Fetch dialogs with FloodWait handling
        try:
            async for dialog in self.user_client.get_dialogs(limit=limit):
                dialogs.append(dialog)
        except FloodWait as e:
            LOGGER.warning("FloodWait on get_dialogs: %ss — waiting", e.value)
            await asyncio.sleep(e.value + 2)
            try:
                async for dialog in self.user_client.get_dialogs(limit=limit):
                    dialogs.append(dialog)
            except Exception as exc:
                LOGGER.error("get_dialogs retry failed: %s", exc)
                return results
        except Exception as exc:
            LOGGER.error("get_dialogs failed: %s", exc)
            return results

        for dialog in dialogs:
            chat = dialog.chat
            if not chat or not chat.title:
                continue
            try:
                peer = await self._safe_resolve(chat.id)
                if not peer:
                    continue
                call = await self._extract_call(peer)
                if call:
                    results.append(VCRecord(
                        dialog_id=chat.id,
                        title=chat.title or str(chat.id),
                        peer=peer,
                        call=call,
                        chat_id=chat.id
                    ))
            except Exception as exc:
                LOGGER.debug("Skipping %s: %s", chat.id, exc)

        return results

    async def _safe_resolve(self, chat_id: int, retries: int = 3) -> Optional[Any]:
        for attempt in range(retries):
            try:
                return await self.user_client.resolve_peer(chat_id)
            except FloodWait as e:
                LOGGER.warning("FloodWait resolve_peer %ss", e.value)
                await asyncio.sleep(e.value + 1)
            except Exception as exc:
                LOGGER.debug("resolve_peer failed: %s", exc)
                return None
        return None

    async def _extract_call(self, peer: Any) -> Optional[Any]:
        try:
            if isinstance(peer, types.InputPeerChannel):
                full = await self.user_client.invoke(
                    functions.channels.GetFullChannel(
                        channel=types.InputChannel(
                            channel_id=peer.channel_id,
                            access_hash=peer.access_hash
                        )
                    )
                )
                return getattr(full.full_chat, "call", None)

            if isinstance(peer, types.InputPeerChat):
                full = await self.user_client.invoke(
                    functions.messages.GetFullChat(chat_id=peer.chat_id)
                )
                return getattr(full.full_chat, "call", None)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
        except Exception:
            pass
        return None

    async def join_and_extract_metadata(self, record: VCRecord) -> dict:
        joined = False
        notice: Optional[str] = None

        try:
            await self.user_client.invoke(
                functions.phone.JoinGroupCall(
                    call=types.InputGroupCall(
                        id=record.call.id,
                        access_hash=record.call.access_hash
                    ),
                    join_as=record.peer,
                    params=types.DataJSON(data=json.dumps({
                        "ufrag": "vc_detector",
                        "pwd": "vc_test_123",
                        "fingerprints": [],
                        "ssrc": 11111111
                    })),
                    muted=True,
                    video_stopped=True,
                    invite_hash=None,
                )
            )
            joined = True
            await asyncio.sleep(2)
        except UserAlreadyParticipant:
            joined = True
        except (ChatAdminRequired, BadRequest) as exc:
            notice = f"Join blocked: {exc}"
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            notice = "FloodWait during join — manual join required"
        except Exception as exc:
            notice = f"Join failed: {exc}"

        # Fetch group call info
        try:
            group_call = await self.user_client.invoke(
                functions.phone.GetGroupCall(
                    call=types.InputGroupCall(
                        id=record.call.id,
                        access_hash=record.call.access_hash
                    ),
                    limit=100,
                )
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            group_call = await self.user_client.invoke(
                functions.phone.GetGroupCall(
                    call=types.InputGroupCall(
                        id=record.call.id,
                        access_hash=record.call.access_hash
                    ),
                    limit=100,
                )
            )

        call = group_call.call
        params_raw = getattr(call, "params", None)
        params_data = getattr(params_raw, "data", "{}") if params_raw else "{}"

        try:
            parsed = json.loads(params_data)
        except json.JSONDecodeError:
            parsed = {"raw": params_data}

        extracted_ips: List[VCConnectionInfo] = []
        seen: Set[str] = set()

        def add_ip(info: VCConnectionInfo) -> None:
            key = f"{info.ip}:{info.port}"
            if key not in seen and info.ip:
                seen.add(key)
                extracted_ips.append(info)

        # From endpoints
        for ep in (parsed.get("endpoints", []) if isinstance(parsed, dict) else []):
            info = self._parse_endpoint(ep, "endpoints")
            if info:
                add_ip(info)

        # From servers list
        if isinstance(parsed, dict):
            for srv in parsed.get("servers", []):
                if isinstance(srv, dict):
                    ip = srv.get("ip") or srv.get("host") or srv.get("address")
                    port = srv.get("port", 0)
                    if ip:
                        add_ip(VCConnectionInfo(
                            ip=ip, port=port,
                            type=srv.get("type", "relay"),
                            region=srv.get("region", "unknown"),
                            raw_endpoint=f"{ip}:{port}",
                            source="servers"
                        ))

        # Deep IP extraction from raw params
        if isinstance(parsed, dict):
            params_str = json.dumps(parsed)
            ipv4_pat = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
            for ip in re.findall(ipv4_pat, params_str):
                if not self._is_private_ip(ip):
                    add_ip(VCConnectionInfo(
                        ip=ip, port=0, type="extracted_public",
                        region="unknown", raw_endpoint=ip,
                        source="deep_extraction"
                    ))

        participants = getattr(group_call, "participants", [])

        return {
            "title": record.title,
            "call_id": record.call.id,
            "chat_id": record.chat_id,
            "params": parsed,
            "extracted_ips": [
                {"ip": x.ip, "port": x.port, "type": x.type,
                 "region": x.region, "source": x.source}
                for x in extracted_ips
            ],
            "joined": joined,
            "notice": notice,
            "participants_count": len(participants) if participants else 0,
        }

    def _parse_endpoint(self, endpoint: str, source: str = "unknown") -> Optional[VCConnectionInfo]:
        if not endpoint:
            return None
        if ":" in endpoint:
            parts = endpoint.rsplit(":", 1)
            if len(parts) == 2:
                ip, port_str = parts
                try:
                    port = int(port_str)
                    if self._is_valid_ip(ip):
                        return VCConnectionInfo(
                            ip=ip, port=port, type="direct",
                            region="auto", raw_endpoint=endpoint,
                            source=source
                        )
                except (ValueError, TypeError):
                    pass
        if self._is_valid_ip(endpoint):
            return VCConnectionInfo(
                ip=endpoint, port=0, type="ip_only",
                region="unknown", raw_endpoint=endpoint,
                source=source
            )
        return None

    def _is_valid_ip(self, ip: str) -> bool:
        if not ip or not isinstance(ip, str):
            return False
        try:
            socket.inet_aton(ip)
            return True
        except socket.error:
            return False

    def _is_private_ip(self, ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    async def leave_call(self, record: VCRecord) -> None:
        try:
            await self.user_client.invoke(
                functions.phone.LeaveGroupCall(
                    call=types.InputGroupCall(
                        id=record.call.id,
                        access_hash=record.call.access_hash
                    ),
                    source=0
                )
            )
            LOGGER.info("Left VC: %s", record.title)
        except Exception as exc:
            LOGGER.warning("Leave error: %s", exc)
