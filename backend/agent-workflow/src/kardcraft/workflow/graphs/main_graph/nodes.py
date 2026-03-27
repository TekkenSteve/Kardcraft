"""Thin orchestration nodes for main graph v3 (no legacy runtime dependency)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from langgraph.runtime import Runtime

from kardcraft.card_templates import (
    TemplatePreparationError,
    prepare_template_context_for_main_graph,
)
from kardcraft.llm.client import chat_complete
from kardcraft.utils.language import detect_preferred_language_with_llm
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.workflow.graphs.main_graph.state import Context, State
from kardcraft.workflow.graphs.main_graph.subgraph.card_supervisor_agent import (
    card_supervisor_agent,
)
from kardcraft.workflow.graphs.main_graph.subgraph.evidence_supervisor_agent import (
    evidence_supervisor_agent,
)
from kardcraft.workflow.graphs.main_graph.subgraph.intent_classifier_agent import intent_classifier
from kardcraft.workflow.graphs.main_graph.subgraph.syllabus_supervisor_agent import (
    syllabus_supervisor_agent,
)


async def separate_content_and_task(user_input: str) -> Dict[str, str]:
    """Split message into source content and task demand using LLM."""
    prompt = (
        "Please split the user input into JSON:\n"
        "{\"message_knowledge\": \"Knowledge material\", \"topic\": \"Task requirement\"}\n"
        "If knowledge material is missing, message_knowledge can be empty."
    )
    try:
        response = await chat_complete(
            intent="extract",
            temperature=0.0,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={})
        if not isinstance(parsed, dict):
            parsed = {}
        source = str(parsed.get("message_knowledge") or "").strip()
        topic = str(parsed.get("topic") or "").strip() or user_input
        return {"message_knowledge": source, "topic": topic}
    except Exception:
        return {"message_knowledge": user_input, "topic": user_input}


async def initialize_processing(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Initialize request context and template context."""
    from kardcraft.services.langfuse import get_langfuse_client

    langfuse = get_langfuse_client()
    session_id = runtime.context.session_id
    user_id = runtime.context.user_id
    if not session_id:
        return {"error": "missing_session_id"}

    try:
        prepared_template = await prepare_template_context_for_main_graph(
            user_id=user_id,
            topic=state.get("user_input", ""),
            template_id=state.get("template_id"),
            template_version_raw=state.get("template_version"),
            selected_profile=state.get("selected_template_profile"),
        )
    except TemplatePreparationError as exc:
        payload: Dict[str, Any] = {"error": exc.message}
        if isinstance(exc.validation, dict):
            payload["template_validation"] = exc.validation
        return payload

    trace_id = None
    try:
        trace = langfuse.trace(
            name="main_graph_execution",
            metadata={
                "user_input": state.get("user_input"),
                "session_id": session_id,
                "user_id": user_id,
            },
        )
        trace_id = trace.id
    except Exception:
        trace_id = None

    return {
        "trace_id": trace_id,
        "template_id": prepared_template.template_id,
        "template_version": prepared_template.template_version,
        "template_name": prepared_template.template_name,
        "template_profiles": prepared_template.template_profiles,
        "template_default_profile": prepared_template.template_default_profile,
        "selected_template_profile": prepared_template.selected_template_profile,
        "template_note_fields": prepared_template.template_note_fields,
        "template_validation": prepared_template.template_validation,
        "pending_questions": [],
        "learning_units": [],
        "approved_cards": [],
        "final_cards": [],
        "saved_card_ids": [],
        "quality_report": {},
        "qa_loop_report": {},
    }


async def run_intent_classifier(state: State) -> Dict[str, Any]:
    """Classify intent and normalize canonical inputs."""
    result = await intent_classifier.ainvoke(
        {
            "user_input": state.get("user_input"),
            "file_ids": state.get("file_ids", []),
            "metadata": {
                "target_count": state.get("target_count", 10),
                "difficulty_level": state.get("difficulty_level", "medium"),
            },
        }
    )

    update: Dict[str, Any] = {
        "intent_type": result.get("intent_type", "create_cards"),
        "driven_mode": result.get("driven_mode"),
        "subject_domain": result.get("subject_domain"),
        "task_complexity": result.get("task_complexity"),
        "language": result.get("language"),
    }

    user_input = state.get("user_input", "")
    if result.get("driven_mode") == "content_driven" and state.get("file_ids") is None:
        separated = await separate_content_and_task(user_input)
        if separated.get("message_knowledge"):
            update["message_knowledge"] = separated["message_knowledge"]
            update["user_input"] = separated.get("topic") or user_input
            update["topic"] = separated.get("topic") or user_input

    demand = str(update.get("user_input") or state.get("user_input") or state.get("topic") or "")
    if demand:
        update["language"] = await detect_preferred_language_with_llm(demand)

    return update


