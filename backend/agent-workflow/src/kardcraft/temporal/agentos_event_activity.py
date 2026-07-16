from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from temporalio import activity

from ..services.hydra_client_credentials import (
    ClientCredentialsConfig,
    ClientCredentialsTokenProvider,
)
from .agentos_workflow import EventInput


@dataclass(frozen=True)
class AgentOSEventConfig:
    task_orchestrator_base_url: str
    client_credentials: ClientCredentialsConfig


class AgentOSEventActivities:
    def __init__(self, config: AgentOSEventConfig) -> None:
        self._config = config
        self._tokens = ClientCredentialsTokenProvider(config.client_credentials)

    @activity.defn(name="emit_agentos_event")
    async def emit_agentos_event(self, event: EventInput) -> None:
        base_url = self._config.task_orchestrator_base_url.rstrip("/")
        if not base_url:
            raise ValueError("task_orchestrator_base_url is required")
        payload = dict(event.payload or {})
        payload.setdefault("task_id", event.run_id)
        payload.setdefault("workflow_id", event.run_id)
        payload.setdefault("run_id", event.run_id)
        payload.setdefault("session_id", event.thread_id)
        async with httpx.AsyncClient(timeout=10) as client:
            token = await self._tokens.token(client)
            response = await client.post(
                f"{base_url}/internal/execution/runs/{event.run_id}/events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "event_id": event.event_id,
                    "run_id": event.run_id,
                    "thread_id": event.thread_id,
                    "event_type": event.event_type,
                    "source": event.source,
                    "sequence": event.sequence,
                    "timestamp": event.timestamp,
                    "payload": payload,
                },
            )
            response.raise_for_status()


def agentos_event_activities_from_env() -> AgentOSEventActivities:
    base_url = os.getenv("TASK_ORCHESTRATOR_BASE_URL", "").strip()
    config = ClientCredentialsConfig(
        token_url=os.getenv("HYDRA_TOKEN_URL", "").strip(),
        client_id=os.getenv("AGENT_WORKFLOW_OAUTH_CLIENT_ID", "").strip(),
        client_secret=os.getenv("AGENT_WORKFLOW_OAUTH_CLIENT_SECRET", "").strip(),
        audience=os.getenv("HYDRA_EVENT_AUDIENCE", "").strip(),
        scope="task.events.write",
    )
    return AgentOSEventActivities(
        AgentOSEventConfig(task_orchestrator_base_url=base_url, client_credentials=config),
    )
