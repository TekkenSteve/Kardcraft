"""Tests for ShellMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.tools.base import ToolException

from kardcraft.agent_skills.shell import ShellMiddleware
from kardcraft.services.shell_execution_engine import (
    ExecutionOutcome,
    ShellExecutionRequest,
)


class _FakeExecutionPort:
    async def execute_shell(self, request: ShellExecutionRequest) -> ExecutionOutcome:
        self.calls.append(request)
        return self._outcome


@pytest.mark.asyncio
async def test_empty_command_raises_tool_exception():
    mw = ShellMiddleware(workspace_root="/tmp", execution_port=_FakeExecutionPort())
    with pytest.raises(ToolException, match="non-empty command"):
        await mw._run_shell_command("", tool_call_id="cid-1")


@pytest.mark.asyncio
async def test_non_string_command_raises_tool_exception():
    mw = ShellMiddleware(workspace_root="/tmp", execution_port=_FakeExecutionPort())
    with pytest.raises(ToolException, match="non-empty command"):
        await mw._run_shell_command(123, tool_call_id="cid-1")  # type: ignore


@pytest.mark.asyncio
async def test_successful_execution_returns_tool_message():
    port = _FakeExecutionPort()
    port._outcome = ExecutionOutcome(
        content="hello world",
        status="success",
        runtime="local",
        exit_code=0,
    )
    port.calls = []

    mw = ShellMiddleware(workspace_root="/tmp", execution_port=port)
    result = await mw._run_shell_command("echo hello", tool_call_id="cid-2")

    assert result.content == "hello world"
    assert result.status == "success"
    assert result.tool_call_id == "cid-2"
    assert len(port.calls) == 1
    assert port.calls[0].command == "echo hello"


@pytest.mark.asyncio
async def test_execution_port_exception_returns_error_message():
    port = _FakeExecutionPort()
    port._outcome = ExecutionOutcome(
        content="", status="error", runtime="local", exit_code=1
    )
    port.calls = []

    mw = ShellMiddleware(workspace_root="/tmp", execution_port=port)
    result = await mw._run_shell_command("false", tool_call_id="cid-3")

    assert result.status == "error"
    assert len(port.calls) == 1


@pytest.mark.asyncio
async def test_tool_description_includes_workspace_root():
    mw = ShellMiddleware(
        workspace_root="/my/workspace", execution_port=_FakeExecutionPort()
    )
    assert "/my/workspace" in mw.tools[0].description
