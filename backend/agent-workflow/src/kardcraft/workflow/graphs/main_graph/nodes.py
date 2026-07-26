"""Thin orchestration nodes for main graph v3 (no legacy runtime dependency)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.card_templates import (
    TemplatePreparationError,
    prepare_template_context_for_main_graph,
)
from kardcraft.utils.document_registry import build_incremental_document_registry
from kardcraft.utils.language import detect_preferred_language_with_llm
from kardcraft.utils.logger import logger
from kardcraft.utils.main_graph_helpers import (
    collect_asked_question_texts,
    determine_query_scope,
    extract_first_question,
    extract_pending_question_ids,
    information_gain_score,
    is_file_tree_path_enabled,
    normalize_clarification_responses,
    normalize_pending_questions_strict,
    scope_budget,
    separate_content_and_task,
    should_trigger_preflight,
    validate_pending_questions_strict,
)
from kardcraft.utils.rollout_gate import rollout_enabled_for_user
from kardcraft.workflow.graphs.clarification_graph.tool import clarify
from kardcraft.workflow.graphs.main_graph.state import (
    EVIDENCE_STORE_SCHEMA_VERSION,
    Context,
    State,
)
from kardcraft.workflow.graphs.main_graph.subgraph.card_aggregation_agent import (
    card_aggregation_agent,
)
from kardcraft.workflow.graphs.main_graph.subgraph.card_scope_supervisor_agent import (
    card_scope_supervisor_agent,
)
from kardcraft.workflow.graphs.main_graph.subgraph.evidence_react_agent import (
    evidence_react_agent,
)
from kardcraft.workflow.graphs.main_graph.subgraph.intent_classifier_agent import intent_classifier

SOC_MAX_ROUNDS = 3
SOC_MIN_INFORMATION_GAIN = 0.05


def _history_preview(
    history: List[Dict[str, Any]] | None,
    *,
    max_items: int = 8,
    max_chars: int = 200,
) -> List[Dict[str, Any]]:
    items = list(history or [])
    start = max(0, len(items) - max_items)
    preview: List[Dict[str, Any]] = []
    for idx, entry in enumerate(items[start:], start=start):
        if not isinstance(entry, dict):
            preview.append({"index": idx, "role": "unknown", "content_preview": str(entry)[:max_chars]})
            continue
        content = str(entry.get("content") or "").strip()
        if len(content) > max_chars:
            content = content[:max_chars] + "...[truncated]"
        preview.append(
            {
                "index": idx,
                "role": str(entry.get("role") or "unknown"),
                "content_preview": content,
            }
        )
    return preview


def _derive_final_status(state: State) -> tuple[str, str]:
    explicit_status = str(state.get("status") or "").strip().lower()
    workflow_error = str(state.get("error") or "").strip()
    card_status = str(state.get("card_status") or "").strip().lower()
    pending_questions = list(state.get("pending_questions") or [])
    cards = list(state.get("final_cards") or [])

    stage_statuses = {
        "preflight_status": str(state.get("preflight_status") or "").strip().lower(),
        "syllabus_status": str(state.get("syllabus_status") or "").strip().lower(),
        "card_scope_status": str(state.get("card_scope_status") or "").strip().lower(),
        "evidence_status": str(state.get("evidence_status") or "").strip().lower(),
    }
    failed_stages = [name for name, value in stage_statuses.items() if value == "failed"]
    need_input_stages = [
        name for name, value in stage_statuses.items() if value == "need_user_input"
    ]

    if explicit_status == "failed" or workflow_error:
        return "failed", "explicit_failed_or_error"
    if failed_stages:
        return "failed", f"stage_failed:{','.join(failed_stages)}"
    if explicit_status == "need_user_input":
        return "need_user_input", "explicit_need_user_input"
    if need_input_stages:
        return "need_user_input", f"stage_need_user_input:{','.join(need_input_stages)}"
    if pending_questions:
        return "need_user_input", "pending_questions_present"
    if card_status:
        return ("success", "card_quality_pass") if card_status == "quality_pass" else ("failed", f"card_status:{card_status}")
    if explicit_status == "success" and cards:
        return "success", "explicit_success_with_cards"
    if explicit_status == "success":
        return "failed", "success_without_cards"
    return "failed", "undetermined_terminal_state"


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

    rollout = rollout_enabled_for_user(user_id)

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

    initialized = {
        "trace_id": trace_id,
        "template_id": prepared_template.template_id,
        "template_version": prepared_template.template_version,
        "template_name": prepared_template.template_name,
        "template_profiles": prepared_template.template_profiles,
        "template_default_profile": prepared_template.template_default_profile,
        "selected_template_profile": prepared_template.selected_template_profile,
        "template_note_fields": prepared_template.template_note_fields,
        "template_validation": prepared_template.template_validation,
        "profile_prompt_hint": prepared_template.profile_prompt_hint,
        "preflight_status": None,
        "preflight_reason": None,
        "query_scope": None,
        "file_tree_path_active": bool(
            [x for x in (state.get("file_ids") or []) if str(x).strip()]
        )
        and is_file_tree_path_enabled(user_id),
        "retrieval_budget": {},
        "document_tree_status": None,
        "document_tree_error": None,
        "clarification_state": None,
        "termination_reason": None,
        "clarification_round": 0,
        "max_rounds": SOC_MAX_ROUNDS,
        "clarification_responses": {},
        "asked_questions": [],
        "pending_questions": [],
        "document_trees": [],
        "tree_registry": {},
        "candidate_nodes": [],
        "scoped_learning_units": [],
        "scope_chunks": [],
        "selected_nodes": [],
        "evidence_items": [],
        "evidence_store": {
            "schema_version": EVIDENCE_STORE_SCHEMA_VERSION,
            "items": [],
            "index": {},
            "reason_code_counts": {},
            "duplicate_query_ratio": 0.0,
            "hit_rate": 0.0,
        },
        "coverage_state": {
            "coverage_rate": 0.0,
            "covered_node_ids": [],
            "total_node_count": 0,
        },
        "evidence_loop_report": {},
        "evidence_retry_count": 0,
        "learning_units": [],
        "syllabus_outline": [],
        "outline_sources": [],
        "approved_cards": [],
        "final_cards": [],
        "saved_card_ids": [],
        "quality_report": {},
        "qa_loop_report": {},
        "card_scope_status": None,
        "card_scope_report": {},
        "evidence_skillrouter_rollout": rollout,
    }
    if state.get("resume_mode"):
        for key in (
            "clarification_state",
            "termination_reason",
            "clarification_round",
            "max_rounds",
            "clarification_responses",
            "asked_questions",
            "pending_questions",
        ):
            initialized.pop(key, None)
        initialized["status"] = None
        initialized["error"] = None

    return initialized


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
        "classification_confidence": float(result.get("confidence") or 0.0),
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


async def run_socratic_preflight(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Strict preflight with deterministic multi-round clarification control."""
    pending_questions_raw = state.get("pending_questions") or []
    pending_questions, pending_error = validate_pending_questions_strict(pending_questions_raw)
    if pending_error and pending_questions_raw:
        return {
            "error": pending_error,
            "status": "failed",
            "clarification_state": "exhausted",
            "termination_reason": "invalid_pending_questions",
            "preflight_status": "need_user_input",
            "preflight_reason": "invalid_pending_questions",
        }

    raw_responses = state.get("clarification_responses")
    clarification_responses, response_error = normalize_clarification_responses(raw_responses)
    if response_error:
        return {
            "error": response_error,
            "status": "failed",
            "clarification_state": "exhausted",
            "termination_reason": "invalid_clarification_responses",
            "preflight_status": "need_user_input",
            "preflight_reason": "invalid_clarification_responses",
        }

    current_round = int(state.get("clarification_round") or 0)
    max_rounds = int(state.get("max_rounds") or SOC_MAX_ROUNDS)
    if max_rounds != SOC_MAX_ROUNDS:
        max_rounds = SOC_MAX_ROUNDS

    if pending_questions and not clarification_responses:
        question = extract_first_question(pending_questions)
        return {
            "preflight_status": "need_user_input",
            "preflight_reason": "pending_questions_exist",
            "status": "need_user_input",
            "clarification_state": "collecting",
            "termination_reason": None,
            "clarification_round": current_round or 1,
            "max_rounds": max_rounds,
            "pending_questions": pending_questions,
            "question": question,
            "message": question or "Additional user input is required to continue.",
        }

    should_trigger, reason = should_trigger_preflight(state)
    has_reassessment_input = bool(clarification_responses)
    if not should_trigger and not has_reassessment_input:
        return {
            "preflight_status": "skipped",
            "preflight_reason": reason,
            "clarification_state": "resolved",
            "termination_reason": None,
            "max_rounds": max_rounds,
        }

    if clarification_responses and pending_questions:
        allowed_ids = extract_pending_question_ids(pending_questions)
        unknown_keys = sorted(set(clarification_responses.keys()) - allowed_ids)
        if unknown_keys:
            return {
                "error": f"unknown clarification response keys: {','.join(unknown_keys)}",
                "status": "failed",
                "clarification_state": "exhausted",
                "termination_reason": "invalid_clarification_response_keys",
                "preflight_status": "need_user_input",
                "preflight_reason": "invalid_clarification_response_keys",
            }

    message_knowledge = str(state.get("message_knowledge") or "").strip()
    user_input = str(state.get("user_input") or "").strip()
    asked_questions = collect_asked_question_texts(
        state.get("asked_questions"),
        pending_questions,
    )

    if clarification_responses and pending_questions:
        if information_gain_score(clarification_responses, message_knowledge) < SOC_MIN_INFORMATION_GAIN:
            return {
                "preflight_status": "need_user_input",
                "preflight_reason": "low_information_gain",
                "status": "need_user_input",
                "clarification_state": "exhausted",
                "termination_reason": "exhausted",
                "clarification_round": current_round or 1,
                "max_rounds": max_rounds,
                "pending_questions": [],
                "message": "Need more concrete details to proceed.",
                "clarification_responses": clarification_responses,
            }

        response_lines = []
        for item in pending_questions:
            question_id = str(item.get("id") or "").strip()
            question_text = str(item.get("question_text") or "").strip()
            answer = clarification_responses.get(question_id)
            if question_text and answer:
                response_lines.append(f"Q: {question_text}\nA: {answer}")
        if response_lines:
            integrated = "\n\n".join(response_lines)
            message_knowledge = f"{message_knowledge}\n\n{integrated}".strip() if message_knowledge else integrated

    target_round = 1 if current_round <= 0 else current_round + (1 if clarification_responses else 0)
    session_id = str(runtime.context.session_id or "").strip()
    clarification = await clarify.ainvoke(
        {
            "user_input": user_input,
            "message_knowledge": message_knowledge,
            "file_ids": [],
            "language": state.get("language"),
            "session_id": session_id,
            "round_index": target_round,
            "asked_questions": asked_questions,
        }
    )
    status = str(clarification.get("status") or "").strip().lower()
    pending_questions_raw = clarification.get("pending_questions") or []
    pending_questions, pending_error = validate_pending_questions_strict(pending_questions_raw)
    if pending_error:
        return {
            "error": pending_error,
            "status": "failed",
            "clarification_state": "exhausted",
            "termination_reason": "invalid_pending_questions",
            "preflight_status": "need_user_input",
            "preflight_reason": "invalid_pending_questions",
        }

    if status == "need_user_input":
        if target_round > max_rounds:
            return {
                "preflight_status": "need_user_input",
                "preflight_reason": "max_rounds_reached",
                "status": "need_user_input",
                "clarification_state": "exhausted",
                "termination_reason": "exhausted",
                "clarification_round": max_rounds,
                "max_rounds": max_rounds,
                "pending_questions": [],
                "message": "Maximum clarification rounds reached. Please provide clearer requirements.",
                "clarification_responses": clarification_responses,
                "asked_questions": asked_questions,
            }
        question = extract_first_question(pending_questions)
        updated_asked = collect_asked_question_texts(asked_questions, pending_questions)
        return {
            "preflight_status": "need_user_input",
            "preflight_reason": str(clarification.get("reason") or "preflight_clarification"),
            "pending_questions": pending_questions,
            "status": "need_user_input",
            "clarification_state": "collecting",
            "termination_reason": None,
            "clarification_round": target_round,
            "max_rounds": max_rounds,
            "question": question,
            "message": question or str(clarification.get("message") or "").strip() or "Additional user input is required to continue.",
            "clarification_responses": clarification_responses,
            "asked_questions": updated_asked,
        }

    if status == "success":
        return {
            "preflight_status": "pass_through",
            "preflight_reason": str(clarification.get("reason") or "clarification_sufficient"),
            "status": "success",
            "clarification_state": "resolved",
            "termination_reason": None,
            "clarification_round": current_round or target_round,
            "max_rounds": max_rounds,
            "pending_questions": [],
            "clarification_responses": clarification_responses,
            "asked_questions": asked_questions,
            "message_knowledge": message_knowledge,
        }

    return {
        "error": str(clarification.get("reason") or "clarification_failed"),
        "status": "failed",
        "clarification_state": "exhausted",
        "termination_reason": str(clarification.get("termination_reason") or "clarification_failed"),
        "preflight_status": "need_user_input",
        "preflight_reason": str(clarification.get("reason") or "clarification_failed"),
    }


