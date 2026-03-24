"""Shell execution engine with mode-based runtime routing."""

from __future__ import annotations

import asyncio
from collections import deque
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import grpc

from kardcraft.config import Config
from kardcraft.sandbox_broker.client import SandboxBrokerClient

ShellExecutionMode = Literal["auto", "sandbox", "local"]


@dataclass(frozen=True)
class ShellExecutionRequest:
    workspace_id: str
    command: str
    tool_call_id: str
    timeout_seconds: int
    env: dict[str, str]
    cwd: str
    max_output_bytes: int


@dataclass(frozen=True)
class PythonExecutionRequest:
    workspace_id: str
    code: str
    tool_call_id: str
    timeout_seconds: int
    env: dict[str, str]
    cwd: str
    max_output_bytes: int
    language: str = "python"


@dataclass(frozen=True)
class RawExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    success: bool


@dataclass(frozen=True)
class ExecutionOutcome:
    content: str
    status: Literal["success", "error"]
    runtime: Literal["sandbox", "local", "degraded-local"]
    exit_code: int
    fallback_reason: str | None = None


@runtime_checkable
class ExecutionPort(Protocol):
    async def execute_shell(self, request: ShellExecutionRequest) -> ExecutionOutcome: ...
    async def execute_python(self, request: PythonExecutionRequest) -> ExecutionOutcome: ...


class AdapterFailure(Exception):
    def __init__(self, *, reason: str, degradable: bool, message: str):
        super().__init__(message)
        self.reason = reason
        self.degradable = degradable
        self.message = message

    def __str__(self) -> str:
        return self.message


class SandboxExecutor:
    def __init__(self, broker_client: SandboxBrokerClient):
        self._broker_client = broker_client

    async def execute(self, request: ShellExecutionRequest) -> RawExecutionResult:
        return await self.execute_shell(request)

    async def execute_shell(self, request: ShellExecutionRequest) -> RawExecutionResult:
        command = _with_cwd(request.command, request.cwd)
        try:
            resp = await self._broker_client.execute_command(
                workspace_id=request.workspace_id,
                task_id=request.tool_call_id,
                user_id="agent-skills",
                tool_name="shell",
                workflow_type="shell-tool",
                command=command,
                env=request.env,
                policy_profile="shell-tool-default",
                timeout_seconds=request.timeout_seconds,
                allow_network=False,
            )
        except grpc.aio.AioRpcError as exc:
            code = exc.code()
            if code == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise AdapterFailure(
                    reason="broker_timeout",
                    degradable=True,
                    message=f"sandbox broker timeout: {exc.details() or code.name}",
                ) from exc
            if code == grpc.StatusCode.UNAVAILABLE:
                raise AdapterFailure(
                    reason="broker_unreachable",
                    degradable=True,
                    message=f"sandbox broker unavailable: {exc.details() or code.name}",
                ) from exc
            raise AdapterFailure(
                reason="broker_internal_error",
                degradable=True,
                message=f"sandbox broker rpc error: {code.name}",
            ) from exc
        except TimeoutError as exc:
            raise AdapterFailure(
                reason="broker_timeout",
                degradable=True,
                message="sandbox broker timeout",
            ) from exc
        except Exception as exc:
            raise AdapterFailure(
                reason="broker_internal_error",
                degradable=True,
                message=f"sandbox broker error: {exc}",
            ) from exc

        if _is_policy_denied(resp):
            raise AdapterFailure(
                reason="policy_denied",
                degradable=False,
                message=_policy_message(resp),
            )

        return RawExecutionResult(
            stdout=str(getattr(resp, "stdout", "") or ""),
            stderr=str(getattr(resp, "stderr", "") or ""),
            exit_code=int(getattr(resp, "exit_code", 0) or 0),
            success=bool(getattr(resp, "success", False)),
        )

    async def execute_python(self, request: PythonExecutionRequest) -> RawExecutionResult:
        code = _with_cwd_python(request.code, request.cwd)
        try:
            resp = await self._broker_client.execute_python(
                workspace_id=request.workspace_id,
                task_id=request.tool_call_id,
                user_id="agent-skills",
                tool_name="python_exec",
                workflow_type="python-tool",
                code=code,
                language=request.language,
                inputs_json={},
                policy_profile="shell-tool-default",
                timeout_seconds=request.timeout_seconds,
                allow_network=False,
            )
        except grpc.aio.AioRpcError as exc:
            code_status = exc.code()
            if code_status == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise AdapterFailure(
                    reason="broker_timeout",
                    degradable=True,
                    message=f"sandbox broker timeout: {exc.details() or code_status.name}",
                ) from exc
            if code_status == grpc.StatusCode.UNAVAILABLE:
                raise AdapterFailure(
                    reason="broker_unreachable",
                    degradable=True,
                    message=f"sandbox broker unavailable: {exc.details() or code_status.name}",
                ) from exc
            raise AdapterFailure(
                reason="broker_internal_error",
                degradable=True,
                message=f"sandbox broker rpc error: {code_status.name}",
            ) from exc
        except TimeoutError as exc:
            raise AdapterFailure(
                reason="broker_timeout",
                degradable=True,
                message="sandbox broker timeout",
            ) from exc
        except Exception as exc:
            raise AdapterFailure(
                reason="broker_internal_error",
                degradable=True,
                message=f"sandbox broker error: {exc}",
            ) from exc

        if _is_policy_denied(resp):
            raise AdapterFailure(
                reason="policy_denied",
                degradable=False,
                message=_policy_message(resp),
            )

        return RawExecutionResult(
            stdout=str(getattr(resp, "stdout", "") or ""),
            stderr=str(getattr(resp, "stderr", "") or ""),
            exit_code=int(getattr(resp, "exit_code", 0) or 0),
            success=bool(getattr(resp, "success", False)),
        )


