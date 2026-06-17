from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import workflow


WORKFLOW_TYPE = "kardcraft.agent_workflow.v1"
STATUS_QUERY = "agentos_status"


@dataclass
class BackendRef:
    kind: str
    name: str


@dataclass
class StartInput:
    run_id: str
    thread_id: str | None = None
    account_id: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
    model_ref: str | None = None
    system_prompt: str | None = None
    user_message: str | None = None
    idempotency_key: str | None = None
    requested_at: str | None = None
    metadata: dict[str, str] | None = None
    backend: BackendRef | None = None
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalInput:
    type: str
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    sent_at: str | None = None


@dataclass
class RunStatus:
    RunID: str
    LifecycleState: str
    Step: int = 0
    Reason: str = ""
    UpdatedAt: str = ""


@dataclass
class EventInput:
    run_id: str
    thread_id: str
    user_id: str
    event_type: str
    source: str
    payload: dict[str, Any]
    event_id: str = ""


@workflow.defn(name=WORKFLOW_TYPE)
class KardcraftAgentOSWorkflow:
    def __init__(self) -> None:
        self._status = RunStatus(RunID="", LifecycleState="created")
        self._start: StartInput | None = None
        self._paused = False
        self._cancelled = False
        self._pending_user_messages: list[SignalInput] = []
        self._pending_runtime_events: list[dict[str, Any]] = []
        self._last_outcome: dict[str, Any] | None = None

    @workflow.run
    async def run(self, start: StartInput) -> RunStatus:
        self._start = start
        self._set_status("running")
        await self._emit("WORKFLOW_STARTED", {"message": "Workflow started"})
        try:
            outcome = await self._execute_initial(start)
        except Exception as exc:
            outcome = self._failed_outcome(start, exc)
            self._last_outcome = outcome
            self._set_status("failed", reason=str(exc))
            await self._emit_terminal("WORKFLOW_FAILED", outcome)
            return self._status
        self._last_outcome = outcome

        while True:
            await self._flush_runtime_events()
            status = self._outcome_status(outcome)
            if self._cancelled:
                self._set_status("cancelled")
                await self._emit_terminal("WORKFLOW_CANCELLED", outcome)
                return self._status
            if status != "need_user_input":
                self._set_status(self._terminal_lifecycle(status))
                await self._emit_terminal(self._terminal_event_type(status), outcome)
                return self._status

            self._set_status("waiting_input", reason=self._outcome_message(outcome))
            await self._emit(
                "WORKFLOW_WAITING_INPUT",
                {
                    "message": self._outcome_message(outcome) or "Workflow waiting for user input",
                    "status": "need_user_input",
                },
            )
            while not self._cancelled and not self._pending_user_messages:
                await workflow.wait_condition(
                    lambda: self._cancelled
                    or bool(self._pending_user_messages)
                    or bool(self._pending_runtime_events)
                )
                await self._flush_runtime_events()
            if self._cancelled:
                await self._flush_runtime_events()
                self._set_status("cancelled")
                await self._emit_terminal("WORKFLOW_CANCELLED", outcome)
                return self._status

            while self._paused and not self._cancelled:
                await workflow.wait_condition(
                    lambda: not self._paused or self._cancelled or bool(self._pending_runtime_events)
                )
                await self._flush_runtime_events()
            if self._cancelled:
                await self._flush_runtime_events()
                self._set_status("cancelled")
                await self._emit_terminal("WORKFLOW_CANCELLED", outcome)
                return self._status

            signal = self._pending_user_messages.pop(0)
            self._set_status("running")
            try:
                outcome = await self._resume_from_signal(start, outcome, signal)
            except Exception as exc:
                outcome = self._failed_outcome(start, exc)
                self._last_outcome = outcome
                self._set_status("failed", reason=str(exc))
                await self._emit_terminal("WORKFLOW_FAILED", outcome)
                return self._status
            self._last_outcome = outcome

    @workflow.signal(name="user_input")
    def user_input(self, signal: SignalInput) -> None:
        self._pending_user_messages.append(signal)
        self._record_runtime_event(
            "MESSAGE_RECEIVED",
            {
                "message": "User message received",
                "signal_type": signal.type,
                "idempotency_key": signal.idempotency_key,
            },
        )

    @workflow.signal(name="pause")
    def pause(self, _: SignalInput | None = None) -> None:
        self._paused = True
        self._set_status("paused")
        self._record_runtime_event("WORKFLOW_PAUSED", {"message": "Workflow paused"})

    @workflow.signal(name="resume")
    def resume(self, _: SignalInput | None = None) -> None:
        self._paused = False
        self._set_status("running")
        self._record_runtime_event("WORKFLOW_RESUMED", {"message": "Workflow resumed"})

    @workflow.signal(name="cancel")
    def cancel(self, signal: SignalInput | None = None) -> None:
        self._cancelled = True
        self._paused = False
        reason = ""
        if signal is not None and isinstance(signal.payload, dict):
            reason = str(signal.payload.get("reason") or "")
        self._set_status("cancelled", reason=reason)
        self._record_runtime_event(
            "WORKFLOW_CANCELLING",
            {"message": "Workflow cancelling", "reason": reason},
        )

    @workflow.query(name=STATUS_QUERY)
    def agentos_status(self) -> RunStatus:
        return self._status

    async def _execute_initial(self, start: StartInput) -> dict[str, Any]:
        self._status.Step += 1
        return await workflow.execute_activity(
            "execute_agent_workflow",
            self._activity_input(start),
            start_to_close_timeout=timedelta(minutes=35),
            heartbeat_timeout=timedelta(seconds=45),
        )

    async def _resume_from_signal(
        self,
        start: StartInput,
        previous_outcome: dict[str, Any],
        signal: SignalInput,
    ) -> dict[str, Any]:
        self._status.Step += 1
        return await workflow.execute_activity(
            "resume_agent_workflow",
            self._resume_input(start, previous_outcome, signal),
            start_to_close_timeout=timedelta(minutes=35),
            heartbeat_timeout=timedelta(seconds=45),
        )

    def _activity_input(self, start: StartInput) -> dict[str, Any]:
        payload = dict(start.input or {})
        metadata = dict(start.metadata or {})
        if start.idempotency_key:
            metadata["request_id"] = start.idempotency_key
        return {
            "task_id": start.run_id,
            "user_id": start.account_id or "",
            "task_type": str(payload.get("task_type") or "main"),
            "input": payload,
            "config": {"model_ref": start.model_ref or ""},
            "metadata": metadata,
        }

    def _resume_input(
        self,
        start: StartInput,
        previous_outcome: dict[str, Any],
        signal: SignalInput,
    ) -> dict[str, Any]:
        payload = dict(signal.payload or {})
        additional_input = {
            "user_id": start.account_id or "",
            "session_id": start.thread_id or start.input.get("session_id") or "",
            "workspace_id": start.thread_id or start.input.get("session_id") or "",
            "input": {
                "query": str(payload.get("content") or ""),
                "session_id": start.thread_id or start.input.get("session_id") or "",
                "context": payload.get("context") or {},
                "attachments": payload.get("attachments") or [],
                "file_ids": payload.get("file_ids") or [],
                "context_envelope": payload.get("context_envelope") or {},
            },
            "metadata": payload.get("metadata") or {},
        }
        return {
            "task_id": start.run_id,
            "checkpoint_id": str(previous_outcome.get("checkpoint_id") or start.run_id),
            "session_id": start.thread_id or start.input.get("session_id") or "",
            "user_id": start.account_id or "",
            "metadata": self._resume_metadata(start, signal),
            "additional_input": additional_input,
            "workflow_type": previous_outcome.get("workflow_type") or start.input.get("task_type") or "main",
        }

    def _resume_metadata(self, start: StartInput, signal: SignalInput) -> dict[str, Any]:
        metadata = dict(start.metadata or {})
        if signal.idempotency_key:
            metadata["request_id"] = signal.idempotency_key
        return metadata

    def _set_status(self, lifecycle: str, reason: str = "") -> None:
        run_id = self._start.run_id if self._start is not None else ""
        self._status = RunStatus(
            RunID=run_id,
            LifecycleState=lifecycle,
            Step=self._status.Step,
            Reason=reason,
            UpdatedAt=workflow.now().isoformat(),
        )

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._start is None:
            return
        payload = dict(payload or {})
        payload.setdefault("correlation_id", self._correlation_id())
        await workflow.execute_activity(
            "emit_agentos_event",
            EventInput(
                run_id=self._start.run_id,
                thread_id=self._start.thread_id or self._start.input.get("session_id") or self._start.run_id,
                user_id=self._start.account_id or "",
                event_type=event_type,
                source="kardcraft.agent_workflow",
                payload=payload,
            ),
            start_to_close_timeout=timedelta(seconds=15),
        )

    def _record_runtime_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._pending_runtime_events.append(
            {
                "event_type": event_type,
                "payload": dict(payload or {}),
            }
        )

    async def _flush_runtime_events(self) -> None:
        while self._pending_runtime_events:
            event = self._pending_runtime_events.pop(0)
            await self._emit(
                str(event.get("event_type") or "WORKFLOW_PROGRESS"),
                dict(event.get("payload") or {}),
            )

    async def _emit_terminal(self, event_type: str, outcome: dict[str, Any]) -> None:
        payload = dict(outcome or {})
        payload.setdefault("schema_version", "task-outcome")
        payload.setdefault("task_id", self._start.run_id if self._start is not None else "")
        payload.setdefault("workflow_id", self._start.run_id if self._start is not None else "")
        payload.setdefault("run_id", self._start.run_id if self._start is not None else "")
        payload.setdefault("correlation_id", self._correlation_id())
        payload["task_outcome"] = dict(payload)
        await self._emit(event_type, payload)

    def _correlation_id(self) -> str:
        if self._start is None:
            return ""
        metadata = self._start.metadata or {}
        return str(
            self._start.idempotency_key
            or metadata.get("request_id")
            or self._start.run_id
            or ""
        ).strip()

    def _outcome_status(self, outcome: dict[str, Any]) -> str:
        return str(outcome.get("status") or "").strip().lower()

    def _outcome_message(self, outcome: dict[str, Any]) -> str:
        return str(outcome.get("message") or "").strip()

    def _terminal_lifecycle(self, status: str) -> str:
        if status == "cancelled":
            return "cancelled"
        if status == "failed":
            return "failed"
        return "completed"

    def _terminal_event_type(self, status: str) -> str:
        if status == "cancelled":
            return "WORKFLOW_CANCELLED"
        if status == "failed":
            return "WORKFLOW_FAILED"
        return "WORKFLOW_COMPLETED"

    def _failed_outcome(self, start: StartInput, exc: Exception) -> dict[str, Any]:
        message = str(exc) or "Workflow failed"
        return {
            "schema_version": "task-outcome",
            "status": "failed",
            "task_id": start.run_id,
            "workflow_id": start.run_id,
            "run_id": start.run_id,
            "session_id": start.thread_id or start.input.get("session_id") or "",
            "user_id": start.account_id or "",
            "message": message,
            "error": message,
            "metadata": dict(start.metadata or {}),
            "result": {
                "workflow_completed": False,
                "task_id": start.run_id,
                "user_id": start.account_id or "",
                "status": "failed",
                "message": message,
            },
            "checkpoint_id": start.run_id,
            "execution_time_ms": 0,
            "workflow_type": start.input.get("task_type") or "main",
            "final_cards": [],
            "saved_card_ids": [],
        }
