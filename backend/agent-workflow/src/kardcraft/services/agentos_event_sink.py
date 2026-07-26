"""AgentOS event sink for Kardcraft task-orchestrator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

from .hydra_client_credentials import (
    ClientCredentialsConfig,
    ClientCredentialsTokenProvider,
)


class AgentOSEventDeliveryError(RuntimeError):
    """An execution event was rejected by task-orchestrator."""


@dataclass(frozen=True)
class AgentOSEventContext:
    task_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    conversation_run_id: str
    project_id: str
    workflow_id: str
    run_id: str
    correlation_id: str


class AgentOSEventSink:
    def __init__(
        self,
        *,
        task_orchestrator_base_url: str,
        client_credentials: ClientCredentialsConfig,
    ) -> None:
        base_url = task_orchestrator_base_url.rstrip("/")
        if not base_url:
            raise ValueError("task_orchestrator_base_url is required")
        self._base_url = base_url
        self._tokens = ClientCredentialsTokenProvider(client_credentials)

    @classmethod
    def from_env(cls) -> "AgentOSEventSink":
        base_url = os.getenv("TASK_ORCHESTRATOR_BASE_URL", "").strip()
        return cls(
            task_orchestrator_base_url=base_url,
            client_credentials=ClientCredentialsConfig(
                token_url=os.getenv("HYDRA_TOKEN_URL", "").strip(),
                client_id=os.getenv("AGENT_WORKFLOW_OAUTH_CLIENT_ID", "").strip(),
                client_secret=os.getenv("AGENT_WORKFLOW_OAUTH_CLIENT_SECRET", "").strip(),
                audience=os.getenv("HYDRA_EVENT_AUDIENCE", "").strip(),
                scope="task.events.write",
            ),
        )

    async def emit(
        self,
        *,
        ctx: AgentOSEventContext,
        event_type: str,
        payload: dict[str, Any],
        event_id: str,
        sequence: int,
        timestamp: str,
    ) -> None:
        event_id = str(event_id or "").strip()
        if not event_id:
            raise ValueError("event_id is required")
        if int(sequence) <= 0:
            raise ValueError("sequence must be positive")
        timestamp = str(timestamp or "").strip()
        if not timestamp:
            raise ValueError("timestamp is required")
        normalized_payload = dict(payload or {})
        normalized_payload.setdefault("task_id", ctx.task_id)
        normalized_payload.setdefault("workflow_id", ctx.workflow_id)
        normalized_payload.setdefault("run_id", ctx.run_id)
        normalized_payload.setdefault("session_id", ctx.session_id or "")
        normalized_payload.setdefault("workspace_id", ctx.session_id or "")
        normalized_payload.setdefault("correlation_id", ctx.correlation_id)
        normalized_payload.setdefault("event_type", event_type)
        normalized_payload.setdefault("timestamp", timestamp)
        async with httpx.AsyncClient(timeout=10) as client:
            token = await self._tokens.token(client)
            response = await client.post(
                f"{self._base_url}/internal/execution/runs/{ctx.run_id}/events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "event_id": event_id,
                    "run_id": ctx.run_id,
                    "conversation_run_id": ctx.conversation_run_id,
                    "thread_id": ctx.session_id or "",
                    "account_id": ctx.user_id or "",
                    "project_id": ctx.project_id,
                    "event_type": event_type,
                    "source": "kardcraft.agent_workflow.activity",
                    "sequence": sequence,
                    "timestamp": timestamp,
                    "payload": normalized_payload,
                },
            )
            if response.is_error:
                body = response.text.strip()
                raise AgentOSEventDeliveryError(
                    f"task-orchestrator rejected event status={response.status_code} body={body or '<empty>'}"
                )


__all__ = ["AgentOSEventContext", "AgentOSEventDeliveryError", "AgentOSEventSink"]
