"""gRPC sandbox broker service implementation."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Dict, Optional

from kardcraft.sandbox_broker_pb2 import (
    CancelResponse,
    ErrorMetadata,
    ExecuteResponse,
    ExecutionProgress,
    HealthResponse,
    RoutingMetadata,
    SandboxMetadata,
    StatusResponse,
)
from kardcraft.sandbox_broker_pb2_grpc import SandboxBrokerServiceServicer

from .container_runtime import check_sandbox_runtime_ready
from .config_provider import CompositeConfigProvider
from .policy_profiles import (
    DEFAULT_POLICY_PROFILES,
    LimitsModel,
    PolicyProfileResolver,
)
from .runtime_router import BrokerRuntimeRouter


class SandboxBrokerService(SandboxBrokerServiceServicer):
    def __init__(
        self,
        config_provider: CompositeConfigProvider,
        *,
        max_concurrent_executions: int = 32,
        queue_wait_seconds: float = 3.0,
        policy_refresh_ttl_seconds: float = 2.0,
    ):
        self.config_provider = config_provider
        self.profile_resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="default")
        self.router = BrokerRuntimeRouter(profile_resolver=self.profile_resolver)
        self._status: Dict[str, dict] = {}
        self._refresh_lock = asyncio.Lock()
        self._refresh_ttl_seconds = max(0.1, float(policy_refresh_ttl_seconds))
        self._last_refresh_at = 0.0
        self._execute_semaphore = asyncio.Semaphore(max(1, int(max_concurrent_executions)))
        self._queue_wait_seconds = max(0.1, float(queue_wait_seconds))

    async def refresh_policy(self) -> None:
        now = time.monotonic()
        if (now - self._last_refresh_at) < self._refresh_ttl_seconds:
            return
        async with self._refresh_lock:
            now = time.monotonic()
            if (now - self._last_refresh_at) < self._refresh_ttl_seconds:
                return
            snapshot = await self.config_provider.load()
            if snapshot.data:
                resolver = PolicyProfileResolver.parse(snapshot.data, revision=snapshot.revision)
                self.profile_resolver = resolver
                self.router = BrokerRuntimeRouter(profile_resolver=self.profile_resolver)
            self._last_refresh_at = time.monotonic()

    async def Execute(self, request, context):  # noqa: N802
        await self.refresh_policy()
        acquired = False
        try:
            await asyncio.wait_for(
                self._execute_semaphore.acquire(),
                timeout=self._queue_wait_seconds,
            )
            acquired = True
        except TimeoutError:
            return _overloaded_response(
                workspace_id=request.workspace_id,
                task_id=request.task_id,
                policy_profile=request.policy.policy_profile or "shell-tool-default",
            )

        execution_id = f"exec-{uuid.uuid4().hex[:16]}"
        limits_override = _to_limits(request.policy.limits_override)
        payload_type = "command" if request.HasField("command") else "python"
        command = request.command.command if request.HasField("command") else None
        code = request.python.code if request.HasField("python") else None
        language = request.python.language if request.HasField("python") else "python"
        env = dict(request.command.env) if request.HasField("command") else {}

        try:
            result = await self.router.execute(
                workspace_id=request.workspace_id,
                task_id=request.task_id,
                user_id=request.user_id,
                workflow_type=request.workflow_type or request.tool_name,
                tool_name=request.tool_name,
                profile_name=request.policy.policy_profile or "shell-tool-default",
                payload_type=payload_type,
                command=command,
                code=code,
                language=language,
                labels=dict(request.labels),
                env=env,
                limits_override=limits_override,
            )
            self._status[execution_id] = result
            errors = [
                ErrorMetadata(code=str(item.get("code", "")), message=str(item.get("message", "")))
                for item in result.get("errors", [])
                if isinstance(item, dict)
            ]
            return ExecuteResponse(
                execution_id=execution_id,
                workspace_id=result["workspace_id"],
                task_id=result["task_id"],
                runtime=result["runtime"],
                status=result["status"],
                success=result["success"],
                exit_code=int(result.get("exit_code") or 0),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                duration_ms=int(result.get("duration_ms") or 0),
                started_at_ms=int(result.get("started_at_ms") or 0),
                completed_at_ms=int(result.get("completed_at_ms") or 0),
                routing=RoutingMetadata(**result.get("routing", {})),
                sandbox=SandboxMetadata(**result.get("sandbox", {})),
                errors=errors,
            )
        finally:
            if acquired:
                self._execute_semaphore.release()

    async def Start(self, request, context):  # noqa: N802
        execution_id = f"exec-{uuid.uuid4().hex[:16]}"
        snapshot_id = f"snap-{uuid.uuid4().hex[:16]}"
        self._status[execution_id] = {
            "state": "SNAPSHOT_CREATED",
            "snapshot_id": snapshot_id,
        }
        return ExecutionProgress(
            execution_id=execution_id,
            snapshot_id=snapshot_id,
            state="SNAPSHOT_CREATED",
            details_json=json.dumps({"profile": request.execute.policy.policy_profile}),
        )

    async def Resume(self, request, context):  # noqa: N802
        execution_id = f"exec-{uuid.uuid4().hex[:16]}"
        self._status[execution_id] = {"state": "RESUMED", "snapshot_id": request.snapshot_id}
        return ExecutionProgress(
            execution_id=execution_id,
            snapshot_id=request.snapshot_id,
            state="RESUMED",
            details_json=json.dumps({"snapshot_id": request.snapshot_id}),
        )

    async def GetStatus(self, request, context):  # noqa: N802
        status = self._status.get(request.execution_id, {"state": "UNKNOWN"})
        return StatusResponse(
            execution_id=request.execution_id,
            state=status.get("state", "UNKNOWN"),
            details_json=json.dumps(status, ensure_ascii=False),
        )

    async def Cancel(self, request, context):  # noqa: N802
        if request.execution_id in self._status:
            self._status[request.execution_id]["state"] = "CANCELLED"
            return CancelResponse(
                execution_id=request.execution_id,
                cancelled=True,
                message="cancelled",
            )
        return CancelResponse(
            execution_id=request.execution_id,
            cancelled=False,
            message="not-found",
        )

    async def Health(self, request, context):  # noqa: N802
        await self.refresh_policy()
        runtime_ready, reason = check_sandbox_runtime_ready()
        return HealthResponse(
            healthy=runtime_ready,
            status="healthy" if runtime_ready else "degraded",
            sandbox_runtime=self.profile_resolver.model.defaults.container.runtime,
            runtime_ready=runtime_ready,
            runtime_reason=reason,
            config_revision=self.profile_resolver.revision,
        )


def _to_limits(limits_message) -> Optional[LimitsModel]:
    if limits_message is None:
        return None
    if (
        limits_message.timeout_seconds == 0
        and limits_message.memory_mb == 0
        and limits_message.cpu_seconds == 0
        and limits_message.max_processes == 0
        and not limits_message.allow_network
    ):
        return None
    return LimitsModel(
        timeout_seconds=int(limits_message.timeout_seconds or 0) or 60,
        memory_mb=int(limits_message.memory_mb or 0) or 512,
        cpu_seconds=int(limits_message.cpu_seconds or 0) or 30,
        max_processes=int(limits_message.max_processes or 0) or 64,
        allow_network=bool(limits_message.allow_network),
    )


def _overloaded_response(*, workspace_id: str, task_id: str, policy_profile: str) -> ExecuteResponse:
    now_ms = int(time.time() * 1000)
    return ExecuteResponse(
        execution_id=f"exec-{uuid.uuid4().hex[:16]}",
        workspace_id=workspace_id,
        task_id=task_id,
        runtime="none",
        status="overloaded",
        success=False,
        exit_code=1,
        stdout="",
        stderr="sandbox broker queue timeout: overloaded",
        duration_ms=0,
        started_at_ms=now_ms,
        completed_at_ms=now_ms,
        routing=RoutingMetadata(
            selected_runtime="none",
            eligibility_reason="overloaded",
            fallback_used=False,
            fallback_reason="",
        ),
        sandbox=SandboxMetadata(
            runtime="runsc",
            image="",
            policy_profile=policy_profile,
        ),
        errors=[ErrorMetadata(code="BROKER_OVERLOADED", message="queue wait timeout")],
    )
