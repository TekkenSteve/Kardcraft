from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kardcraft.sandbox_broker.service import SandboxBrokerService
from kardcraft.sandbox_broker_pb2 import CommandPayload, ExecuteRequest, ExecutionPolicy


class _FakeConfigProvider:
    async def load(self):
        return SimpleNamespace(data=None, revision="test")


class _SlowRouter:
    async def execute(self, **kwargs):
        await asyncio.sleep(0.08)
        now = 0
        return {
            "workspace_id": kwargs["workspace_id"],
            "task_id": kwargs["task_id"],
            "runtime": "container",
            "status": "succeeded",
            "success": True,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 1,
            "started_at_ms": now,
            "completed_at_ms": now,
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


def _request(task_id: str) -> ExecuteRequest:
    return ExecuteRequest(
        workspace_id="ws-1",
        task_id=task_id,
        user_id="u-1",
        tool_name="shell",
        workflow_type="shell-tool",
        policy=ExecutionPolicy(policy_profile="shell-tool-default"),
        command=CommandPayload(command="echo ok", env={}),
    )


@pytest.mark.asyncio
async def test_broker_service_overload_returns_structured_error():
    service = SandboxBrokerService(
        _FakeConfigProvider(),
        max_concurrent_executions=1,
        queue_wait_seconds=0.01,
        policy_refresh_ttl_seconds=999.0,
    )
    service.router = _SlowRouter()

    await service._execute_semaphore.acquire()  # force queue wait timeout path
    try:
        resp = await service.Execute(_request("t-2"), None)
    finally:
        service._execute_semaphore.release()

    assert resp.status == "overloaded"
    assert resp.errors and resp.errors[0].code == "BROKER_OVERLOADED"
