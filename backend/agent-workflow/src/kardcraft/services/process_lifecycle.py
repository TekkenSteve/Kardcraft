"""Process lifecycle gate for coordinated quiesce/drain shutdown."""

from __future__ import annotations

import asyncio
from typing import Final


PHASE_RUNNING: Final[str] = "running"
PHASE_QUIESCING: Final[str] = "quiescing"
PHASE_DRAINING: Final[str] = "draining"
PHASE_STOPPED: Final[str] = "stopped"


class ProcessLifecycleGate:
    """Tracks process phase and in-flight event writes for graceful shutdown."""

    def __init__(self) -> None:
        self._phase = PHASE_RUNNING
        self._inflight = 0
        self._lock = asyncio.Lock()
        self._drained = asyncio.Event()
        self._drained.set()

    @property
    def phase(self) -> str:
        return self._phase

    async def begin_quiesce(self) -> None:
        async with self._lock:
            if self._phase == PHASE_RUNNING:
                self._phase = PHASE_QUIESCING

    async def begin_draining(self) -> None:
        async with self._lock:
            if self._phase in {PHASE_RUNNING, PHASE_QUIESCING}:
                self._phase = PHASE_DRAINING

    async def mark_stopped(self) -> None:
        async with self._lock:
            self._phase = PHASE_STOPPED

    async def try_acquire_publish_slot(self, channel: str) -> bool:
        # Strict rule: once quiescing starts, disallow all new realtime event writes.
        async with self._lock:
            if self._phase != PHASE_RUNNING:
                return False
            self._inflight += 1
            if self._inflight == 1:
                self._drained.clear()
            return True

    async def release_publish_slot(self) -> None:
        async with self._lock:
            if self._inflight > 0:
                self._inflight -= 1
            if self._inflight == 0:
                self._drained.set()

    async def drain(self, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._drained.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False
