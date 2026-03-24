from kardcraft.sandbox_broker.policy_profiles import DEFAULT_POLICY_PROFILES, PolicyProfileResolver
from kardcraft.sandbox_broker.runtime_router import BrokerRuntimeRouter


class _FakeMontyRuntime:
    async def run(self, **kwargs):
        return "monty-ok"


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


async def test_router_selects_monty_for_eligible_profile():
    resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="unit")
    router = BrokerRuntimeRouter(
        profile_resolver=resolver,
        monty_runtime=_FakeMontyRuntime(),
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
    assert result["runtime"] == "monty"
    assert result["success"] is True


async def test_router_falls_back_to_container_for_command_profile():
    resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="unit")
    router = BrokerRuntimeRouter(
        profile_resolver=resolver,
        monty_runtime=_FakeMontyRuntime(),
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
    assert result["runtime"] == "container"
    assert result["success"] is True
