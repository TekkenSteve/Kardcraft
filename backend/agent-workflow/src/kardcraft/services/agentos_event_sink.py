"""AgentOS event sink for Kardcraft task-orchestrator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class AgentOSEventContext:
    task_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    workflow_id: str
    run_id: str
    correlation_id: str


class AgentOSEventSink:
    def __init__(self, *, task_orchestrator_base_url: str) -> None:
        base_url = task_orchestrator_base_url.rstrip("/")
        if not base_url:
            raise ValueError("task_orchestrator_base_url is required")
        self._base_url = base_url

    @classmethod
    def from_env(cls) -> "AgentOSEventSink":
        base_url = os.getenv("TASK_ORCHESTRATOR_BASE_URL", "").strip()
        return cls(task_orchestrator_base_url=base_url)

    async def emit(
        self,
        *,
        ctx: AgentOSEventContext,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> None:
        normalized_payload = dict(payload or {})
        normalized_payload.setdefault("task_id", ctx.task_id)
        normalized_payload.setdefault("workflow_id", ctx.workflow_id)
        normalized_payload.setdefault("run_id", ctx.run_id)
        normalized_payload.setdefault("session_id", ctx.session_id or "")
        normalized_payload.setdefault("workspace_id", ctx.session_id or "")
        normalized_payload.setdefault("correlation_id", ctx.correlation_id)
        normalized_payload.setdefault("event_type", event_type)
        normalized_payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self._base_url}/api/v1/agentos/runs/{ctx.run_id}/events",
                headers={"X-User-Id": ctx.user_id or "system"},
                json={
                    "event_id": event_id or f"evt-{uuid4()}",
                    "run_id": ctx.run_id,
                    "thread_id": ctx.session_id or "",
                    "event_type": event_type,
                    "source": "kardcraft.agent_workflow.activity",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": normalized_payload,
                },
            )
            response.raise_for_status()


__all__ = ["AgentOSEventContext", "AgentOSEventSink"]
