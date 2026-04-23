from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator
import logging

from .backends import BackendClient, BackendFactory
from .config import Settings
from .policy import StrictLRUPolicy, WorkspaceEvictionPolicy


@dataclass
class WorkspaceState:
    queue: asyncio.Queue[BackendClient]
    created_clients: int = 0
    checked_out_clients: int = 0
    last_used_monotonic: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    evicted: bool = False
    runtime_cleanup_done: bool = False


class WorkspaceClientPool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._factory = BackendFactory(settings)
        self._states: dict[str, WorkspaceState] = {}
        self._policy: WorkspaceEvictionPolicy = StrictLRUPolicy(settings.max_workspace_count)
        self._states_lock = asyncio.Lock()
        self._global_semaphore = asyncio.Semaphore(settings.global_max_inflight)
        self._workspace_semaphores: dict[str, asyncio.Semaphore] = {}

    async def close_all(self) -> None:
        async with self._states_lock:
            states = list(self._states.values())
            self._states.clear()
            self._policy.clear()
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
                    await self._recycle_client(workspace, state, client)

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
            admitted_state: WorkspaceState | None = None

            async with self._states_lock:
                state = self._states.get(workspace)
                if state is not None:
                    self._touch_state_locked(workspace, state)
                    return state

                victim = self._policy.admit(workspace)
                if victim is not None:
                    evicted_state = self._states.pop(victim, None)
                    self._workspace_semaphores.pop(victim, None)
                    if evicted_state is None:
                        self._policy.remove(workspace)
                        raise RuntimeError(f"eviction policy/state desync for workspace={victim}")
                    evicted_state.evicted = True
                    evicted = (victim, evicted_state)
                    logger.warning(
                        "workspace_evicted",
                        extra={
                            "workspace": victim,
                            "admitted_workspace": workspace,
                            "max_workspace_count": self._settings.max_workspace_count,
                        },
                    )

                state = WorkspaceState(queue=asyncio.Queue(self._settings.pool_size_per_workspace))
                self._states[workspace] = state
                state.last_used_monotonic = time.monotonic()
                admitted_state = state

            if evicted is not None:
                await self._cleanup_evicted_state(*evicted)
            assert admitted_state is not None
            return admitted_state

    def _touch_state_locked(self, workspace: str, state: WorkspaceState) -> None:
        state.last_used_monotonic = time.monotonic()
        self._policy.touch(workspace)

    async def _cleanup_evicted_state(self, name: str, state: WorkspaceState) -> None:
        closed_idle_clients = 0
        while not state.queue.empty():
            client = state.queue.get_nowait()
            await client.aclose()
            closed_idle_clients += 1

        run_runtime_cleanup = False
        async with state.lock:
            state.created_clients = max(0, state.created_clients - closed_idle_clients)
            if state.checked_out_clients == 0 and not state.runtime_cleanup_done:
                state.runtime_cleanup_done = True
                run_runtime_cleanup = True

        if run_runtime_cleanup:
            await self._factory.on_workspace_evicted(name)
        logger.info(
            "workspace_cleanup_complete",
            extra={
                "workspace": name,
                "closed_idle_clients": closed_idle_clients,
                "checked_out_clients": state.checked_out_clients,
                "runtime_cleanup_done": run_runtime_cleanup,
            },
        )

    async def _borrow_client(self, workspace: str, state: WorkspaceState) -> BackendClient:
        async with state.lock:
            if not state.queue.empty():
                client = state.queue.get_nowait()
                state.checked_out_clients += 1
                await self._touch_workspace(workspace)
                return client

            if state.created_clients < self._settings.pool_size_per_workspace:
                client = self._factory.create(workspace)
                state.created_clients += 1
                state.checked_out_clients += 1
                await self._touch_workspace(workspace)
                return client

        try:
            client = await asyncio.wait_for(
                state.queue.get(), timeout=self._settings.borrow_timeout_sec
            )
        except TimeoutError:
            logger.error(
                "workspace_pool_borrow_timeout",
                extra={
                    "workspace": workspace,
                    "borrow_timeout_sec": self._settings.borrow_timeout_sec,
                    "created_clients": state.created_clients,
                    "checked_out_clients": state.checked_out_clients,
                    "idle_clients": state.queue.qsize(),
                },
            )
            raise
        async with state.lock:
            state.checked_out_clients += 1
        await self._touch_workspace(workspace)
        return client

    async def _recycle_client(self, workspace: str, state: WorkspaceState, client: BackendClient) -> None:
        close_now = False
        run_runtime_cleanup = False
        async with state.lock:
            state.checked_out_clients = max(0, state.checked_out_clients - 1)
            if state.evicted:
                close_now = True
                state.created_clients = max(0, state.created_clients - 1)
                if state.checked_out_clients == 0 and not state.runtime_cleanup_done:
                    state.runtime_cleanup_done = True
                    run_runtime_cleanup = True

        if close_now:
            await client.aclose()
            if run_runtime_cleanup:
                await self._factory.on_workspace_evicted(workspace)
            return

        await self._touch_workspace(workspace)
        try:
            state.queue.put_nowait(client)
        except asyncio.QueueFull:
            await client.aclose()
            async with state.lock:
                state.created_clients = max(0, state.created_clients - 1)

    async def _touch_workspace(self, workspace: str) -> None:
        async with self._states_lock:
            state = self._states.get(workspace)
            if state is None:
                return
            self._touch_state_locked(workspace, state)

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
logger = logging.getLogger(__name__)
