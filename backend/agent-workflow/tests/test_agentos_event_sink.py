from __future__ import annotations

import httpx
import pytest

from kardcraft.services.agentos_event_sink import (
    AgentOSEventContext,
    AgentOSEventDeliveryError,
    AgentOSEventSink,
)
from kardcraft.services.hydra_client_credentials import ClientCredentialsConfig


@pytest.mark.asyncio
async def test_event_sink_requires_source_identity() -> None:
    sink = AgentOSEventSink(
        task_orchestrator_base_url="http://task-orchestrator",
        client_credentials=ClientCredentialsConfig(
            token_url="http://hydra/token",
            client_id="agent-workflow",
            client_secret="secret",
            audience="task-orchestrator",
            scope="task.events.write",
        ),
    )
    context = AgentOSEventContext(
        task_id="task-1",
        session_id="session-1",
        user_id="user-1",
        conversation_run_id="conversation-run-1",
        project_id="session-1",
        workflow_id="task-1",
        run_id="task-1",
        correlation_id="request-1",
    )

    with pytest.raises(ValueError, match="event_id is required"):
        await sink.emit(
            ctx=context,
            event_type="WORKFLOW_PROGRESS",
            payload={},
            event_id="",
            sequence=1,
            timestamp="2026-07-15T00:00:00Z",
        )


@pytest.mark.asyncio
async def test_event_sink_includes_rejection_body(monkeypatch) -> None:
    sink = AgentOSEventSink(
        task_orchestrator_base_url="http://task-orchestrator",
        client_credentials=ClientCredentialsConfig(
            token_url="http://hydra/token",
            client_id="agent-workflow",
            client_secret="secret",
            audience="task-orchestrator",
            scope="task.events.write",
        ),
    )
    context = AgentOSEventContext(
        task_id="task-1",
        session_id="session-1",
        user_id="user-1",
        conversation_run_id="conversation-run-1",
        project_id="session-1",
        workflow_id="task-1",
        run_id="task-1",
        correlation_id="request-1",
    )

    async def fake_token(_client) -> str:
        return "token"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **_kwargs):
            request = httpx.Request("POST", url)
            return httpx.Response(400, request=request, text="reject execution event: idempotency mismatch")

    monkeypatch.setattr(sink._tokens, "token", fake_token)
    monkeypatch.setattr("kardcraft.services.agentos_event_sink.httpx.AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(AgentOSEventDeliveryError, match="idempotency mismatch"):
        await sink.emit(
            ctx=context,
            event_type="NODE_STARTED",
            payload={"node_name": "planner"},
            event_id="event-1",
            sequence=1,
            timestamp="2026-07-26T00:00:00Z",
        )