class LocalExecutor:
    async def execute(self, request: ShellExecutionRequest) -> RawExecutionResult:
        return await self.execute_shell(request)

    async def execute_shell(self, request: ShellExecutionRequest) -> RawExecutionResult:
        try:
            proc = subprocess.run(
                request.command,
                check=False,
                shell=True,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                env=request.env,
                cwd=request.cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterFailure(
                reason="local_timeout",
                degradable=False,
                message=f"command timed out after {request.timeout_seconds} seconds",
            ) from exc

        return RawExecutionResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=int(proc.returncode or 0),
            success=proc.returncode == 0,
        )

    async def execute_python(self, request: PythonExecutionRequest) -> RawExecutionResult:
        try:
            proc = subprocess.run(
                ["python3", "-c", request.code],
                check=False,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                env=request.env,
                cwd=request.cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterFailure(
                reason="local_timeout",
                degradable=False,
                message=f"command timed out after {request.timeout_seconds} seconds",
            ) from exc

        return RawExecutionResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=int(proc.returncode or 0),
            success=proc.returncode == 0,
        )


class ShellExecutionEngine(ExecutionPort):
    def __init__(
        self,
        *,
        config: Config | None = None,
        mode: ShellExecutionMode | None = None,
        sandbox_executor: SandboxExecutor | None = None,
        local_executor: LocalExecutor | None = None,
    ):
        resolved_config = config or Config()
        resolved_mode = mode or resolved_config.shell_execution_mode
        if resolved_mode not in ("auto", "sandbox", "local"):
            raise ValueError(
                "Invalid SHELL_EXECUTION_MODE. Expected one of: auto, sandbox, local."
            )

        self._mode: ShellExecutionMode = resolved_mode
        self._auto_degrade_max_per_minute = max(
            0, int(resolved_config.execution_auto_degrade_max_per_minute)
        )
        self._degrade_events: deque[float] = deque()
        self._degrade_lock = asyncio.Lock()
        self._sandbox_executor = sandbox_executor or SandboxExecutor(
            broker_client=SandboxBrokerClient.from_config(resolved_config)
        )
        self._local_executor = local_executor or LocalExecutor()

    async def execute_shell(self, request: ShellExecutionRequest) -> ExecutionOutcome:
        if self._mode == "local":
            result = await self._local_executor.execute(request)
            return _to_outcome(result, runtime="local", max_output_bytes=request.max_output_bytes)

        if self._mode == "sandbox":
            try:
                result = await self._sandbox_executor.execute(request)
                return _to_outcome(
                    result, runtime="sandbox", max_output_bytes=request.max_output_bytes
                )
            except AdapterFailure as exc:
                return _error_outcome(
                    message=exc.message,
                    runtime="sandbox",
                    max_output_bytes=request.max_output_bytes,
                )

        # auto mode: sandbox-first, local fallback only for degradable infra errors.
        try:
            result = await self._sandbox_executor.execute(request)
            return _to_outcome(result, runtime="sandbox", max_output_bytes=request.max_output_bytes)
        except AdapterFailure as exc:
            if not exc.degradable:
                return _error_outcome(
                    message=exc.message,
                    runtime="sandbox",
                    max_output_bytes=request.max_output_bytes,
                )
            if not await self._consume_degrade_budget():
                return _error_outcome(
                    message="sandbox unavailable and auto-degrade budget exhausted",
                    runtime="sandbox",
                    max_output_bytes=request.max_output_bytes,
                )
            local_result = await self._local_executor.execute(request)
            return _to_outcome(
                local_result,
                runtime="degraded-local",
                max_output_bytes=request.max_output_bytes,
                fallback_reason=exc.reason,
            )

    async def execute_python(self, request: PythonExecutionRequest) -> ExecutionOutcome:
        if self._mode == "local":
            result = await self._local_executor.execute_python(request)
            return _to_outcome(result, runtime="local", max_output_bytes=request.max_output_bytes)

        if self._mode == "sandbox":
            try:
                result = await self._sandbox_executor.execute_python(request)
                return _to_outcome(
                    result, runtime="sandbox", max_output_bytes=request.max_output_bytes
                )
            except AdapterFailure as exc:
                return _error_outcome(
                    message=exc.message,
                    runtime="sandbox",
                    max_output_bytes=request.max_output_bytes,
                )

        try:
            result = await self._sandbox_executor.execute_python(request)
            return _to_outcome(result, runtime="sandbox", max_output_bytes=request.max_output_bytes)
        except AdapterFailure as exc:
            if not exc.degradable:
                return _error_outcome(
                    message=exc.message,
                    runtime="sandbox",
                    max_output_bytes=request.max_output_bytes,
                )
            if not await self._consume_degrade_budget():
                return _error_outcome(
                    message="sandbox unavailable and auto-degrade budget exhausted",
                    runtime="sandbox",
                    max_output_bytes=request.max_output_bytes,
                )
            local_result = await self._local_executor.execute_python(request)
            return _to_outcome(
                local_result,
                runtime="degraded-local",
                max_output_bytes=request.max_output_bytes,
                fallback_reason=exc.reason,
            )

    async def _consume_degrade_budget(self) -> bool:
        if self._auto_degrade_max_per_minute <= 0:
            return False
        now = time.monotonic()
        cutoff = now - 60.0
        async with self._degrade_lock:
            while self._degrade_events and self._degrade_events[0] < cutoff:
                self._degrade_events.popleft()
            if len(self._degrade_events) >= self._auto_degrade_max_per_minute:
                return False
            self._degrade_events.append(now)
            return True


