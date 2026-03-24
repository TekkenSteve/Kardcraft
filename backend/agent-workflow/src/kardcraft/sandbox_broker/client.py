"""Sandbox broker gRPC client."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

import grpc

from kardcraft.sandbox_broker_pb2 import (
    CommandPayload,
    ExecuteRequest,
    ExecutionPolicy,
    Limits,
    PythonPayload,
)
from kardcraft.sandbox_broker_pb2_grpc import SandboxBrokerServiceStub

if TYPE_CHECKING:
    from kardcraft.config import Config


@dataclass
class BrokerClientConfig:
    address: str = os.getenv("SANDBOX_BROKER_TARGET", "sandbox-broker:50061")
    timeout_seconds: float = float(os.getenv("SANDBOX_BROKER_TIMEOUT_SECONDS", "30"))


class SandboxBrokerClient:
    def __init__(self, config: Optional[BrokerClientConfig] = None):
        self.config = config or BrokerClientConfig()
        self._channel = grpc.aio.insecure_channel(self.config.address)
        self._stub = SandboxBrokerServiceStub(self._channel)

    @classmethod
    def from_config(cls, config: "Config") -> "SandboxBrokerClient":
        return cls(
            BrokerClientConfig(
                address=config.sandbox_broker_target,
                timeout_seconds=config.sandbox_broker_timeout_seconds,
            )
        )

    async def execute_command(
        self,
        *,
        workspace_id: str,
        task_id: str,
        user_id: str,
        tool_name: str,
        workflow_type: str,
        command: str,
        env: Dict[str, str],
        policy_profile: str = "shell-tool-default",
        timeout_seconds: int = 120,
        allow_network: bool = False,
    ):
        req = ExecuteRequest(
            workspace_id=workspace_id,
            task_id=task_id,
            user_id=user_id,
            tool_name=tool_name,
            workflow_type=workflow_type,
            policy=ExecutionPolicy(
                policy_profile=policy_profile,
                limits_override=Limits(
                    timeout_seconds=timeout_seconds,
                    allow_network=allow_network,
                ),
            ),
            command=CommandPayload(
                command=command,
                env=env,
            ),
        )
        return await self._stub.Execute(req, timeout=self.config.timeout_seconds)

    async def execute_python(
        self,
        *,
        workspace_id: str,
        task_id: str,
        user_id: str,
        tool_name: str,
        workflow_type: str,
        code: str,
        language: str = "python",
        inputs_json: Optional[Dict[str, str]] = None,
        policy_profile: str = "shell-tool-default",
        timeout_seconds: int = 120,
        allow_network: bool = False,
    ):
        req = ExecuteRequest(
            workspace_id=workspace_id,
            task_id=task_id,
            user_id=user_id,
            tool_name=tool_name,
            workflow_type=workflow_type,
            policy=ExecutionPolicy(
                policy_profile=policy_profile,
                limits_override=Limits(
                    timeout_seconds=timeout_seconds,
                    allow_network=allow_network,
                ),
            ),
            python=PythonPayload(
                code=code,
                language=language,
                inputs_json=inputs_json or {},
            ),
        )
        return await self._stub.Execute(req, timeout=self.config.timeout_seconds)

    async def close(self) -> None:
        await self._channel.close()

    def execute_command_sync(self, **kwargs):
        return asyncio.get_event_loop().run_until_complete(self.execute_command(**kwargs))
