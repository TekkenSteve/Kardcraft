"""Tests for BrokerRuntimeRouter."""

from __future__ import annotations

import pytest

from kardcraft.sandbox_broker.policy_profiles import (
    DEFAULT_POLICY_PROFILES,
    PolicyProfileResolver,
)
from kardcraft.sandbox_broker.runtime_router import BrokerRuntimeRouter


class _FailingMontyRuntime:
    async def run(self, **kwargs):
        raise RuntimeError("monty failed")


class _OkMontyRuntime:
    async def run(self, **kwargs):
        return "monty-output"


class _FakeContainerRuntime:
    async def execute(self, req, limits):
        class _Result:
            success = True
            exit_code = 0
            stdout = "container-ok"
            stderr = ""
            duration_ms = 1
            started_at_ms = 1
            completed_at_ms = 2
            metadata = {"sandbox_runtime": "runsc", "image": "img"}

        return _Result()


class _FailingContainerRuntime:
    async def execute(self, req, limits):
        class _Result:
            success = False
            exit_code = 1
            stdout = ""
            stderr = "container error"
            duration_ms = 1
            started_at_ms = 1
            completed_at_ms = 2
            metadata = {}

        return _Result()


def _resolver():
    return PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="unit")


async def test_payload_profile_mismatch_returns_rejected():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_OkMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )
    result = await router.execute(
        workspace_id="ws",
        task_id="t1",
        user_id="u1",
        workflow_type="wf",
        tool_name="tool",
        profile_name="python-fastlane-safe",
        payload_type="command",
        command="echo ok",
    )
    assert result["status"] == "rejected"
    assert result["runtime"] == "none"
    assert "errors" in result
    assert result["errors"][0]["code"] == "BROKER_PAYLOAD_PROFILE_MISMATCH"


async def test_monty_fallback_to_container_on_exception():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_FailingMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )
    result = await router.execute(
        workspace_id="ws",
        task_id="t1",
        user_id="u1",
        workflow_type="wf",
        tool_name="tool",
        profile_name="python-fastlane-safe",
        payload_type="python",
        code="print(1)",
    )
    assert result["runtime"] == "container"
    assert result["routing"]["fallback_used"] is True
    assert "monty failed" in result["routing"]["fallback_reason"]


async def test_container_execution_includes_routing_metadata():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_OkMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )
    result = await router.execute(
        workspace_id="ws",
        task_id="t1",
        user_id="u1",
        workflow_type="wf",
        tool_name="tool",
        profile_name="shell-tool-default",
        payload_type="command",
        command="echo ok",
    )
    assert "routing" in result
    assert result["routing"]["selected_runtime"] == "container"
    assert result["routing"]["eligibility_reason"] == "non-eligible"
    assert result["routing"]["fallback_used"] is False
    assert "sandbox" in result
    assert result["sandbox"]["policy_profile"] == "shell-tool-default"


async def test_unknown_profile_raises_key_error():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_OkMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )
    with pytest.raises(KeyError):
        await router.execute(
            workspace_id="ws",
            task_id="t1",
            user_id="u1",
            workflow_type="wf",
            tool_name="tool",
            profile_name="nonexistent-profile",
            payload_type="command",
            command="echo ok",
        )


async def test_container_failure_returns_failed_status():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_OkMontyRuntime(),
        container_runtime=_FailingContainerRuntime(),
    )
    result = await router.execute(
        workspace_id="ws",
        task_id="t1",
        user_id="u1",
        workflow_type="wf",
        tool_name="tool",
        profile_name="shell-tool-default",
        payload_type="command",
        command="false",
    )
    assert result["runtime"] == "container"
    assert result["success"] is False
    assert result["exit_code"] == 1
    assert result["stderr"] == "container error"


async def test_rejected_response_includes_timing_fields():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_OkMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )
    result = await router.execute(
        workspace_id="ws",
        task_id="t1",
        user_id="u1",
        workflow_type="wf",
        tool_name="tool",
        profile_name="python-fastlane-safe",
        payload_type="command",
        command="echo ok",
    )
    assert result["duration_ms"] == 0
    assert result["started_at_ms"] > 0
    assert result["completed_at_ms"] >= result["started_at_ms"]


async def test_to_json_serializes_result():
    router = BrokerRuntimeRouter(
        profile_resolver=_resolver(),
        monty_runtime=_OkMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )
    result = await router.execute(
        workspace_id="ws",
        task_id="t1",
        user_id="u1",
        workflow_type="wf",
        tool_name="tool",
        profile_name="shell-tool-default",
        payload_type="command",
        command="echo ok",
    )
    json_str = BrokerRuntimeRouter.to_json(result)
    assert '"runtime": "container"' in json_str