async def run_syllabus_supervisor(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    result = await syllabus_supervisor_agent.ainvoke(
        {
            "user_input": state.get("user_input"),
            "message_knowledge": state.get("message_knowledge"),
            "file_ids": state.get("file_ids") or [],
            "subject_domain": state.get("subject_domain"),
            "task_complexity": state.get("task_complexity"),
            "difficulty_level": state.get("difficulty_level"),
            "language": state.get("language"),
        },
        context=context,
    )
    return {
        "syllabus_status": result.get("status", "failed"),
        "learning_units": result.get("learning_units") or [],
        "pending_questions": result.get("pending_questions") or [],
        "clarification_responses": result.get("clarification_responses") or {},
        "error": state.get("error") if result.get("status") != "failed" else result.get("reason"),
    }


async def run_evidence_supervisor(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    result = await evidence_supervisor_agent.ainvoke(
        {
            "user_input": state.get("user_input"),
            "message_knowledge": state.get("message_knowledge"),
            "synthesized_knowledge": state.get("synthesized_knowledge") or "",
            "file_ids": state.get("file_ids") or [],
            "subject_domain": state.get("subject_domain"),
            "difficulty_level": state.get("difficulty_level"),
            "target_count": state.get("target_count") or 10,
            "learning_units": state.get("learning_units") or [],
            "language": state.get("language"),
        },
        context=context,
    )
    research_content = str((result.get("research_results") or {}).get("content") or "").strip()

    payload: Dict[str, Any] = {
        "evidence_status": result.get("status", "failed"),
        "pending_questions": result.get("pending_questions") or [],
        "research_results": result.get("research_results") or {},
        "error": state.get("error") if result.get("status") != "failed" else result.get("reason"),
    }
    if research_content:
        payload["synthesized_knowledge"] = research_content
        payload["message_knowledge"] = research_content
    return payload


async def run_card_supervisor(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    result = await card_supervisor_agent.ainvoke(
        {
            "user_input": state.get("user_input"),
            "message_knowledge": state.get("message_knowledge"),
            "subject_domain": state.get("subject_domain"),
            "learning_units": state.get("learning_units") or [],
            "template_profiles": state.get("template_profiles") or [],
            "template_default_profile": state.get("template_default_profile"),
            "selected_template_profile": state.get("selected_template_profile"),
            "file_ids": state.get("file_ids") or [],
            "judge_score_threshold": 90,
            "max_qa_iterations": 8,
            "language": state.get("language"),
        },
        context=context,
    )

    approved = result.get("approved_cards") or []
    status = result.get("status", "failed")
    return {
        "card_status": status,
        "approved_cards": approved,
        "final_cards": approved if status in {"quality_pass", "need_user_review"} else [],
        "quality_report": result.get("quality_report") or {},
        "qa_loop_report": result.get("qa_loop_report") or {},
        "error": state.get("error") if status != "failed" else result.get("reason"),
    }


async def finalize_processing(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Persist final cards and emit final workflow payload."""
    from kardcraft.services.langfuse import get_langfuse_client
    from kardcraft.workflow.graphs.main_graph.utils import save_cards_to_workspace

    langfuse = get_langfuse_client()
    context = runtime.context
    workspace_id = str((context.workspace_id if context else None) or "")
    workspace_id = workspace_id.strip()
    if not workspace_id:
        raise ValueError("workspace_id missing in runtime context")

    cards = list(state.get("final_cards") or state.get("approved_cards") or [])
    saved_card_ids = list(state.get("saved_card_ids") or [])

    if cards and not saved_card_ids:
        saved_card_ids = await save_cards_to_workspace(
            cards,
            workspace_id=workspace_id,
            owner=str((context.user_id if context else "") or ""),
        )

    if langfuse.enabled:
        try:
            langfuse.flush()
        except Exception:
            pass

    return {
        "final_cards": cards,
        "approved_cards": cards,
        "saved_card_ids": saved_card_ids,
        "completed_at": datetime.utcnow().isoformat(),
    }
