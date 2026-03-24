from __future__ import annotations

import pytest

from kardcraft.agent_skills.code import CodeMiddleware
from kardcraft.services.shell_execution_engine import (
    ExecutionOutcome,
    PythonExecutionRequest,
    ShellExecutionRequest,
)


class _FakeExecutionPort:
    async def execute_shell(self, request: ShellExecutionRequest) -> ExecutionOutcome:
        raise RuntimeError("not used")

    async def execute_python(self, request: PythonExecutionRequest) -> ExecutionOutcome:
        return ExecutionOutcome(
            content="ok",
            status="success",
            runtime="local",
            exit_code=0,
        )


@pytest.mark.asyncio
async def test_code_middleware_routes_to_execution_port():
    middleware = CodeMiddleware(
        workspace_root=".",
        execution_port=_FakeExecutionPort(),
    )
    result = await middleware._run_python_code("print('x')", tool_call_id="tool-1")
    assert result.status == "success"
    assert result.content == "ok"

