"""Tests for SandboxBrokerService."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kardcraft.sandbox_broker.service import (
    SandboxBrokerService,
    _overloaded_response,
    _to_limits,
)
from kardcraft.sandbox_broker_pb2 import (
    CommandPayload,
    ExecuteRequest,
    ExecutionPolicy,
    Limits,
    PythonPayload,
    ResumeRequest,
    StartRequest,
    StatusRequest,
)


class _FakeConfigProvider:
    async def load(self):
        return SimpleNamespace(data=None, revision="test-rev")


class _FakeRouter:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return self._result or {
            "workspace_id": kwargs["workspace_id"],
            "task_id": kwargs["task_id"],
            "runtime": "container",
            "state": "succeeded",
            "status": "succeeded",
            "success": True,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 10,
            "started_at_ms": 1000,
            "completed_at_ms": 1010,
            "routing": {
                "selected_runtime": "container",
                "eligibility_reason": "non-eligible",
                "fallback_used": False,
                "fallback_reason": "",
            },
            "sandbox": {
                "runtime": "runsc",
                "image": "img",
                "policy_profile": "shell-tool-default",
            },
            "errors": [],
        }


def _cmd_request(
    task_id: str, policy_profile: str = "shell-tool-default"
) -> ExecuteRequest:
    return ExecuteRequest(
        workspace_id="ws-1",
        task_id=task_id,
        user_id="u-1",
        tool_name="shell",
        workflow_type="shell-tool",
        policy=ExecutionPolicy(policy_profile=policy_profile),
        command=CommandPayload(command="echo ok", env={}),
    )


def _py_request(task_id: str) -> ExecuteRequest:
    return ExecuteRequest(
        workspace_id="ws-1",
        task_id=task_id,
        user_id="u-1",
        tool_name="python",
        workflow_type="python-tool",
        policy=ExecutionPolicy(policy_profile="python-fastlane-safe"),
        python=PythonPayload(code="print(1)", language="python"),
    )


@pytest.mark.asyncio
async def test_execute_with_command_payload():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    resp = await service.Execute(_cmd_request("t1"), None)

    assert resp.status == "succeeded"
    assert resp.success is True
    assert resp.stdout == "ok"
    assert len(service.router.calls) == 1
    assert service.router.calls[0]["payload_type"] == "command"
    assert service.router.calls[0]["command"] == "echo ok"


@pytest.mark.asyncio
async def test_execute_with_python_payload():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    resp = await service.Execute(_py_request("t2"), None)

    assert resp.status == "succeeded"
    assert resp.runtime == "container"
    assert len(service.router.calls) == 1
    assert service.router.calls[0]["payload_type"] == "python"
    assert service.router.calls[0]["code"] == "print(1)"
    assert service.router.calls[0]["language"] == "python"


@pytest.mark.asyncio
async def test_execute_stores_status():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    resp = await service.Execute(_cmd_request("t3"), None)

    assert resp.execution_id in service._status
    assert service._status[resp.execution_id]["task_id"] == "t3"


@pytest.mark.asyncio
async def test_health_returns_status():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    resp = await service.Health(SimpleNamespace(), None)

    assert hasattr(resp, "healthy")
    assert hasattr(resp, "status")
    assert hasattr(resp, "config_revision")
    assert resp.config_revision == "default"


@pytest.mark.asyncio
async def test_start_creates_snapshot():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    req = StartRequest(execute=_cmd_request("t4"))
    resp = await service.Start(req, None)

    assert resp.state == "SNAPSHOT_CREATED"
    assert resp.execution_id in service._status
    assert "snap-" in resp.snapshot_id


@pytest.mark.asyncio
async def test_resume_stores_state():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    req = ResumeRequest(snapshot_id="snap-abc")
    resp = await service.Resume(req, None)

    assert resp.state == "RESUMED"
    assert resp.snapshot_id == "snap-abc"
    assert resp.execution_id in service._status
    assert service._status[resp.execution_id]["snapshot_id"] == "snap-abc"


@pytest.mark.asyncio
async def test_get_status_returns_stored_state():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    exec_resp = await service.Execute(_cmd_request("t5"), None)
    status_resp = await service.GetStatus(
        StatusRequest(execution_id=exec_resp.execution_id), None
    )

    assert status_resp.state == "succeeded"


@pytest.mark.asyncio
async def test_get_status_unknown_returns_unknown():
    service = SandboxBrokerService(_FakeConfigProvider())

    resp = await service.GetStatus(StatusRequest(execution_id="unknown-id"), None)

    assert resp.state == "UNKNOWN"


@pytest.mark.asyncio
async def test_cancel_existing_execution():
    service = SandboxBrokerService(_FakeConfigProvider())
    service.router = _FakeRouter()

    exec_resp = await service.Execute(_cmd_request("t6"), None)
    cancel_resp = await service.Cancel(
        SimpleNamespace(execution_id=exec_resp.execution_id), None
    )

    assert cancel_resp.cancelled is True
    assert service._status[exec_resp.execution_id]["state"] == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_unknown_execution_returns_not_found():
    service = SandboxBrokerService(_FakeConfigProvider())

    resp = await service.Cancel(SimpleNamespace(execution_id="does-not-exist"), None)

    assert resp.cancelled is False
    assert resp.message == "not-found"


@pytest.mark.asyncio
async def test_refresh_policy_skips_when_ttl_not_expired():
    service = SandboxBrokerService(_FakeConfigProvider())
    service._last_refresh_at = float("inf")

    await service.refresh_policy()

    assert service._last_refresh_at == float("inf")


@pytest.mark.asyncio
async def test_refresh_policy_updates_when_ttl_expired():
    service = SandboxBrokerService(_FakeConfigProvider())
    service._last_refresh_at = 0.0

    class _Provider:
        async def load(self):
            return SimpleNamespace(data=None, revision="updated-rev")

    service.config_provider = _Provider()

    await service.refresh_policy()

    assert service._last_refresh_at > 0


def test_to_limits_returns_none_for_empty_message():
    result = _to_limits(None)
    assert result is None


def test_to_limits_returns_none_when_all_zeros():
    msg = SimpleNamespace(
        timeout_seconds=0,
        memory_mb=0,
        cpu_seconds=0,
        max_processes=0,
        allow_network=False,
    )
    result = _to_limits(msg)
    assert result is None


def test_to_limits_returns_model_when_set():
    msg = SimpleNamespace(
        timeout_seconds=30,
        memory_mb=1024,
        cpu_seconds=15,
        max_processes=32,
        allow_network=True,
    )
    result = _to_limits(msg)
    assert result is not None
    assert result.timeout_seconds == 30
    assert result.memory_mb == 1024
    assert result.allow_network is True


def test_overloaded_response_shape():
    resp = _overloaded_response(
        workspace_id="ws-x",
        task_id="t-x",
        policy_profile="shell-tool-default",
    )
    assert resp.status == "overloaded"
    assert resp.success is False
    assert resp.errors[0].code == "BROKER_OVERLOADED"
    assert resp.routing.eligibility_reason == "overloaded"
