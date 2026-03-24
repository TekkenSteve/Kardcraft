from kardcraft.sandbox_broker.container_runtime import (
    ContainerLimits,
    ContainerRequest,
    ContainerRuntime,
    check_sandbox_runtime_ready,
)


def test_container_runtime_builds_hardened_command():
    commands = []

    def _runner(cmd, **kwargs):
        commands.append(cmd)
        class _Proc:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return _Proc()

    runtime = ContainerRuntime(runner=_runner)
    req = ContainerRequest(
        workspace_id="ws-1",
        task_id="t-1",
        command="echo ok",
        env={"X": "1"},
    )
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        runtime.execute(
            req,
            ContainerLimits(
                timeout_seconds=10,
                memory_mb=256,
                cpu_seconds=5,
                max_processes=32,
                allow_network=False,
            ),
        )
    )
    assert result.success is True
    cmd = commands[0]
    assert "--runtime=runsc" in cmd
    assert "--read-only" in cmd
    assert "--cap-drop=ALL" in cmd
    assert "--network" in cmd
    assert "none" in cmd


def test_check_sandbox_runtime_ready_success():
    def _runner(cmd, **kwargs):
        class _Proc:
            returncode = 0
            stdout = '{"runsc":{"path":"runsc"}}'
            stderr = ""
        return _Proc()

    healthy, reason = check_sandbox_runtime_ready(_runner, "runsc")
    assert healthy is True
    assert reason == "ready"
