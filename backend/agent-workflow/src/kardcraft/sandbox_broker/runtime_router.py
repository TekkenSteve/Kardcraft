"""Sandbox broker runtime router."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from .container_runtime import ContainerLimits, ContainerRequest, ContainerRuntime
from .monty_runtime import MontyRuntime
from .policy_profiles import LimitsModel, PolicyProfileResolver


class BrokerRuntimeRouter:
    def __init__(
        self,
        *,
        profile_resolver: PolicyProfileResolver,
        monty_runtime: Optional[MontyRuntime] = None,
        container_runtime: Optional[ContainerRuntime] = None,
    ):
        self.profile_resolver = profile_resolver
        self.monty_runtime = monty_runtime or MontyRuntime()
        self.container_runtime = container_runtime or ContainerRuntime(
            image=profile_resolver.model.defaults.container.image,
            runtime=profile_resolver.model.defaults.container.runtime,
        )

    async def execute(
        self,
        *,
        workspace_id: str,
        task_id: str,
        user_id: str,
        workflow_type: str,
        tool_name: str,
        profile_name: str,
        payload_type: str,
        command: Optional[str] = None,
        code: Optional[str] = None,
        language: str = "python",
        labels: Optional[dict[str, str]] = None,
        env: Optional[dict[str, str]] = None,
        limits_override: Optional[LimitsModel] = None,
    ) -> dict[str, Any]:
        resolved = self.profile_resolver.resolve(profile_name, limits_override=limits_override)
        profile = resolved.profile
        routing = {
            "selected_runtime": "container",
            "eligibility_reason": "non-eligible",
            "fallback_used": False,
            "fallback_reason": "",
        }

        if payload_type != profile.payload_type:
            return self._rejected(
                workspace_id,
                task_id,
                profile_name,
                code="BROKER_PAYLOAD_PROFILE_MISMATCH",
                message=f"payload_type={payload_type} not allowed for profile={profile_name}",
            )

        if profile.runtime_order and profile.runtime_order[0] == "monty":
            if payload_type == "python" and profile.monty.enabled:
                routing["selected_runtime"] = "monty"
                routing["eligibility_reason"] = "eligible"
                try:
                    started = int(time.time() * 1000)
                    inputs = {}
                    output = await self.monty_runtime.run(
                        code=str(code or ""),
                        inputs=inputs,
                        input_keys=[],
                        allow_functions=profile.monty.external_functions_allowlist,
                    )
                    completed = int(time.time() * 1000)
                    return {
                        "workspace_id": workspace_id,
                        "task_id": task_id,
                        "runtime": "monty",
                        "status": "succeeded",
                        "success": True,
                        "exit_code": 0,
                        "stdout": str(output),
                        "stderr": "",
                        "duration_ms": max(0, completed - started),
                        "started_at_ms": started,
                        "completed_at_ms": completed,
                        "routing": routing,
                        "sandbox": {
                            "runtime": resolved.container.runtime,
                            "image": resolved.container.image,
                            "policy_profile": profile_name,
                        },
                    }
                except Exception as exc:
                    routing["fallback_used"] = True
                    routing["fallback_reason"] = str(exc)

        result = await self._execute_container(
            workspace_id=workspace_id,
            task_id=task_id,
            user_id=user_id,
            workflow_type=workflow_type,
            command=command,
            code=code,
            language=language,
            env=env or {},
            limits=resolved.limits,
            routing=routing,
            profile_name=profile_name,
        )
        return result

    async def _execute_container(
        self,
        *,
        workspace_id: str,
        task_id: str,
        user_id: str,
        workflow_type: str,
        command: Optional[str],
        code: Optional[str],
        language: str,
        env: dict[str, str],
        limits: LimitsModel,
        routing: dict[str, Any],
        profile_name: str,
    ) -> dict[str, Any]:
        req = ContainerRequest(
            workspace_id=workspace_id,
            task_id=task_id,
            language=language,
            code=code,
            command=command,
            env=env,
        )
        result = await self.container_runtime.execute(
            req,
            ContainerLimits(
                timeout_seconds=limits.timeout_seconds,
                memory_mb=limits.memory_mb,
                cpu_seconds=limits.cpu_seconds,
                max_processes=limits.max_processes,
                allow_network=limits.allow_network,
            ),
        )
        metadata = result.metadata or {}
        return {
            "workspace_id": workspace_id,
            "task_id": task_id,
            "runtime": "container",
            "status": "succeeded" if result.success else "failed",
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "started_at_ms": result.started_at_ms,
            "completed_at_ms": result.completed_at_ms,
            "routing": routing,
            "sandbox": {
                "runtime": str(metadata.get("sandbox_runtime", "runsc")),
                "image": str(metadata.get("image", "")),
                "policy_profile": profile_name,
            },
        }

    def _rejected(
        self,
        workspace_id: str,
        task_id: str,
        profile_name: str,
        *,
        code: str,
        message: str,
    ) -> dict[str, Any]:
        now = int(time.time() * 1000)
        return {
            "workspace_id": workspace_id,
            "task_id": task_id,
            "runtime": "none",
            "status": "rejected",
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": message,
            "duration_ms": 0,
            "started_at_ms": now,
            "completed_at_ms": now,
            "routing": {
                "selected_runtime": "none",
                "eligibility_reason": "rejected",
                "fallback_used": False,
                "fallback_reason": "",
            },
            "sandbox": {
                "runtime": "runsc",
                "image": "",
                "policy_profile": profile_name,
            },
            "errors": [{"code": code, "message": message}],
        }

    @staticmethod
    def to_json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)
