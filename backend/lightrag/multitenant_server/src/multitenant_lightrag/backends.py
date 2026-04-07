from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import socket
import time
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class BackendClient(Protocol):
    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        ...

    def request_stream(self, method: str, path: str, **kwargs: Any) -> AbstractAsyncContextManager:
        ...

    async def aclose(self) -> None:
        ...


@dataclass
class WorkspaceRuntime:
    workspace: str
    port: int
    process: asyncio.subprocess.Process
    client: httpx.AsyncClient
    last_used: float
    active_streams: int = 0


class WorkspaceRuntimeRegistry:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = asyncio.Lock()
        self._next_port = settings.process_base_port
        self._runtimes: dict[str, WorkspaceRuntime] = {}
        self._starting: dict[str, asyncio.Task[WorkspaceRuntime]] = {}

    async def ensure_runtime(self, workspace: str) -> WorkspaceRuntime:
        runtime_to_shutdown: WorkspaceRuntime | None = None

        while True:
            start_task: asyncio.Task[WorkspaceRuntime] | None = None
            task_owned_by_this_call = False

            async with self._lock:
                runtime = self._runtimes.get(workspace)
                if runtime is not None and runtime.process.returncode is None:
                    runtime.last_used = time.monotonic()
                    return runtime

                if runtime is not None:
                    self._runtimes.pop(workspace, None)
                    runtime_to_shutdown = runtime

                start_task = self._starting.get(workspace)
                if start_task is None:
                    start_task = asyncio.create_task(self._start_runtime(workspace))
                    self._starting[workspace] = start_task
                    task_owned_by_this_call = True

            if runtime_to_shutdown is not None:
                await self._shutdown_runtime(runtime_to_shutdown)
                runtime_to_shutdown = None

            assert start_task is not None

            if task_owned_by_this_call:
                try:
                    runtime = await start_task
                finally:
                    async with self._lock:
                        if self._starting.get(workspace) is start_task:
                            self._starting.pop(workspace, None)
                async with self._lock:
                    current = self._runtimes.get(workspace)
                    if current is None or current.process.returncode is not None:
                        self._runtimes[workspace] = runtime
                    else:
                        runtime = current
                runtime.last_used = time.monotonic()
                return runtime

            try:
                runtime = await start_task
            except Exception:
                async with self._lock:
                    if self._starting.get(workspace) is start_task:
                        self._starting.pop(workspace, None)
                continue

            runtime.last_used = time.monotonic()
            return runtime

    async def close_workspace(
        self,
        workspace: str,
        *,
        purge_data: bool = False,
        delete_workspace_dir: bool = False,
    ) -> None:
        async with self._lock:
            runtime = self._runtimes.pop(workspace, None)
            start_task = self._starting.pop(workspace, None)

        if start_task is not None:
            start_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await start_task

        if purge_data:
            await self._purge_workspace_data(workspace=workspace, runtime=runtime)

        if runtime is not None:
            await self._shutdown_runtime(runtime)

        if delete_workspace_dir:
            self._delete_workspace_dir(workspace)

    async def close_all(self) -> None:
        async with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
            starting_tasks = list(self._starting.values())
            self._starting.clear()

        for task in starting_tasks:
            task.cancel()
        if starting_tasks:
            await asyncio.gather(*starting_tasks, return_exceptions=True)

        for runtime in runtimes:
            await self._shutdown_runtime(runtime)

    async def stats(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "runtime_count": len(self._runtimes),
                "runtimes": {
                    workspace: {
                        "port": rt.port,
                        "alive": rt.process.returncode is None,
                        "active_streams": rt.active_streams,
                        "last_used": rt.last_used,
                    }
                    for workspace, rt in self._runtimes.items()
                },
                "starting_workspaces": sorted(self._starting.keys()),
            }

    async def _start_runtime(self, workspace: str) -> WorkspaceRuntime:
        ws_root = Path(self._settings.workspaces_root) / workspace
        working_dir = ws_root / "rag_storage"
        input_dir = ws_root / "inputs"
        working_dir.mkdir(parents=True, exist_ok=True)
        input_dir.mkdir(parents=True, exist_ok=True)

        port = self._pick_free_port()
        env = self._build_runtime_env()

        cmd = [
            self._settings.process_cmd,
            "--host",
            self._settings.process_bind_host,
            "--port",
            str(port),
            "--working-dir",
            str(working_dir),
            "--input-dir",
            str(input_dir),
            "--workspace",
            workspace,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        headers: dict[str, str] = {}
        if self._settings.api_key:
            headers["X-API-Key"] = self._settings.api_key

        client = httpx.AsyncClient(
            base_url=f"http://{self._settings.process_bind_host}:{port}",
            timeout=self._settings.upstream_timeout_sec,
            headers=headers,
        )

        ok = await self._wait_healthy(
            client=client,
            process=process,
            timeout_sec=self._settings.process_startup_timeout_sec,
        )
        if not ok:
            await client.aclose()
            if process.returncode is None:
                process.terminate()
            raise RuntimeError(
                f"workspace runtime startup timeout: workspace={workspace} port={port}"
            )

        return WorkspaceRuntime(
            workspace=workspace,
            port=port,
            process=process,
            client=client,
            last_used=time.monotonic(),
        )

    async def _shutdown_runtime(self, runtime: WorkspaceRuntime) -> None:
        await runtime.client.aclose()
        if runtime.process.returncode is None:
            runtime.process.terminate()
            try:
                await asyncio.wait_for(runtime.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                runtime.process.kill()

    async def _purge_workspace_data(
        self,
        workspace: str,
        runtime: WorkspaceRuntime | None,
    ) -> None:
        active_runtime = runtime
        started_temp_runtime = False

        if active_runtime is None or active_runtime.process.returncode is not None:
            try:
                active_runtime = await self._start_runtime(workspace)
                started_temp_runtime = True
            except Exception as exc:
                logger.warning(
                    "workspace purge skipped: cannot start runtime workspace=%s err=%s",
                    workspace,
                    exc,
                )
                return

        assert active_runtime is not None
        try:
            response = await active_runtime.client.request(
                method="DELETE",
                url="/documents",
                timeout=self._settings.upstream_timeout_sec,
            )
            if response.status_code >= 400:
                logger.warning(
                    "workspace purge returned non-2xx workspace=%s status=%s body=%s",
                    workspace,
                    response.status_code,
                    response.text[:300],
                )
        except Exception as exc:
            logger.warning(
                "workspace purge request failed workspace=%s err=%s",
                workspace,
                exc,
            )
        finally:
            if started_temp_runtime:
                await self._shutdown_runtime(active_runtime)

    def _delete_workspace_dir(self, workspace: str) -> None:
        try:
            root = Path(self._settings.workspaces_root).resolve()
            target = (root / workspace).resolve()
            if target == root or root not in target.parents:
                logger.warning(
                    "workspace dir delete skipped due to unsafe path workspace=%s target=%s",
                    workspace,
                    target,
                )
                return
            if target.exists():
                shutil.rmtree(target)
        except Exception as exc:
            logger.warning(
                "workspace dir delete failed workspace=%s err=%s",
                workspace,
                exc,
            )

    async def _wait_healthy(
        self,
        client: httpx.AsyncClient,
        process: asyncio.subprocess.Process,
        timeout_sec: float,
    ) -> bool:
        deadline = time.monotonic() + timeout_sec
        probe_timeout = min(2.0, timeout_sec)
        while time.monotonic() < deadline:
            if process.returncode is not None:
                return False
            try:
                response = await client.get("/health", timeout=probe_timeout)
                if response.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        return False

    def _build_runtime_env(self) -> dict[str, str]:
        env_from_file = self._read_env_file(self._settings.template_env_file)
        env = dict(env_from_file)
        env.update(os.environ)
        return env

    @staticmethod
    def _read_env_file(path: str) -> dict[str, str]:
        file_path = Path(path)
        if not file_path.exists():
            return {}

        # Use dotenv parser for compatibility with official LightRAG env syntax.
        try:
            from dotenv import dotenv_values

            parsed = dotenv_values(file_path)
            return {str(k): str(v) for k, v in parsed.items() if k and v is not None}
        except Exception:
            # Fallback parser keeps service resilient when dotenv is unavailable.
            out: dict[str, str] = {}
            for raw in file_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                out[key.strip()] = val.strip().strip('"').strip("'")
            return out

    def _pick_free_port(self) -> int:
        for _ in range(200):
            port = self._next_port
            self._next_port += 1
            if self._port_available(port):
                return port
        raise RuntimeError("cannot allocate free port for workspace runtime")

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.connect_ex(("127.0.0.1", port)) != 0


class WorkspaceBackendClient:
    def __init__(self, registry: WorkspaceRuntimeRegistry, workspace: str):
        self._registry = registry
        self._workspace = workspace

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        runtime = await self._registry.ensure_runtime(self._workspace)
        runtime.last_used = time.monotonic()
        return await runtime.client.request(method=method, url=path, **kwargs)

    def request_stream(self, method: str, path: str, **kwargs: Any) -> AbstractAsyncContextManager:
        return _WorkspaceStreamContext(
            registry=self._registry,
            workspace=self._workspace,
            method=method,
            path=path,
            kwargs=kwargs,
        )

    async def aclose(self) -> None:
        return None


class _WorkspaceStreamContext:
    def __init__(self, registry: WorkspaceRuntimeRegistry, workspace: str, method: str, path: str, kwargs: dict[str, Any]):
        self._registry = registry
        self._workspace = workspace
        self._method = method
        self._path = path
        self._kwargs = kwargs
        self._runtime: WorkspaceRuntime | None = None
        self._inner_cm: Any = None

    async def __aenter__(self):
        runtime = await self._registry.ensure_runtime(self._workspace)
        runtime.active_streams += 1
        runtime.last_used = time.monotonic()
        self._runtime = runtime

        self._inner_cm = runtime.client.stream(method=self._method, url=self._path, **self._kwargs)
        return await self._inner_cm.__aenter__()

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._inner_cm is None:
                return False
            return await self._inner_cm.__aexit__(exc_type, exc, tb)
        finally:
            if self._runtime is not None:
                self._runtime.active_streams = max(0, self._runtime.active_streams - 1)
                self._runtime.last_used = time.monotonic()


class BackendFactory:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._registry = WorkspaceRuntimeRegistry(settings)

    def create(self, workspace: str) -> BackendClient:
        return WorkspaceBackendClient(self._registry, workspace)

    async def on_workspace_evicted(self, workspace: str) -> None:
        await self._registry.close_workspace(
            workspace,
            purge_data=self._settings.purge_data_on_evict,
            delete_workspace_dir=self._settings.delete_workspace_dir_on_evict,
        )

    async def shutdown(self) -> None:
        await self._registry.close_all()

    async def stats(self) -> dict[str, Any]:
        return await self._registry.stats()
