"""Nodes for syllabus supervisor agent (ReAct)."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.tools import tool
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from kardcraft.utils.react_runtime import run_react_structured
from kardcraft.workflow.graphs.main_graph.state import Context
from kardcraft.workflow.graphs.main_graph.subgraph.syllabus_agent import syllabus_agent

from .prompt import resolve_prompt
from .state import State


class SyllabusDecision(BaseModel):
    status: str = Field(description="outline_ready|need_user_input|failed")
    reason: str = ""


@tool
async def invoke_syllabus_agent(
    user_input: str,
    user_knowledge: str,
    subject_domain: str,
    complexity_level: str,
    file_ids: List[str],
    session_id: str | None,
    user_id: str | None,
    language: str | None,
) -> Dict[str, Any]:
    """Invoke syllabus agent to produce learning units and clarification questions."""
    result = await syllabus_agent.ainvoke(
        {
            "user_input": user_input,
            "user_knowledge": user_knowledge,
            "subject_domain": subject_domain,
            "complexity_level": complexity_level,
            "file_ids": file_ids,
            "session_id": session_id,
            "user_id": user_id,
            "language": language,
        }
    )
    return {
        "learning_units": result.get("learning_units") or [],
        "pending_questions": result.get("pending_questions") or [],
        "clarification_responses": result.get("clarification_responses") or {},
    }


async def run_syllabus_supervisor(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    user_input = state.get("user_input")
    message_knowledge = state.get("message_knowledge")

    payload = {
        "user_input": user_input,
        "user_knowledge": message_knowledge,
        "subject_domain": state.get("subject_domain"),
        "complexity_level": state.get("task_complexity"),
        "file_ids": state.get("file_ids") or [],
        "session_id": context.session_id,
        "user_id": context.user_id,
        "language": state.get("language"),
    }

    result = await syllabus_agent.ainvoke(payload, context=context)
    learning_units = result.get("learning_units") or []
    pending_questions = result.get("pending_questions") or []

    prompt = resolve_prompt(state.get("language"))
    decision = await run_react_structured(
        prompt=prompt,
        tools=[invoke_syllabus_agent],
        response_schema=SyllabusDecision,
        user_payload={
            "learning_units_count": len(learning_units),
            "pending_questions_count": len(pending_questions),
            "learning_units_preview": learning_units[:3],
            "pending_questions_preview": pending_questions[:3],
            "required_output": "Decide outline_ready/need_user_input/failed.",
        },
        name="syllabus_supervisor_react",
    )

    status = str(decision.get("status") or "").strip()
    if status not in {"outline_ready", "need_user_input", "failed"}:
        status = "failed"
    # Business-safe constraint: if follow-up questions exist, user input is required.
    if pending_questions:
        status = "need_user_input"
    elif learning_units and status != "failed":
        status = "outline_ready"

    return {
        "status": status,
        "reason": str(decision.get("reason") or "syllabus_decision"),
        "learning_units": learning_units,
        "pending_questions": pending_questions,
        "clarification_responses": result.get("clarification_responses") or {},
    }
