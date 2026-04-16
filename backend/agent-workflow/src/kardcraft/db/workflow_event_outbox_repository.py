"""Repository for durable workflow event outbox and lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .postgres import postgres


class PublishRejectedError(RuntimeError):
    """Raised when lifecycle policy rejects an event publish attempt."""


@dataclass
class OutboxEvent:
    id: int
    task_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    workflow_id: str
    run_id: str
    event_seq: int
    event_type: str
    channel: str
    payload: dict[str, Any]
    occurred_at: datetime


class WorkflowEventOutboxRepository:
    """Postgres-backed source of truth for realtime workflow events."""

    async def bootstrap_schema(self) -> None:
        """Create durable event tables if absent."""
        async with postgres.session() as session:
            await session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_event_outbox (
                        id BIGSERIAL PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        session_id TEXT,
                        user_id TEXT,
                        workflow_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        event_seq BIGINT NOT NULL,
                        event_type TEXT NOT NULL,
                        channel TEXT NOT NULL DEFAULT 'timeline',
                        payload JSONB NOT NULL,
                        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        status TEXT NOT NULL DEFAULT 'pending',
                        projector_id TEXT,
                        claimed_at TIMESTAMPTZ,
                        projected_at TIMESTAMPTZ,
                        attempt_count INT NOT NULL DEFAULT 0,
                        last_error TEXT,
                        CONSTRAINT uq_outbox_task_seq UNIQUE (task_id, event_seq),
                        CONSTRAINT ck_outbox_status CHECK (status in ('pending', 'projecting', 'projected'))
                    )
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_outbox_pending
                    ON workflow_event_outbox(status, id)
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_outbox_task_seq
                    ON workflow_event_outbox(task_id, event_seq)
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS task_lifecycle_state (
                        task_id TEXT PRIMARY KEY,
                        phase TEXT NOT NULL,
                        accepting_progress BOOLEAN NOT NULL DEFAULT TRUE,
                        accepting_usage BOOLEAN NOT NULL DEFAULT TRUE,
                        terminal_event_emitted BOOLEAN NOT NULL DEFAULT FALSE,
                        done_event_emitted BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT ck_task_lifecycle_phase
                        CHECK (phase in ('running', 'paused', 'cancelling', 'terminal'))
                    )
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS task_event_seq (
                        task_id TEXT PRIMARY KEY,
                        next_seq BIGINT NOT NULL
                    )
                    """
                )
            )

    async def mark_running(self, task_id: str) -> None:
        await self._upsert_task_state(
            task_id=task_id,
            phase="running",
            accepting_progress=True,
            accepting_usage=True,
        )

    async def mark_paused(self, task_id: str) -> None:
        await self._upsert_task_state(
            task_id=task_id,
            phase="paused",
            accepting_progress=False,
            accepting_usage=False,
        )

    async def mark_cancelling(self, task_id: str) -> None:
        await self._upsert_task_state(
            task_id=task_id,
            phase="cancelling",
            accepting_progress=False,
            accepting_usage=False,
        )

    async def mark_terminal(self, task_id: str) -> None:
        await self._upsert_task_state(
            task_id=task_id,
            phase="terminal",
            accepting_progress=False,
            accepting_usage=False,
        )

    async def _upsert_task_state(
        self,
        *,
        task_id: str,
        phase: str,
        accepting_progress: bool,
        accepting_usage: bool,
    ) -> None:
        async with postgres.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO task_lifecycle_state (
                        task_id,
                        phase,
                        accepting_progress,
                        accepting_usage,
                        updated_at
                    ) VALUES (
                        :task_id,
                        :phase,
                        :accepting_progress,
                        :accepting_usage,
                        NOW()
                    )
                    ON CONFLICT (task_id)
                    DO UPDATE SET
                        phase = EXCLUDED.phase,
                        accepting_progress = EXCLUDED.accepting_progress,
                        accepting_usage = EXCLUDED.accepting_usage,
                        updated_at = NOW()
                    """
                ),
                {
                    "task_id": task_id,
                    "phase": phase,
                    "accepting_progress": accepting_progress,
                    "accepting_usage": accepting_usage,
                },
            )

    async def append_event(
        self,
        *,
        task_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
        workflow_id: str,
        run_id: str,
        event_type: str,
        channel: str,
        payload: dict[str, Any],
    ) -> Optional[int]:
        """Persist event and return event_seq. Returns None for idempotent duplicates."""
        async with postgres.session() as session:
            await self._ensure_task_state_exists(session=session, task_id=task_id)
            gate = await session.execute(
                text(
                    """
                    SELECT
                        phase,
                        accepting_progress,
                        accepting_usage,
                        terminal_event_emitted,
                        done_event_emitted
                    FROM task_lifecycle_state
                    WHERE task_id = :task_id
                    FOR UPDATE
                    """
                ),
                {"task_id": task_id},
            )
            state = gate.mappings().one()

            if channel == "progress" and not bool(state["accepting_progress"]):
                raise PublishRejectedError(
                    f"progress publish rejected by lifecycle gate: task_id={task_id} phase={state['phase']}"
                )
            if channel == "usage" and not bool(state["accepting_usage"]):
                raise PublishRejectedError(
                    f"usage publish rejected by lifecycle gate: task_id={task_id} phase={state['phase']}"
                )

            if channel == "terminal" and bool(state["terminal_event_emitted"]):
                return None
            if channel == "done" and bool(state["done_event_emitted"]):
                return None

            seq_result = await session.execute(
                text(
                    """
                    INSERT INTO task_event_seq (task_id, next_seq)
                    VALUES (:task_id, 1)
                    ON CONFLICT (task_id)
                    DO UPDATE SET next_seq = task_event_seq.next_seq + 1
                    RETURNING next_seq
                    """
                ),
                {"task_id": task_id},
            )
            event_seq = int(seq_result.scalar_one())

            await session.execute(
                text(
                    """
                    INSERT INTO workflow_event_outbox (
                        task_id,
                        session_id,
                        user_id,
                        workflow_id,
                        run_id,
                        event_seq,
                        event_type,
                        channel,
                        payload,
                        occurred_at,
                        status,
                        attempt_count
                    ) VALUES (
                        :task_id,
                        :session_id,
                        :user_id,
                        :workflow_id,
                        :run_id,
                        :event_seq,
                        :event_type,
                        :channel,
                        CAST(:payload AS JSONB),
                        NOW(),
                        'pending',
                        0
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "event_seq": event_seq,
                    "event_type": event_type,
                    "channel": channel,
                    "payload": self._to_json(payload),
                },
            )

            if channel == "terminal":
                await session.execute(
                    text(
                        """
                        UPDATE task_lifecycle_state
                        SET
                            terminal_event_emitted = TRUE,
                            phase = 'terminal',
                            accepting_progress = FALSE,
                            accepting_usage = FALSE,
                            updated_at = NOW()
                        WHERE task_id = :task_id
                        """
                    ),
                    {"task_id": task_id},
                )
            elif channel == "done":
                await session.execute(
                    text(
                        """
                        UPDATE task_lifecycle_state
                        SET
                            done_event_emitted = TRUE,
                            phase = 'terminal',
                            accepting_progress = FALSE,
                            accepting_usage = FALSE,
                            updated_at = NOW()
                        WHERE task_id = :task_id
                        """
                    ),
                    {"task_id": task_id},
                )

            return event_seq

    async def claim_pending_events(
        self,
        *,
        projector_id: str,
        batch_size: int,
    ) -> list[OutboxEvent]:
        async with postgres.session() as session:
            rows = await session.execute(
                text(
                    """
                    WITH to_claim AS (
                        SELECT id
                        FROM workflow_event_outbox
                        WHERE status = 'pending'
                        ORDER BY id
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE workflow_event_outbox o
                    SET
                        status = 'projecting',
                        projector_id = :projector_id,
                        claimed_at = NOW(),
                        attempt_count = o.attempt_count + 1
                    FROM to_claim
                    WHERE o.id = to_claim.id
                    RETURNING
                        o.id,
                        o.task_id,
                        o.session_id,
                        o.user_id,
                        o.workflow_id,
                        o.run_id,
                        o.event_seq,
                        o.event_type,
                        o.channel,
                        o.payload,
                        o.occurred_at
                    """
                ),
                {"projector_id": projector_id, "batch_size": batch_size},
            )
            return [
                OutboxEvent(
                    id=int(row.id),
                    task_id=str(row.task_id),
                    session_id=row.session_id,
                    user_id=row.user_id,
                    workflow_id=str(row.workflow_id),
                    run_id=str(row.run_id),
                    event_seq=int(row.event_seq),
                    event_type=str(row.event_type),
                    channel=str(row.channel),
                    payload=row.payload if isinstance(row.payload, dict) else {},
                    occurred_at=row.occurred_at,
                )
                for row in rows.mappings().all()
            ]

    async def ack_projected(self, *, event_id: int, projector_id: str) -> None:
        async with postgres.session() as session:
            await session.execute(
                text(
                    """
                    UPDATE workflow_event_outbox
                    SET
                        status = 'projected',
                        projected_at = NOW(),
                        last_error = NULL
                    WHERE
                        id = :event_id
                        AND status = 'projecting'
                        AND projector_id = :projector_id
                    """
                ),
                {"event_id": event_id, "projector_id": projector_id},
            )

    async def nack_projecting(
        self,
        *,
        event_id: int,
        projector_id: str,
        error: str,
    ) -> None:
        async with postgres.session() as session:
            await session.execute(
                text(
                    """
                    UPDATE workflow_event_outbox
                    SET
                        status = 'pending',
                        projector_id = NULL,
                        claimed_at = NULL,
                        last_error = :error
                    WHERE
                        id = :event_id
                        AND status = 'projecting'
                        AND projector_id = :projector_id
                    """
                ),
                {
                    "event_id": event_id,
                    "projector_id": projector_id,
                    "error": error[:2000],
                },
            )

    async def requeue_stale_claims(self, *, stale_seconds: int) -> int:
        async with postgres.session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE workflow_event_outbox
                    SET
                        status = 'pending',
                        projector_id = NULL,
                        claimed_at = NULL,
                        last_error = COALESCE(last_error, 'stale claim requeued')
                    WHERE
                        status = 'projecting'
                        AND claimed_at < NOW() - (:stale_seconds * INTERVAL '1 second')
                    """
                ),
                {"stale_seconds": stale_seconds},
            )
            return int(result.rowcount or 0)

    async def pending_count(self) -> int:
        async with postgres.session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM workflow_event_outbox
                    WHERE status IN ('pending', 'projecting')
                    """
                )
            )
            return int(result.scalar_one() or 0)

    async def _ensure_task_state_exists(self, *, session: AsyncSession, task_id: str) -> None:
        await session.execute(
            text(
                """
                INSERT INTO task_lifecycle_state (
                    task_id,
                    phase,
                    accepting_progress,
                    accepting_usage,
                    terminal_event_emitted,
                    done_event_emitted,
                    updated_at
                ) VALUES (
                    :task_id,
                    'running',
                    TRUE,
                    TRUE,
                    FALSE,
                    FALSE,
                    NOW()
                )
                ON CONFLICT (task_id) DO NOTHING
                """
            ),
            {"task_id": task_id},
        )

    def _to_json(self, payload: dict[str, Any]) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False, default=str)


workflow_event_outbox_repo = WorkflowEventOutboxRepository()


__all__ = [
    "OutboxEvent",
    "PublishRejectedError",
    "WorkflowEventOutboxRepository",
    "workflow_event_outbox_repo",
]
