"""Durable workflow event bus backed by Postgres outbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ..db.workflow_event_outbox_repository import (
    PublishRejectedError,
    WorkflowEventOutboxRepository,
    workflow_event_outbox_repo,
)
from ..utils.logger import logger
from .process_lifecycle import ProcessLifecycleGate


@dataclass
class EventContext:
    task_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    workflow_id: str
    run_id: str


class WorkflowEventBus:
    """High-level event API for activities/workflows."""

    def __init__(
        self,
        *,
        repository: WorkflowEventOutboxRepository = workflow_event_outbox_repo,
        process_gate: Optional[ProcessLifecycleGate] = None,
    ) -> None:
        self._repo = repository
        self._process_gate = process_gate

    async def bootstrap(self) -> None:
        await self._repo.bootstrap_schema()

    async def mark_task_running(self, task_id: str) -> None:
        await self._repo.mark_running(task_id)

    async def mark_task_paused(self, task_id: str) -> None:
        await self._repo.mark_paused(task_id)

    async def mark_task_cancelling(self, task_id: str) -> None:
        await self._repo.mark_cancelling(task_id)

    async def publish_progress(self, *, ctx: EventContext, payload: dict[str, Any]) -> bool:
        return await self._publish(
            ctx=ctx,
            event_type=str(payload.get("event_type") or payload.get("type") or "WORKFLOW_PROGRESS"),
            channel="progress",
            payload=payload,
        )

    async def publish_usage(self, *, ctx: EventContext, payload: dict[str, Any]) -> bool:
        return await self._publish(
            ctx=ctx,
            event_type="LLM_USAGE",
            channel="usage",
            payload=payload,
        )

    async def publish_terminal(
        self,
        *,
        ctx: EventContext,
        event_type: str,
        message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        data = dict(payload or {})
        data.setdefault("task_id", ctx.task_id)
        data.setdefault("workspace_id", ctx.session_id or "")
        data.setdefault("session_id", ctx.session_id or "")
        data.setdefault("message", message)
        data.setdefault("timestamp", datetime.utcnow().isoformat())
        accepted = await self._publish(
            ctx=ctx,
            event_type=event_type,
            channel="terminal",
            payload=data,
        )
        if accepted:
            await self._repo.mark_terminal(ctx.task_id)
        return accepted

    async def publish_done(self, *, ctx: EventContext, message: str = "Stream end") -> bool:
        data = {
            "task_id": ctx.task_id,
            "workspace_id": ctx.session_id or "",
            "session_id": ctx.session_id or "",
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        accepted = await self._publish(
            ctx=ctx,
            event_type="done",
            channel="done",
            payload=data,
        )
        if accepted:
            await self._repo.mark_terminal(ctx.task_id)
        return accepted

    async def _publish(
        self,
        *,
        ctx: EventContext,
        event_type: str,
        channel: str,
        payload: dict[str, Any],
    ) -> bool:
        slot_acquired = False
        if self._process_gate is not None:
            slot_acquired = await self._process_gate.try_acquire_publish_slot(channel)
            if not slot_acquired:
                logger.info(
                    "event publish rejected by process phase",
                    task_id=ctx.task_id,
                    event_type=event_type,
                    channel=channel,
                    phase=self._process_gate.phase,
                )
                return False

        try:
            await self._repo.append_event(
                task_id=ctx.task_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                workflow_id=ctx.workflow_id or "unknown-workflow",
                run_id=ctx.run_id or "unknown-run",
                event_type=event_type,
                channel=channel,
                payload=payload,
            )
            return True
        except PublishRejectedError as exc:
            logger.info(
                "event publish rejected by task lifecycle",
                task_id=ctx.task_id,
                event_type=event_type,
                channel=channel,
                error=str(exc),
            )
            return False
        finally:
            if slot_acquired and self._process_gate is not None:
                await self._process_gate.release_publish_slot()


__all__ = ["EventContext", "WorkflowEventBus"]
