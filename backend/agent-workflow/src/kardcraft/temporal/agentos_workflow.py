from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


WORKFLOW_TYPE = "kardcraft.agent_workflow.v2"
STATUS_QUERY = "agentos_status"
NON_RETRYABLE_GRAPH_ACTIVITY = RetryPolicy(maximum_attempts=1)


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
    conversation_run_id: str
    thread_id: str
    user_id: str
    project_id: str
    event_type: str
    source: str
    payload: dict[str, Any]
    event_id: str
    sequence: int
    timestamp: str


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
        self._event_sequence = 0
        self._conversation_run_id = ""
        self._conversation_run_terminal = False
        self._seen_user_input_ids: set[str] = set()

    @workflow.run
    async def run(self, start: StartInput) -> RunStatus:
        self._start = start
        self._conversation_run_id = str(
            start.input.get("conversation_run_id") or start.run_id
        ).strip()
        self._conversation_run_terminal = False
        self._set_status("running")
        await self._emit("RUN_STARTED", {})
        try:
            outcome = await self._execute_initial(start)
        except Exception as exc:
            outcome = self._failed_outcome(start, exc)
            self._last_outcome = outcome
            self._set_status("failed", reason=str(exc))
            await self._emit_run_error(outcome)
            return self._status
        self._last_outcome = outcome

        while True:
            await self._flush_runtime_events()
            status = self._outcome_status(outcome)
            if self._cancelled:
                self._set_status("cancelled")
                await self._emit_run_finished("cancelled", outcome)
                return self._status
            if status != "need_user_input":
                self._set_status(self._terminal_lifecycle(status))
                if status == "failed":
                    await self._emit_run_error(outcome)
                else:
                    await self._emit_assistant_message(outcome)
                    await self._emit_run_finished(
                        "cancelled" if status == "cancelled" else "normal", outcome
                    )
                return self._status

            self._set_status("waiting_input", reason=self._outcome_message(outcome))
            await self._emit_assistant_message(outcome)
            await self._emit_interrupt(outcome)
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
                await self._emit_run_finished("cancelled", outcome)
                return self._status

            while self._paused and not self._cancelled:
                await workflow.wait_condition(
                    lambda: not self._paused or self._cancelled or bool(self._pending_runtime_events)
                )
                await self._flush_runtime_events()
            if self._cancelled:
                await self._flush_runtime_events()
                self._set_status("cancelled")
                await self._emit_run_finished("cancelled", outcome)
                return self._status

            signal = self._pending_user_messages.pop(0)
            next_run_id = str(signal.payload.get("conversation_run_id") or "").strip()
            if not next_run_id:
                raise ValueError("resume signal requires conversation_run_id")
            self._conversation_run_id = next_run_id
            self._conversation_run_terminal = False
            self._set_status("running")
            await self._emit("RUN_STARTED", {"resume": True})
            try:
                outcome = await self._resume_from_signal(start, outcome, signal)
            except Exception as exc:
                outcome = self._failed_outcome(start, exc)
                self._last_outcome = outcome
                self._set_status("failed", reason=str(exc))
                await self._emit_run_error(outcome)
                return self._status
            self._last_outcome = outcome

    @workflow.signal(name="user_input")
    def user_input(self, signal: SignalInput) -> None:
        signal_id = str(signal.idempotency_key or "").strip()
        if signal_id and signal_id in self._seen_user_input_ids:
            return
        if signal_id:
            self._seen_user_input_ids.add(signal_id)
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
            retry_policy=NON_RETRYABLE_GRAPH_ACTIVITY,
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
            retry_policy=NON_RETRYABLE_GRAPH_ACTIVITY,
        )

    def _activity_input(self, start: StartInput) -> dict[str, Any]:
        payload = dict(start.input or {})
        metadata = dict(start.metadata or {})
        if start.idempotency_key:
            metadata["request_id"] = start.idempotency_key
        return {
            "task_id": start.run_id,
            "user_id": start.account_id or "",
            "conversation_run_id": self._conversation_run_id,
            "project_id": start.project_id or start.thread_id or "",
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
        previous_state = self._previous_graph_state(previous_outcome)
        original_input = dict(start.input or {})
        original_context = original_input.get("context")
        if not isinstance(original_context, dict):
            original_context = {}
        signal_context = payload.get("context")
        if not isinstance(signal_context, dict):
            signal_context = {}
        input_context = {**original_context, **signal_context}
        resumed_input = {
            **original_input,
            "query": str(payload.get("content") or ""),
            "session_id": start.thread_id or original_input.get("session_id") or "",
            "context": input_context,
            "attachments": payload.get("attachments") or original_input.get("attachments") or [],
            "file_ids": payload.get("file_ids") or original_input.get("file_ids") or [],
            "context_envelope": payload.get("context_envelope") or original_input.get("context_envelope") or {},
        }
        clarification_responses: dict[str, str] = {}
        response = str(payload.get("content") or "").strip()
        if response:
            for question in previous_state.get("pending_questions") or []:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("id") or "").strip()
                if question_id:
                    clarification_responses[question_id] = response
                    break

        additional_input = {
            **previous_state,
            "user_id": start.account_id or "",
            "session_id": start.thread_id or start.input.get("session_id") or "",
            "workspace_id": start.thread_id or start.input.get("session_id") or "",
            "input": resumed_input,
            "metadata": payload.get("metadata") or {},
            "resume_mode": True,
            "clarification_responses": clarification_responses,
        }
        return {
            "task_id": start.run_id,
            "conversation_run_id": self._conversation_run_id,
            "project_id": start.project_id or start.thread_id or "",
            "checkpoint_id": str(previous_outcome.get("checkpoint_id") or start.run_id),
            "session_id": start.thread_id or start.input.get("session_id") or "",
            "user_id": start.account_id or "",
            "metadata": self._resume_metadata(start, signal),
            "additional_input": additional_input,
            "workflow_type": previous_outcome.get("workflow_type") or start.input.get("task_type") or "main",
        }

    @staticmethod
    def _previous_graph_state(previous_outcome: dict[str, Any]) -> dict[str, Any]:
        result = previous_outcome.get("result")
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        return dict(data) if isinstance(data, dict) else dict(result)

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
        self._event_sequence += 1
        sequence = self._event_sequence
        await workflow.execute_activity(
            "emit_agentos_event",
            EventInput(
                run_id=self._start.run_id,
                conversation_run_id=self._conversation_run_id,
                thread_id=self._start.thread_id or self._start.input.get("session_id") or self._start.run_id,
                user_id=self._start.account_id or "",
                project_id=self._start.project_id or self._start.thread_id or "",
                event_type=event_type,
                source="kardcraft.agent_workflow",
                payload=payload,
                event_id=f"{self._start.run_id}:{self._conversation_run_id}:workflow:{sequence}",
                sequence=sequence,
                timestamp=workflow.now().isoformat(),
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

    def _terminal_payload(self, outcome: dict[str, Any]) -> dict[str, Any]:
        payload = dict(outcome or {})
        payload.pop("task_outcome", None)
        payload.setdefault("schema_version", "task-outcome")
        payload.setdefault("task_id", self._start.run_id if self._start is not None else "")
        payload.setdefault("workflow_id", self._start.run_id if self._start is not None else "")
        payload.setdefault("run_id", self._start.run_id if self._start is not None else "")
        payload.setdefault("correlation_id", self._correlation_id())
        return payload

    async def _emit_assistant_message(self, outcome: dict[str, Any]) -> None:
        content = self._outcome_message(outcome)
        if not content:
            return
        message_id = f"{self._conversation_run_id}:assistant"
        await self._emit(
            "TEXT_MESSAGE_START",
            {"message_id": message_id, "role": "assistant"},
        )
        await self._emit(
            "TEXT_MESSAGE_CONTENT",
            {"message_id": message_id, "delta": content},
        )
        await self._emit(
            "TEXT_MESSAGE_END",
            {"message_id": message_id, "role": "assistant", "content": content},
        )

    async def _emit_interrupt(self, outcome: dict[str, Any]) -> None:
        if self._conversation_run_terminal:
            return
        prompt = self._outcome_message(outcome) or "Additional input is required"
        checkpoint_id = str(outcome.get("checkpoint_id") or self._start.run_id)
        interrupt_id = f"{checkpoint_id}:{self._status.Step}"
        await self._emit(
            "RUN_FINISHED",
            {
                "outcome": "interrupt",
                "interrupt": {
                    "interrupt_id": interrupt_id,
                    "type": "user_input",
                    "prompt": prompt,
                    "input_schema": {"type": "string"},
                    "metadata": {"checkpoint_id": checkpoint_id},
                },
                "task_outcome": self._terminal_payload(outcome),
            },
        )
        self._conversation_run_terminal = True

    async def _emit_run_finished(self, outcome_type: str, outcome: dict[str, Any]) -> None:
        payload = self._terminal_payload(outcome)
        if self._conversation_run_terminal:
            await self._emit(
                "kardcraft.process.cancelled",
                {"outcome": outcome_type, "task_outcome": payload},
            )
            return
        await self._emit(
            "RUN_FINISHED",
            {"outcome": outcome_type, "task_outcome": payload},
        )
        self._conversation_run_terminal = True

    async def _emit_run_error(self, outcome: dict[str, Any]) -> None:
        if self._conversation_run_terminal:
            return
        payload = self._terminal_payload(outcome)
        await self._emit(
            "RUN_ERROR",
            {
                "code": str(outcome.get("error_code") or "WORKFLOW_FAILED"),
                "message": self._outcome_message(outcome) or "Workflow failed",
                "retryable": False,
                "task_outcome": payload,
            },
        )
        self._conversation_run_terminal = True

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
