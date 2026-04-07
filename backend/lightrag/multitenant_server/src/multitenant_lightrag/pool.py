from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from .backends import BackendClient, BackendFactory
from .config import Settings


@dataclass
class WorkspaceState:
    queue: asyncio.Queue[BackendClient]
    created_clients: int = 0
    last_used_monotonic: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WorkspaceClientPool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._factory = BackendFactory(settings)
        self._states: dict[str, WorkspaceState] = {}
        self._states_lock = asyncio.Lock()
        self._global_semaphore = asyncio.Semaphore(settings.global_max_inflight)
        self._workspace_semaphores: dict[str, asyncio.Semaphore] = {}

    async def close_all(self) -> None:
        async with self._states_lock:
            states = list(self._states.values())
            self._states.clear()
            self._workspace_semaphores.clear()

        for state in states:
            while not state.queue.empty():
                client = state.queue.get_nowait()
                await client.aclose()
        await self._factory.shutdown()

    @asynccontextmanager
    async def acquire(self, workspace: str) -> AsyncIterator[BackendClient]:
        semaphore = await self._get_workspace_semaphore(workspace)

        async with self._global_semaphore:
            async with semaphore:
                state = await self._get_or_create_state(workspace)
                client = await self._borrow_client(workspace, state)
                try:
                    yield client
                finally:
                    await self._recycle_client(state, client)

    async def _get_workspace_semaphore(self, workspace: str) -> asyncio.Semaphore:
        async with self._states_lock:
            semaphore = self._workspace_semaphores.get(workspace)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self._settings.per_workspace_max_inflight)
                self._workspace_semaphores[workspace] = semaphore
            return semaphore

    async def _get_or_create_state(self, workspace: str) -> WorkspaceState:
        while True:
            evicted: tuple[str, WorkspaceState] | None = None

            async with self._states_lock:
                state = self._states.get(workspace)
                if state is not None:
                    state.last_used_monotonic = time.monotonic()
                    return state

                if len(self._states) >= self._settings.max_workspace_count:
                    evicted = self._evict_one_idle_workspace_locked()
                    if evicted is None:
                        raise RuntimeError(
                            f"max workspace count ({self._settings.max_workspace_count}) reached "
                            "and no idle workspaces available for eviction"
                        )
                else:
                    state = WorkspaceState(queue=asyncio.Queue(self._settings.pool_size_per_workspace))
                    self._states[workspace] = state
                    state.last_used_monotonic = time.monotonic()
                    return state

            assert evicted is not None
            await self._cleanup_evicted_state(*evicted)

    def _evict_one_idle_workspace_locked(self) -> tuple[str, WorkspaceState] | None:
        if not self._states:
            return None

        now = time.monotonic()
        ttl = self._settings.workspace_idle_ttl_sec
        candidates = [
            (name, st)
            for name, st in self._states.items()
            if now - st.last_used_monotonic >= ttl
        ]
        if not candidates:
            return None

        name, state = min(candidates, key=lambda item: item[1].last_used_monotonic)
        self._states.pop(name, None)
        self._workspace_semaphores.pop(name, None)
        return name, state

    async def _cleanup_evicted_state(self, name: str, state: WorkspaceState) -> None:
        while not state.queue.empty():
            client = state.queue.get_nowait()
            await client.aclose()
        await self._factory.on_workspace_evicted(name)

    async def _borrow_client(self, workspace: str, state: WorkspaceState) -> BackendClient:
        async with state.lock:
            state.last_used_monotonic = time.monotonic()

            if not state.queue.empty():
                return state.queue.get_nowait()

            if state.created_clients < self._settings.pool_size_per_workspace:
                client = self._factory.create(workspace)
                state.created_clients += 1
                return client

        return await asyncio.wait_for(
            state.queue.get(), timeout=self._settings.borrow_timeout_sec
        )

    async def _recycle_client(self, state: WorkspaceState, client: BackendClient) -> None:
        state.last_used_monotonic = time.monotonic()
        try:
            state.queue.put_nowait(client)
        except asyncio.QueueFull:
            await client.aclose()
            async with state.lock:
                state.created_clients = max(0, state.created_clients - 1)

    async def stats(self) -> dict:
        async with self._states_lock:
            workspaces = {}
            for name, state in self._states.items():
                workspaces[name] = {
                    "created_clients": state.created_clients,
                    "idle_clients": state.queue.qsize(),
                    "last_used_monotonic": state.last_used_monotonic,
                }

            payload = {
                "workspace_count": len(self._states),
                "pool_size_per_workspace": self._settings.pool_size_per_workspace,
                "max_workspace_count": self._settings.max_workspace_count,
                "global_max_inflight": self._settings.global_max_inflight,
                "per_workspace_max_inflight": self._settings.per_workspace_max_inflight,
                "workspaces": workspaces,
            }
        payload["runtime"] = await self._factory.stats()
        return payload
