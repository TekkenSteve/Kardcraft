"""Workflow execution control gate shared by agent activities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text

from ..db.postgres import postgres


TASK_STATUS_PENDING: Final[str] = "pending"
TASK_STATUS_QUEUED: Final[str] = "queued"
TASK_STATUS_RUNNING: Final[str] = "running"
TASK_STATUS_PAUSED: Final[str] = "paused"
TASK_STATUS_CANCELLED: Final[str] = "cancelled"
TASK_STATUS_CANCELED: Final[str] = "canceled"

ACTIVE_STATUSES: Final[set[str]] = {
    TASK_STATUS_PENDING,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
}
CANCELLED_STATUSES: Final[set[str]] = {
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CANCELED,
}


class WorkflowCancelledByControl(asyncio.CancelledError):
    """Raised when the shared task control state requests cancellation."""


@dataclass(frozen=True)
class WorkflowControlState:
    status: str

    @property
    def is_paused(self) -> bool:
        return self.status == TASK_STATUS_PAUSED

    @property
    def is_cancelled(self) -> bool:
        return self.status in CANCELLED_STATUSES


class WorkflowControlGate:
    """Polls durable task state and blocks graph progression while paused."""

    def __init__(self, *, poll_interval_s: float = 1.0) -> None:
        self._poll_interval_s = poll_interval_s

    async def get_state(self, task_id: str) -> WorkflowControlState:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return WorkflowControlState(status=TASK_STATUS_RUNNING)

        async with postgres.session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT LOWER(COALESCE(status::text, 'running')) AS status
                    FROM kc_tasks
                    WHERE task_id = :task_id
                    """
                ),
                {"task_id": normalized_task_id},
            )
            status = result.scalar_one_or_none()

        normalized_status = str(status or TASK_STATUS_RUNNING).strip().lower()
        if not normalized_status:
            normalized_status = TASK_STATUS_RUNNING
        return WorkflowControlState(status=normalized_status)

    async def wait_until_runnable(self, task_id: str) -> WorkflowControlState:
        while True:
            state = await self.get_state(task_id)
            if state.is_cancelled:
                raise WorkflowCancelledByControl(f"workflow cancelled: {task_id}")
            if not state.is_paused:
                return state
            await asyncio.sleep(self._poll_interval_s)