async def run_document_tree_planner(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    if not bool(state.get("file_tree_path_active")):
        return {
            "document_tree_status": "skipped",
            "document_tree_error": None,
            "document_trees": [],
            "tree_registry": {},
        }

    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    if not file_ids:
        return {
            "error": "missing_file_ids",
            "document_tree_status": "failed",
            "document_trees": [],
            "tree_registry": {},
        }

    user_id = str((runtime.context.user_id if runtime.context else "") or "").strip()
    if not user_id:
        return {
            "error": "missing_user_id",
            "document_tree_status": "failed",
            "document_trees": [],
            "tree_registry": {},
        }

    session_id = str((runtime.context.session_id if runtime.context else "") or "").strip()
    raw_scope = str(state.get("query_scope") or "").strip().lower()
    try:
        query_scope = raw_scope or await determine_query_scope(
            str(state.get("user_input") or ""),
            has_files=bool(file_ids),
        )
        retrieval_budget = state.get("retrieval_budget") or scope_budget(query_scope)
    except Exception as exc:
        return {
            "status": "failed",
            "evidence_status": "failed",
            "error": f"query_scope_resolution_failed:{str(exc)}",
            "document_tree_status": "failed",
            "message": "Unable to determine the search range, please try again.",
            "document_trees": [],
            "tree_registry": {},
        }
    logger.info(
        "file tree scope resolved in planner",
        session_id=session_id or "default",
        user_id=user_id,
        query_scope=query_scope,
        budget=retrieval_budget,
        file_count=len(file_ids),
    )
    history = list((getattr(runtime.context, "conversation_history", []) if runtime.context else []) or [])
    logger.debug(
        "document tree planner history context",
        session_id=session_id or "default",
        user_id=user_id,
        history_count=len(history),
        history_preview=_history_preview(history),
    )
    try:
        registry_result = await build_incremental_document_registry(
            session_id=session_id,
            user_id=user_id,
            file_ids=file_ids,
            user_input=str(state.get("user_input") or ""),
            message_knowledge=str(state.get("message_knowledge") or ""),
            conversation_history=history,
        )
    except Exception as exc:
        logger.warning(
            "document tree build failed, fallback to ragix summary in syllabus",
            session_id=session_id or "default",
            user_id=user_id,
            error=str(exc),
        )
        return {
            "status": "failed",
            "evidence_status": "failed",
            "error": f"document_tree_build_failed:{str(exc)}",
            "document_tree_status": "fallback_to_ragix_summary",
            "document_tree_error": f"document_tree_build_failed:{str(exc)}",
            "query_scope": query_scope,
            "retrieval_budget": retrieval_budget,
            "document_trees": [],
            "tree_registry": {},
        }
    failed_files = list(registry_result.get("failed_files") or [])
    if failed_files:
        first_failed = failed_files[0]
        logger.warning(
            "document tree partial failure, fallback to ragix summary in syllabus",
            session_id=session_id or "default",
            user_id=user_id,
            file_id=str(first_failed.get("file_id") or ""),
        )
        return {
            "status": "failed",
            "evidence_status": "failed",
            "error": f"document_tree_build_failed:{str(first_failed.get('file_id') or '')}",
            "document_tree_status": "fallback_to_ragix_summary",
            "document_tree_error": f"document_tree_build_failed:{str(first_failed.get('file_id') or '')}",
            "query_scope": query_scope,
            "retrieval_budget": retrieval_budget,
            "document_trees": [],
            "tree_registry": {},
        }
    document_trees = list(registry_result.get("document_trees") or [])
    tree_registry = dict(registry_result.get("tree_registry") or {})
    return {
        "document_tree_status": "ready",
        "document_tree_error": None,
        "document_trees": document_trees,
        "tree_registry": tree_registry,
        "query_scope": query_scope,
        "retrieval_budget": retrieval_budget,
    }


async def run_card_scope_planner(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    return await card_scope_supervisor_agent.ainvoke(
        {
            "user_input": state.get("user_input"),
            "file_ids": state.get("file_ids") or [],
            "query_scope": state.get("query_scope"),
            "retrieval_budget": state.get("retrieval_budget") or {},
            "document_trees": state.get("document_trees") or [],
            "candidate_nodes": state.get("candidate_nodes") or [],
            "learning_units": state.get("learning_units") or [],
            "evidence_items": state.get("evidence_items") or [],
            "syllabus_status": state.get("syllabus_status"),
        },
        context=runtime.context,
    )


async def run_evidence_builder(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Single retrieval entrypoint for evidence construction."""
    history = list((getattr(runtime.context, "conversation_history", []) if runtime.context else []) or [])
    logger.debug(
        "evidence builder history context",
        session_id=str((runtime.context.session_id if runtime.context else "") or "").strip() or "default",
        user_id=str((runtime.context.user_id if runtime.context else "") or "").strip() or "unknown",
        history_count=len(history),
        history_preview=_history_preview(history),
    )
    return await evidence_react_agent.ainvoke(
        {
            "user_input": state.get("user_input"),
            "query_scope": state.get("query_scope"),
            "retrieval_budget": state.get("retrieval_budget") or {},
            "candidate_nodes": state.get("candidate_nodes") or [],
            "file_ids": state.get("file_ids") or [],
            "file_tree_path_active": state.get("file_tree_path_active"),
            "evidence_status": state.get("evidence_status"),
            "pending_questions": state.get("pending_questions") or [],
            "evidence_items": state.get("evidence_items") or [],
            "selected_nodes": state.get("selected_nodes") or [],
            "evidence_loop_report": state.get("evidence_loop_report") or {},
            "evidence_store": state.get("evidence_store") or {
                "schema_version": EVIDENCE_STORE_SCHEMA_VERSION,
                "items": [],
                "index": {},
                "reason_code_counts": {},
                "duplicate_query_ratio": 0.0,
                "hit_rate": 0.0,
            },
            "coverage_state": state.get("coverage_state") or {
                "coverage_rate": 0.0,
                "covered_node_ids": [],
                "total_node_count": 0,
            },
            "message_knowledge": state.get("message_knowledge"),
        },
        context=runtime.context,
    )


async def run_card_pipeline(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    file_tree_path_active = bool(state.get("file_tree_path_active"))
    result = await card_aggregation_agent.ainvoke(
        {
            "template_id": state.get("template_id"),
            "template_version": state.get("template_version"),
            "user_input": state.get("user_input"),
            "message_knowledge": state.get("message_knowledge"),
            "subject_domain": state.get("subject_domain"),
            "learning_units": [] if file_tree_path_active else (state.get("scoped_learning_units") or state.get("learning_units") or []),
            "scoped_learning_units": state.get("scoped_learning_units") or [],
            "scope_chunks": state.get("scope_chunks") or [],
            "query_scope": state.get("query_scope"),
            "evidence_items": state.get("evidence_items") or [],
            "document_trees": state.get("document_trees") or [],
            "template_profiles": state.get("template_profiles") or [],
            "template_default_profile": state.get("template_default_profile"),
            "selected_template_profile": state.get("selected_template_profile"),
            "profile_prompt_hint": state.get("profile_prompt_hint") or {},
            "file_ids": state.get("file_ids") or [],
        },
        context=runtime.context,
    )

    approved = result.get("approved_cards") or []
    status = result.get("status", "failed")
    failure_reason = str(result.get("reason") or "").strip()
    workflow_status = "success" if status == "quality_pass" else "failed"
    payload = {
        "status": workflow_status,
        "card_status": status,
        "approved_cards": approved,
        "final_cards": approved if status == "quality_pass" else [],
        "quality_report": result.get("quality_report") or {},
        "qa_loop_report": result.get("qa_loop_report") or {},
        "error": state.get("error") if status == "quality_pass" else failure_reason,
    }
    if file_tree_path_active and failure_reason in {"missing_file_tree_evidence_items", "missing_file_tree_evidence"}:
        payload["error"] = failure_reason
    return payload


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

    final_status, final_status_reason = _derive_final_status(state)
    workflow_error = str(state.get("error") or "").strip()

    cards = list(state.get("final_cards") or [])
    saved_card_ids = list(state.get("saved_card_ids") or [])

    if final_status == "success" and cards and not saved_card_ids:
        saved_card_ids = await save_cards_to_workspace(
            cards,
            workspace_id=workspace_id,
            owner=str((context.user_id if context else "") or ""),
        )
    elif final_status != "success":
        cards = []
        saved_card_ids = []

    if final_status == "failed" and not workflow_error and final_status_reason == "success_without_cards":
        workflow_error = "no_cards_generated"

    if langfuse.enabled:
        try:
            langfuse.flush()
        except Exception:
            pass

    final_message = str(state.get("message") or "").strip()
    if not final_message:
        if final_status == "failed":
            final_message = workflow_error or "Workflow failed"
        elif final_status == "need_user_input":
            final_message = extract_first_question(list(state.get("pending_questions") or [])) or "Additional user input is required to continue."
        elif cards:
            final_message = f"Generated {len(cards)} flashcards"
        else:
            final_message = "Workflow completed successfully"

    logger.debug(
        "workflow finalize status resolution",
        final_status=final_status,
        final_status_reason=final_status_reason,
        explicit_status=str(state.get("status") or "").strip().lower(),
        card_status=str(state.get("card_status") or "").strip().lower(),
        preflight_status=str(state.get("preflight_status") or "").strip().lower(),
        syllabus_status=str(state.get("syllabus_status") or "").strip().lower(),
        card_scope_status=str(state.get("card_scope_status") or "").strip().lower(),
        evidence_status=str(state.get("evidence_status") or "").strip().lower(),
        pending_question_count=len(list(state.get("pending_questions") or [])),
        final_cards_count=len(cards),
        error=workflow_error,
    )

    return {
        "status": final_status,
        "message": final_message,
        "final_cards": cards,
        "approved_cards": cards,
        "saved_card_ids": saved_card_ids,
        "error": workflow_error or None,
        "completed_at": datetime.utcnow().isoformat(),
    }
