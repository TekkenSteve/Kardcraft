from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from kardcraft.config import Config
from kardcraft.services.shell_execution_engine import (
    AdapterFailure,
    LocalExecutor,
    PythonExecutionRequest,
    RawExecutionResult,
    ShellExecutionEngine,
    ShellExecutionRequest,
)


class _FakeSandboxExecutor:
    def __init__(self, result: RawExecutionResult | None = None, failure: AdapterFailure | None = None):
        self.result = result
        self.failure = failure
        self.calls = 0

    async def execute(self, request: ShellExecutionRequest) -> RawExecutionResult:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        assert self.result is not None
        return self.result

    async def execute_shell(self, request: ShellExecutionRequest) -> RawExecutionResult:
        return await self.execute(request)

    async def execute_python(self, request: PythonExecutionRequest) -> RawExecutionResult:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        assert self.result is not None
        return self.result


class _FakeLocalExecutor:
    def __init__(self, result: RawExecutionResult):
        self.result = result
        self.calls = 0

    async def execute(self, request: ShellExecutionRequest) -> RawExecutionResult:
        self.calls += 1
        return self.result

    async def execute_shell(self, request: ShellExecutionRequest) -> RawExecutionResult:
        return await self.execute(request)

    async def execute_python(self, request: PythonExecutionRequest) -> RawExecutionResult:
        self.calls += 1
        return self.result


def _request(command: str = "echo ok", *, max_output_bytes: int = 100_000) -> ShellExecutionRequest:
    return ShellExecutionRequest(
        workspace_id="ws-1",
        command=command,
        tool_call_id="tool-1",
        timeout_seconds=60,
        env={},
        cwd=".",
        max_output_bytes=max_output_bytes,
    )


def _python_request(code: str = "print('ok')", *, max_output_bytes: int = 100_000) -> PythonExecutionRequest:
    return PythonExecutionRequest(
        workspace_id="ws-1",
        code=code,
        tool_call_id="tool-2",
        timeout_seconds=60,
        env={},
        cwd=".",
        max_output_bytes=max_output_bytes,
    )


@pytest.mark.asyncio
async def test_local_mode_routes_to_local_executor():
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="ok", stderr="", exit_code=0, success=True)
    )
    sandbox = _FakeSandboxExecutor(
        RawExecutionResult(stdout="sandbox", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="local", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_shell(_request())

    assert outcome.status == "success"
    assert outcome.runtime == "local"
    assert "ok" in outcome.content
    assert local.calls == 1
    assert sandbox.calls == 0


@pytest.mark.asyncio
async def test_auto_mode_degrades_on_infra_failure():
    sandbox = _FakeSandboxExecutor(
        failure=AdapterFailure(
            reason="broker_unreachable",
            degradable=True,
            message="broker unavailable",
        )
    )
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="from-local", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="auto", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_shell(_request())

    assert outcome.status == "success"
    assert outcome.runtime == "degraded-local"
    assert outcome.fallback_reason == "broker_unreachable"
    assert "from-local" in outcome.content
    assert sandbox.calls == 1
    assert local.calls == 1


@pytest.mark.asyncio
async def test_auto_mode_policy_denied_does_not_degrade():
    sandbox = _FakeSandboxExecutor(
        failure=AdapterFailure(reason="policy_denied", degradable=False, message="policy denied")
    )
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="from-local", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="auto", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_shell(_request())

    assert outcome.status == "error"
    assert outcome.runtime == "sandbox"
    assert "policy denied" in outcome.content
    assert local.calls == 0


@pytest.mark.asyncio
async def test_sandbox_mode_fail_closed():
    sandbox = _FakeSandboxExecutor(
        failure=AdapterFailure(reason="broker_timeout", degradable=True, message="timeout")
    )
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="from-local", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="sandbox", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_shell(_request())

    assert outcome.status == "error"
    assert outcome.runtime == "sandbox"
    assert "timeout" in outcome.content
    assert local.calls == 0


@pytest.mark.asyncio
async def test_output_annotation_precedes_truncation_marker():
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="x" * 120, stderr="", exit_code=7, success=False)
    )
    sandbox = _FakeSandboxExecutor(
        RawExecutionResult(stdout="unused", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="local", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_shell(_request(max_output_bytes=30))

    assert outcome.status == "error"
    assert "... Output truncated at 30 bytes." in outcome.content


@pytest.mark.asyncio
async def test_local_executor_honors_cwd():
    executor = LocalExecutor()
    with tempfile.TemporaryDirectory() as td:
        expected = Path(td).resolve()
        req = ShellExecutionRequest(
            workspace_id="ws-1",
            command="pwd",
            tool_call_id="tool-1",
            timeout_seconds=30,
            env={},
            cwd=str(expected),
            max_output_bytes=1000,
        )
        result = await executor.execute(req)
        assert result.success is True
        assert expected.as_posix() in result.stdout.strip()


@pytest.mark.asyncio
async def test_execute_python_local_mode():
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="py-ok", stderr="", exit_code=0, success=True)
    )
    sandbox = _FakeSandboxExecutor(
        RawExecutionResult(stdout="unused", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="local", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_python(_python_request())

    assert outcome.status == "success"
    assert outcome.runtime == "local"
    assert "py-ok" in outcome.content
    assert local.calls == 1
    assert sandbox.calls == 0


@pytest.mark.asyncio
async def test_execute_python_auto_degrade_on_infra_failure():
    sandbox = _FakeSandboxExecutor(
        failure=AdapterFailure(
            reason="broker_unreachable",
            degradable=True,
            message="broker unavailable",
        )
    )
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="py-local", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="auto", sandbox_executor=sandbox, local_executor=local)

    outcome = await engine.execute_python(_python_request())

    assert outcome.status == "success"
    assert outcome.runtime == "degraded-local"
    assert outcome.fallback_reason == "broker_unreachable"
    assert "py-local" in outcome.content


@pytest.mark.asyncio
async def test_auto_mode_degrade_budget_limits_fallback():
    sandbox = _FakeSandboxExecutor(
        failure=AdapterFailure(
            reason="broker_unreachable",
            degradable=True,
            message="broker unavailable",
        )
    )
    local = _FakeLocalExecutor(
        RawExecutionResult(stdout="local-ok", stderr="", exit_code=0, success=True)
    )
    engine = ShellExecutionEngine(mode="auto", sandbox_executor=sandbox, local_executor=local)
    engine._auto_degrade_max_per_minute = 1  # test budget limit

    first = await engine.execute_shell(_request())
    second = await engine.execute_shell(_request())

    assert first.runtime == "degraded-local"
    assert first.status == "success"
    assert second.runtime == "sandbox"
    assert second.status == "error"
    assert "budget exhausted" in second.content


def test_invalid_mode_fails_fast():
    with pytest.raises(ValueError, match="SHELL_EXECUTION_MODE"):
        ShellExecutionEngine(mode="invalid")  # type: ignore[arg-type]


def test_config_invalid_shell_mode_fails_fast(monkeypatch):
    monkeypatch.setenv("SHELL_EXECUTION_MODE", "invalid")
    with pytest.raises(ValidationError):
        Config()