def _to_outcome(
    result: RawExecutionResult,
    *,
    runtime: Literal["sandbox", "local", "degraded-local"],
    max_output_bytes: int,
    fallback_reason: str | None = None,
) -> ExecutionOutcome:
    status: Literal["success", "error"] = "success" if result.success and result.exit_code == 0 else "error"
    content = _normalize_output(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        max_output_bytes=max_output_bytes,
    )
    return ExecutionOutcome(
        content=content,
        status=status,
        runtime=runtime,
        exit_code=result.exit_code,
        fallback_reason=fallback_reason,
    )


def _error_outcome(
    *,
    message: str,
    runtime: Literal["sandbox", "local", "degraded-local"],
    max_output_bytes: int,
) -> ExecutionOutcome:
    content = _truncate_output(message, max_output_bytes=max_output_bytes)
    return ExecutionOutcome(
        content=content,
        status="error",
        runtime=runtime,
        exit_code=1,
    )


def _normalize_output(
    *,
    stdout: str,
    stderr: str,
    exit_code: int,
    max_output_bytes: int,
) -> str:
    output_parts: list[str] = []
    if stdout:
        output_parts.append(stdout)
    if stderr:
        for line in stderr.strip().split("\n"):
            if line:
                output_parts.append(f"[stderr] {line}")

    output = "\n".join(output_parts) if output_parts else "<no output>"
    if exit_code != 0:
        output = f"{output.rstrip()}\n\nExit code: {exit_code}"

    return _truncate_output(output, max_output_bytes=max_output_bytes)


def _truncate_output(output: str, *, max_output_bytes: int) -> str:
    if len(output) <= max_output_bytes:
        return output
    marker = f"\n\n... Output truncated at {max_output_bytes} bytes."
    truncated = output[: max_output_bytes - len(marker)] if max_output_bytes > len(marker) else ""
    return f"{truncated}{marker}"


def _with_cwd(command: str, cwd: str) -> str:
    if not cwd:
        return command
    return f"cd -- {shlex.quote(cwd)} && {command}"


def _with_cwd_python(code: str, cwd: str) -> str:
    if not cwd:
        return code
    return f"import os\nos.chdir({cwd!r})\n{code}"


def _is_policy_denied(resp: object) -> bool:
    for item in getattr(resp, "errors", []) or []:
        code = str(getattr(item, "code", "")).upper()
        if "POLICY" in code or "DENIED" in code:
            return True
    status = str(getattr(resp, "status", "")).lower()
    return status == "rejected"


def _policy_message(resp: object) -> str:
    errors = []
    for item in getattr(resp, "errors", []) or []:
        code = str(getattr(item, "code", ""))
        message = str(getattr(item, "message", ""))
        errors.append(f"{code}: {message}".strip(": "))
    if errors:
        return "; ".join(errors)
    stderr = str(getattr(resp, "stderr", "") or "")
    return stderr or "sandbox execution denied by policy"
