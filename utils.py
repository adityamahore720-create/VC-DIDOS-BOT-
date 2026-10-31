"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Utilities"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{value} B"


def resolve_hostname(host: str) -> Optional[str]:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def is_valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def is_valid_port(port: int) -> bool:
    return 1 <= port <= 65535
