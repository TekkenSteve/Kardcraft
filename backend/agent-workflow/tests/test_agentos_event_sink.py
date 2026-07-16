from __future__ import annotations

import pytest

from kardcraft.services.agentos_event_sink import AgentOSEventContext, AgentOSEventSink
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
