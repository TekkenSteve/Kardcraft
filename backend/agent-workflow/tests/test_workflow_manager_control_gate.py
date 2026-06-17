import asyncio
import time

import pytest

from kardcraft.workflow.manager import WorkflowManager


class _FakeGraph:
    async def astream(self, **_kwargs):
        yield "updates", {"first": {"message": "one"}}
        yield "updates", {"second": {"message": "two"}}
        yield "values", {"status": "success"}


class _ControlledGraph:
    def __init__(self, continue_event: asyncio.Event):
        self.continue_event = continue_event

    async def astream(self, **_kwargs):
        yield "updates", {"first": {"message": "one"}}
        await self.continue_event.wait()
        yield "updates", {"second": {"message": "two"}}
        yield "values", {"status": "success"}


class _CapturingGraph:
    def __init__(self):
        self.inputs = []

    async def astream(self, **kwargs):
        self.inputs.append(kwargs.get("input") or {})
        yield "values", {"status": "success"}


@pytest.mark.asyncio
async def test_execute_checks_control_gate_between_graph_events():
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._get_graph = lambda _workflow_type: _FakeGraph()

    gate_calls = 0
    progress_events = []

    async def control_gate():
        nonlocal gate_calls
        gate_calls += 1

    async def progress_callback(event):
        progress_events.append(event)

    result = await manager.execute(
        workflow_type="main",
        input_data={"task_id": "task-1", "user_id": "user-1", "workspace_id": "s1"},
        progress_callback=progress_callback,
        control_gate=control_gate,
    )

    assert result.result["status"] == "success"
    assert gate_calls >= 4
    assert [event["type"] for event in progress_events] == [
        "NODE_STARTED",
        "NODE_COMPLETED",
        "NODE_STARTED",
        "NODE_COMPLETED",
    ]


@pytest.mark.asyncio
async def test_execute_graph_construction_does_not_block_event_loop():
    manager = WorkflowManager.__new__(WorkflowManager)

    def build_graph(_workflow_type):
        time.sleep(0.1)
        return _FakeGraph()

    manager._get_graph = build_graph
    loop_ticked = asyncio.Event()

    async def ticker():
        await asyncio.sleep(0.02)
        loop_ticked.set()

    task = asyncio.create_task(
        manager.execute(
            workflow_type="main",
            input_data={"task_id": "task-1", "user_id": "user-1", "workspace_id": "s1"},
        )
    )
    ticker_task = asyncio.create_task(ticker())

    await asyncio.wait_for(loop_ticked.wait(), timeout=1)
    result = await task
    await ticker_task

    assert result.result["status"] == "success"


@pytest.mark.asyncio
async def test_resume_checks_control_gate_between_graph_events():
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._get_graph = lambda _workflow_type: _FakeGraph()

    gate_calls = 0
    progress_events = []

    async def control_gate():
        nonlocal gate_calls
        gate_calls += 1

    async def progress_callback(event):
        progress_events.append(event)

    result = await manager.resume(
        checkpoint_id="task-1",
        additional_input={"task_id": "task-1", "user_id": "user-1", "workspace_id": "s1"},
        progress_callback=progress_callback,
        control_gate=control_gate,
    )

    assert result.result["status"] == "success"
    assert gate_calls >= 4
    assert [event["type"] for event in progress_events] == [
        "NODE_STARTED",
        "NODE_COMPLETED",
        "NODE_STARTED",
        "NODE_COMPLETED",
    ]


@pytest.mark.asyncio
async def test_resume_restores_template_state_from_input_context():
    graph = _CapturingGraph()
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._get_graph = lambda _workflow_type: graph

    await manager.resume(
        checkpoint_id="task-1",
        additional_input={
            "task_id": "task-1",
            "user_id": "user-1",
            "session_id": "s1",
            "workspace_id": "s1",
            "input": {
                "query": "make cards",
                "file_ids": ["file-1"],
                "target_count": 5,
                "difficulty_level": "medium",
                "context": {
                    "template_id": "tpl-1",
                    "template_version": 3,
                    "template_profile": "cloze",
                },
            },
        },
    )

    assert graph.inputs
    resumed_input = graph.inputs[0]
    assert resumed_input["template_id"] == "tpl-1"
    assert resumed_input["template_version"] == 3
    assert resumed_input["selected_template_profile"] == "cloze"
    assert resumed_input["user_input"] == "make cards"
    assert resumed_input["file_ids"] == ["file-1"]
    assert resumed_input["target_count"] == 5


@pytest.mark.asyncio
async def test_execute_completes_node_when_update_arrives():
    continue_event = asyncio.Event()
    first_completed = asyncio.Event()
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._get_graph = lambda _workflow_type: _ControlledGraph(continue_event)

    progress_events = []

    async def progress_callback(event):
        progress_events.append(event)
        if event["type"] == "NODE_COMPLETED" and event["node_name"] == "first":
            first_completed.set()

    task = asyncio.create_task(
        manager.execute(
            workflow_type="main",
            input_data={"task_id": "task-1", "user_id": "user-1", "workspace_id": "s1"},
            progress_callback=progress_callback,
        )
    )

    await asyncio.wait_for(first_completed.wait(), timeout=1)
    assert [event["type"] for event in progress_events] == ["NODE_STARTED", "NODE_COMPLETED"]

    continue_event.set()
    result = await task
    assert result.result["status"] == "success"
