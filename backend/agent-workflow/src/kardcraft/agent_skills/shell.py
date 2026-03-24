"""Simplified middleware that exposes a basic shell tool to agents.

Copied from archive/DeepAgents-Skills/shell.py
"""

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
    ShellExecutionEngine,
    ShellExecutionRequest,
)


class ShellMiddleware(AgentMiddleware[AgentState, Any]):
    """Give basic shell access to agents via the shell.

    This shell will execute on the local machine and has NO safeguards except
    for the human in the loop safeguard provided by the CLI itself.
    """

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
        """Initialize an instance of `ShellMiddleware`.

        Args:
            workspace_root: Working directory for shell commands.
            timeout: Maximum time in seconds to wait for command completion.
                Defaults to 120 seconds.
            max_output_bytes: Maximum number of bytes to capture from command output.
                Defaults to 100,000 bytes.
            env: Environment variables to pass to the subprocess. If None,
                uses the current process's environment. Defaults to None.
        """
        super().__init__()
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._tool_name = "shell"
        self._env = env if env is not None else os.environ.copy()
        self._workspace_root = workspace_root
        self._workspace_id = str(workspace_id or "").strip() or "agent-skills"
        self._execution_port = execution_port or ShellExecutionEngine()

        # Build description with working directory information
        description = (
            f"Execute a shell command directly on the host. Commands will run in "
            f"the working directory: {workspace_root}. Each command runs in a fresh shell "
            f"environment with the current process's environment variables. Commands may "
            f"be truncated if they exceed the configured timeout or output limits."
        )

        @tool(self._tool_name, description=description)
        async def shell_tool(
            command: str,
            runtime: ToolRuntime[None, AgentState],
        ) -> ToolMessage | str:
            """Execute a shell command.

            Args:
                command: The shell command to execute.
                runtime: The tool runtime context.
            """
            return await self._run_shell_command(command, tool_call_id=runtime.tool_call_id)

        self._shell_tool = shell_tool
        self.tools = [self._shell_tool]

    async def _run_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage | str:
        """Execute a shell command and return the result.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        try:
            outcome = await self._execution_port.execute_shell(
                ShellExecutionRequest(
                    workspace_id=self._workspace_id,
                    command=command,
                    tool_call_id=tool_call_id or f"shell-{uuid.uuid4().hex[:12]}",
                    timeout_seconds=int(self._timeout),
                    env=self._env,
                    cwd=self._workspace_root,
                    max_output_bytes=self._max_output_bytes,
                )
            )
            return ToolMessage(
                content=outcome.content,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status=outcome.status,
            )
        except Exception as exc:
            output = str(exc).strip() or "shell execution failed"
            status = "error"

        return ToolMessage(
            content=output,
            tool_call_id=tool_call_id,
            name=self._tool_name,
            status=status,
        )


__all__ = ["ShellMiddleware"]
