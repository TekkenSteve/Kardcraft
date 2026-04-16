"""Projects durable outbox events to Redis streams."""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime
from typing import Optional

from ..db.workflow_event_outbox_repository import (
    OutboxEvent,
    WorkflowEventOutboxRepository,
    workflow_event_outbox_repo,
)
from ..services.redis import RedisClient, redis as default_redis
from ..utils.logger import logger


class WorkflowEventProjector:
    """Continuously projects pending outbox events into Redis streams."""

    def __init__(
        self,
        *,
        redis_client: RedisClient = default_redis,
        repository: WorkflowEventOutboxRepository = workflow_event_outbox_repo,
        batch_size: int = 200,
        poll_interval_s: float = 0.2,
        stale_claim_s: int = 30,
        projector_id: Optional[str] = None,
    ) -> None:
        self._redis = redis_client
        self._repo = repository
        self._batch_size = max(1, batch_size)
        self._poll_interval_s = max(0.05, poll_interval_s)
        self._stale_claim_s = max(5, stale_claim_s)
        self._projector_id = projector_id or f"projector-{socket.gethostname()}-{id(self)}"
        self._stop_event = asyncio.Event()
        self._quiescing = False

    async def bootstrap(self) -> None:
        await self._repo.bootstrap_schema()
        await self._redis.initialize_async()

    async def begin_quiesce(self) -> None:
        self._quiescing = True
        self._stop_event.set()

    async def run(self) -> None:
        logger.info("workflow event projector started", projector_id=self._projector_id)
        await self.bootstrap()

        while not self._stop_event.is_set():
            try:
                requeued = await self._repo.requeue_stale_claims(stale_seconds=self._stale_claim_s)
                if requeued:
                    logger.warning("requeued stale projector claims", count=requeued)

                events = await self._repo.claim_pending_events(
                    projector_id=self._projector_id,
                    batch_size=self._batch_size,
                )
                if not events:
                    await asyncio.sleep(self._poll_interval_s)
                    continue

                logger.info(
                    "projector claimed outbox batch",
                    projector_id=self._projector_id,
                    batch_size=len(events),
                )

                # Keep task-level ordering strict in projector process.
                events.sort(key=lambda item: (item.task_id, item.event_seq))
                for event in events:
                    try:
                        await self._project_event(event)
                        await self._repo.ack_projected(
                            event_id=event.id,
                            projector_id=self._projector_id,
                        )
                    except Exception as exc:
                        logger.error(
                            "failed to project outbox event",
                            event_id=event.id,
                            task_id=event.task_id,
                            event_type=event.event_type,
                            error=str(exc),
                        )
                        await self._repo.nack_projecting(
                            event_id=event.id,
                            projector_id=self._projector_id,
                            error=str(exc),
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "projector loop iteration failed",
                    projector_id=self._projector_id,
                    error=str(exc),
                )
                await asyncio.sleep(1.0)

        await self.drain(timeout_s=10.0)
        logger.info("workflow event projector stopped", projector_id=self._projector_id)

    async def drain(self, timeout_s: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            backlog = await self._repo.pending_count()
            if backlog <= 0:
                return
            if asyncio.get_running_loop().time() >= deadline:
                logger.warning("projector drain timed out", backlog=backlog)
                return
            events = await self._repo.claim_pending_events(
                projector_id=self._projector_id,
                batch_size=self._batch_size,
            )
            if not events:
                await asyncio.sleep(0.1)
                continue
            events.sort(key=lambda item: (item.task_id, item.event_seq))
            for event in events:
                try:
                    await self._project_event(event)
                    await self._repo.ack_projected(
                        event_id=event.id,
                        projector_id=self._projector_id,
                    )
                except Exception as exc:
                    logger.error(
                        "failed to project outbox event during drain",
                        event_id=event.id,
                        task_id=event.task_id,
                        error=str(exc),
                    )
                    await self._repo.nack_projecting(
                        event_id=event.id,
                        projector_id=self._projector_id,
                        error=str(exc),
                    )
                    await asyncio.sleep(0.1)

    async def close(self) -> None:
        await self._redis.close()

    async def _project_event(self, event: OutboxEvent) -> None:
        stream_key = f"stream:events:{event.task_id}"
        payload = event.payload if isinstance(event.payload, dict) else {}
        message = str(payload.get("message") or "")

        fields = {
            "task_id": event.task_id,
            "event_type": event.event_type,
            "data": json.dumps(payload, ensure_ascii=False, default=str),
            "message": message,
            "timestamp": self._to_iso(event.occurred_at),
            "event_seq": str(event.event_seq),
        }
        workspace_id = str(payload.get("workspace_id") or payload.get("session_id") or "").strip()
        if workspace_id:
            fields["workspace_id"] = workspace_id
            fields["session_id"] = workspace_id

        await self._redis.stream_add(
            stream_key=stream_key,
            fields=fields,
            maxlen=1000,
            approximate=False,
            fail_silently=False,
        )

    def _to_iso(self, value: datetime) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return datetime.utcnow().isoformat()


__all__ = ["WorkflowEventProjector"]
