"""Middleware exposing Python code execution via unified execution engine."""

from __future__ import annotations

import os
import uuid
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools.base import ToolException

from kardcraft.services.shell_execution_engine import (
    ExecutionPort,
    PythonExecutionRequest,
    ShellExecutionEngine,
)


class CodeMiddleware(AgentMiddleware[AgentState, Any]):
    """Expose Python code execution with shared execution routing and policy."""

    def __init__(
        self,
        *,
        workspace_root: str,
        workspace_id: str | None = None,
        timeout: float = 120.0,
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
        execution_port: ExecutionPort | None = None,
    ) -> None:
        super().__init__()
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._tool_name = "python_exec"
        self._env = env if env is not None else os.environ.copy()
        self._workspace_root = workspace_root
        self._workspace_id = str(workspace_id or "").strip() or "agent-skills"
        self._execution_port = execution_port or ShellExecutionEngine()

        description = (
            f"Execute Python code in a constrained execution runtime. "
            f"Code runs with working directory context: {workspace_root}. "
            f"Output may be truncated by configured limits."
        )

        @tool(self._tool_name, description=description)
        async def python_exec_tool(
            code: str,
            runtime: ToolRuntime[None, AgentState],
        ) -> ToolMessage | str:
            return await self._run_python_code(code, tool_call_id=runtime.tool_call_id)

        self._python_exec_tool = python_exec_tool
        self.tools = [self._python_exec_tool]

    async def _run_python_code(
        self,
        code: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage | str:
        if not code or not isinstance(code, str):
            raise ToolException("python_exec expects a non-empty code string.")

        try:
            outcome = await self._execution_port.execute_python(
                PythonExecutionRequest(
                    workspace_id=self._workspace_id,
                    code=code,
                    tool_call_id=tool_call_id or f"python-exec-{uuid.uuid4().hex[:12]}",
                    timeout_seconds=int(self._timeout),
                    env=self._env,
                    cwd=self._workspace_root,
                    max_output_bytes=self._max_output_bytes,
                    language="python",
                )
            )
            return ToolMessage(
                content=outcome.content,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status=outcome.status,
            )
        except Exception as exc:
            return ToolMessage(
                content=str(exc).strip() or "python execution failed",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )


__all__ = ["CodeMiddleware"]

