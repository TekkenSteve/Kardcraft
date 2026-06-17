from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

import httpx
from temporalio import activity

from .agentos_workflow import EventInput


@dataclass(frozen=True)
class AgentOSEventConfig:
    task_orchestrator_base_url: str


class AgentOSEventActivities:
    def __init__(self, config: AgentOSEventConfig) -> None:
        self._config = config

    @activity.defn(name="emit_agentos_event")
    async def emit_agentos_event(self, event: EventInput) -> None:
        base_url = self._config.task_orchestrator_base_url.rstrip("/")
        if not base_url:
            raise ValueError("task_orchestrator_base_url is required")
        event_id = event.event_id or f"evt-{uuid4()}"
        payload = dict(event.payload or {})
        payload.setdefault("task_id", event.run_id)
        payload.setdefault("workflow_id", event.run_id)
        payload.setdefault("run_id", event.run_id)
        payload.setdefault("session_id", event.thread_id)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/api/v1/agentos/runs/{event.run_id}/events",
                headers={"X-User-Id": event.user_id or "system"},
                json={
                    "event_id": event_id,
                    "run_id": event.run_id,
                    "thread_id": event.thread_id,
                    "event_type": event.event_type,
                    "source": event.source,
                    "payload": payload,
                },
            )
            response.raise_for_status()


def agentos_event_activities_from_env() -> AgentOSEventActivities:
    base_url = os.getenv("TASK_ORCHESTRATOR_BASE_URL", "").strip()
    return AgentOSEventActivities(
        AgentOSEventConfig(task_orchestrator_base_url=base_url),
    )
