from __future__ import annotations

from typing import Any

import pytest

from kardcraft.temporal.agentos_workflow import (
    KardcraftAgentOSWorkflow,
    NON_RETRYABLE_GRAPH_ACTIVITY,
    SignalInput,
    StartInput,
)


def capture_events(runtime: KardcraftAgentOSWorkflow) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    runtime._emit = emit  # type: ignore[method-assign]
    runtime._conversation_run_id = "conversation-run-1"
    return events


@pytest.mark.asyncio
async def test_assistant_message_has_strict_start_content_end_sequence() -> None:
    runtime = KardcraftAgentOSWorkflow()
    events = capture_events(runtime)

    await runtime._emit_assistant_message({"message": "Complete answer"})

    assert [event_type for event_type, _ in events] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
    ]
    assert {payload["message_id"] for _, payload in events} == {
        "conversation-run-1:assistant"
    }
    assert events[-1][1]["content"] == "Complete answer"


@pytest.mark.asyncio
async def test_interrupt_is_emitted_after_completed_prompt_and_is_terminal() -> None:
    runtime = KardcraftAgentOSWorkflow()
    events = capture_events(runtime)
    runtime._status.Step = 2
    runtime._start = type(
        "Start",
        (),
        {"run_id": "process-1", "idempotency_key": "request-1", "metadata": {}},
    )()
    outcome = {"status": "need_user_input", "message": "Which scope?", "checkpoint_id": "checkpoint-1"}

    await runtime._emit_assistant_message(outcome)
    await runtime._emit_interrupt(outcome)

    assert [event_type for event_type, _ in events][-2:] == [
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    terminal = events[-1][1]
    assert terminal["outcome"] == "interrupt"
    assert terminal["interrupt"]["interrupt_id"] == "checkpoint-1:2"
    assert runtime._conversation_run_terminal is True


@pytest.mark.asyncio
async def test_each_conversation_run_gets_only_one_terminal_event() -> None:
    runtime = KardcraftAgentOSWorkflow()
    events = capture_events(runtime)
    runtime._start = type(
        "Start",
        (),
        {"run_id": "process-1", "idempotency_key": "request-1", "metadata": {}},
    )()

    await runtime._emit_run_finished("normal", {"status": "completed", "message": "done"})
    await runtime._emit_run_finished("cancelled", {"status": "cancelled"})

    assert [event_type for event_type, _ in events] == [
        "RUN_FINISHED",
        "kardcraft.process.cancelled",
    ]
    assert "task_outcome" not in events[0][1]["task_outcome"]


@pytest.mark.asyncio
async def test_run_error_is_terminal_and_idempotent() -> None:
    runtime = KardcraftAgentOSWorkflow()
    events = capture_events(runtime)
    runtime._start = type(
        "Start",
        (),
        {"run_id": "process-1", "idempotency_key": "request-1", "metadata": {}},
    )()

    await runtime._emit_run_error(
        {"status": "failed", "message": "backend failed", "error_code": "BACKEND_FAILED"}
    )
    await runtime._emit_run_error({"status": "failed", "message": "duplicate"})

    assert [event_type for event_type, _ in events] == ["RUN_ERROR"]
    assert events[0][1]["code"] == "BACKEND_FAILED"


@pytest.mark.asyncio
async def test_new_conversation_run_can_finish_after_previous_interrupt() -> None:
    runtime = KardcraftAgentOSWorkflow()
    events = capture_events(runtime)
    runtime._status.Step = 1
    runtime._start = type(
        "Start",
        (),
        {"run_id": "process-1", "idempotency_key": "request-1", "metadata": {}},
    )()

    first = {"status": "need_user_input", "message": "First question", "checkpoint_id": "cp-1"}
    await runtime._emit_assistant_message(first)
    await runtime._emit_interrupt(first)

    runtime._conversation_run_id = "conversation-run-2"
    runtime._conversation_run_terminal = False
    runtime._status.Step = 2
    second = {"status": "need_user_input", "message": "Second question", "checkpoint_id": "cp-1"}
    await runtime._emit_assistant_message(second)
    await runtime._emit_interrupt(second)

    terminals = [payload for event_type, payload in events if event_type == "RUN_FINISHED"]
    assert [payload["outcome"] for payload in terminals] == ["interrupt", "interrupt"]
    assert [payload["interrupt"]["interrupt_id"] for payload in terminals] == ["cp-1:1", "cp-1:2"]


def test_resume_input_preserves_original_context_and_maps_reply() -> None:
    runtime = KardcraftAgentOSWorkflow()
    start = StartInput(
        run_id="process-1",
        thread_id="thread-1",
        account_id="account-1",
        input={
            "task_type": "main",
            "session_id": "thread-1",
            "query": "Create cards about photosynthesis",
            "context": {
                "template_id": "anki-quizify",
                "template_version": 1,
                "template_profile": "mcq",
            },
        },
    )
    previous = {
        "checkpoint_id": "process-1",
        "workflow_type": "main",
        "result": {
            "data": {
                "user_input": "Create cards about photosynthesis",
                "template_id": "anki-quizify",
                "pending_questions": [
                    {"id": "question-1", "question_text": "Which concepts?"}
                ],
                "clarification_round": 1,
                "clarification_responses": {},
            }
        },
    }
    signal = SignalInput(
        type="user.message",
        idempotency_key="reply-1",
        payload={"content": "Chlorophyll and the Calvin cycle"},
    )

    resumed = runtime._resume_input(start, previous, signal)
    additional = resumed["additional_input"]

    assert additional["resume_mode"] is True
    assert additional["user_input"] == "Create cards about photosynthesis"
    assert additional["input"]["context"] == start.input["context"]
    assert additional["clarification_responses"] == {
        "question-1": "Chlorophyll and the Calvin cycle"
    }


def test_resume_input_only_submits_the_current_clarification_answer() -> None:
    runtime = KardcraftAgentOSWorkflow()
    start = StartInput(
        run_id="process-1",
        thread_id="thread-1",
        account_id="account-1",
        input={"task_type": "main", "session_id": "thread-1"},
    )
    previous = {
        "result": {
            "data": {
                "message_knowledge": "Q: Which faction?\nA: Cao Cao's faction",
                "pending_questions": [
                    {"id": "question-2", "question_text": "Which characters?"}
                ],
                "clarification_responses": {"question-1": "Cao Cao's faction"},
            }
        }
    }
    signal = SignalInput(type="user.message", payload={"content": "As many as possible"})

    additional = runtime._resume_input(start, previous, signal)["additional_input"]

    assert additional["message_knowledge"] == "Q: Which faction?\nA: Cao Cao's faction"
    assert additional["clarification_responses"] == {
        "question-2": "As many as possible"
    }


def test_graph_activities_do_not_automatically_retry_side_effects() -> None:
    assert NON_RETRYABLE_GRAPH_ACTIVITY.maximum_attempts == 1
