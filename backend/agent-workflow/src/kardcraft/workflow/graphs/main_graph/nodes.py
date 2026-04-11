"""Thin orchestration nodes for main graph v3 (no legacy runtime dependency)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.card_templates import (
    TemplatePreparationError,
    prepare_template_context_for_main_graph,
)
from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.utils.document_registry import build_incremental_document_registry
from kardcraft.utils.language import detect_preferred_language_with_llm
from kardcraft.utils.logger import logger
from kardcraft.utils.main_graph_helpers import (
    collect_asked_question_texts,
    determine_query_scope,
    extract_first_question,
    extract_pending_question_ids,
    information_gain,
    information_gain_score,
    is_file_tree_path_enabled,
    normalize_clarification_responses,
    normalize_pending_questions_strict,
    scope_budget,
    select_candidate_nodes,
    separate_content_and_task,
    should_trigger_preflight,
    validate_pending_questions_strict,
)
from kardcraft.workflow.graphs.main_graph.rollout_gate import rollout_enabled_for_user
from kardcraft.workflow.graphs.clarification_graph.tool import clarify
from kardcraft.workflow.graphs.main_graph.prompt import build_node_query
from kardcraft.workflow.graphs.main_graph.state import (
    EVIDENCE_STORE_SCHEMA_VERSION,
    Context,
    State,
)
from kardcraft.workflow.graphs.main_graph.subgraph.card_supervisor_agent import (
    card_supervisor_agent,
)
from kardcraft.workflow.graphs.main_graph.subgraph.intent_classifier_agent import intent_classifier

SOC_MAX_ROUNDS = 3
SOC_MIN_INFORMATION_GAIN = 0.05

FILE_TREE_PATH_MODEL_ENV = "KARD_FILE_TREE_PAGEINDEX_MODEL"
QA_SAFETY_CAP_ENV = "KARD_QA_SAFETY_CAP"


def _normalize_query_key(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


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
        "evidence_skillrouter_rollout": rollout,
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
    """Strict v2 preflight with deterministic multi-round clarification control."""
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
            "candidate_nodes": [],
        }

    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    if not file_ids:
        return {
            "error": "missing_file_ids",
            "document_tree_status": "failed",
            "document_trees": [],
            "tree_registry": {},
            "candidate_nodes": [],
        }

    user_id = str((runtime.context.user_id if runtime.context else "") or "").strip()
    if not user_id:
        return {
            "error": "missing_user_id",
            "document_tree_status": "failed",
            "document_trees": [],
            "tree_registry": {},
            "candidate_nodes": [],
        }

    model = str(os.getenv(FILE_TREE_PATH_MODEL_ENV) or "").strip() or None
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
            "message": "无法确定检索范围，请重试。",
            "document_trees": [],
            "tree_registry": {},
            "candidate_nodes": [],
        }
    logger.info(
        "file tree scope resolved in planner",
        session_id=session_id or "default",
        user_id=user_id,
        query_scope=query_scope,
        budget=retrieval_budget,
        file_count=len(file_ids),
    )
    try:
        registry_result = await build_incremental_document_registry(
            session_id=session_id,
            user_id=user_id,
            file_ids=file_ids,
            user_input=str(state.get("user_input") or ""),
            message_knowledge=str(state.get("message_knowledge") or ""),
            conversation_history=list((getattr(runtime.context, "conversation_history", []) if runtime.context else []) or []),
            model=model,
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
            "candidate_nodes": [],
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
            "candidate_nodes": [],
        }
    document_trees = list(registry_result.get("document_trees") or [])
    tree_registry = dict(registry_result.get("tree_registry") or {})
    candidate_nodes = select_candidate_nodes(
        document_trees=document_trees,
        user_input=str(state.get("user_input") or ""),
        query_scope=query_scope,
        retrieval_budget=retrieval_budget,
    )

    if not candidate_nodes:
        return {
            "document_tree_status": "empty_candidates",
            "document_tree_error": None,
            "document_trees": document_trees,
            "tree_registry": tree_registry,
            "candidate_nodes": [],
            "evidence_status": "need_user_input",
            "message": "未找到可用于制卡的文档结构节点，请重试或重新上传文件。",
            "query_scope": query_scope,
            "retrieval_budget": retrieval_budget,
        }
    return {
        "document_tree_status": "ready",
        "document_tree_error": None,
        "document_trees": document_trees,
        "tree_registry": tree_registry,
        "candidate_nodes": candidate_nodes,
        "query_scope": query_scope,
        "retrieval_budget": retrieval_budget,
    }


async def run_evidence_loop(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    candidates = list(state.get("candidate_nodes") or [])
    if not candidates:
        return {
            "evidence_status": "need_user_input",
            "pending_questions": [],
            "evidence_items": [],
            "selected_nodes": [],
            "evidence_loop_report": {
                "rag_calls": 0,
                "stop_reason": "no_candidate_nodes",
                "candidate_nodes": 0,
                "selected_nodes": 0,
            },
        }

    query_scope = str(state.get("query_scope") or "").strip().lower()
    if not query_scope:
        return {
            "evidence_status": "failed",
            "pending_questions": [],
            "evidence_items": [],
            "selected_nodes": [],
            "evidence_loop_report": {
                "rag_calls": 0,
                "stop_reason": "missing_query_scope",
                "candidate_nodes": len(candidates),
                "selected_nodes": 0,
            },
            "error": "missing_query_scope",
        }
    budget = dict(state.get("retrieval_budget") or scope_budget(query_scope))
    max_nodes_per_round = int(budget.get("max_nodes_per_round") or 2)
    max_rag_calls = int(budget.get("max_rag_calls") or 6)
    min_gain = float(budget.get("min_information_gain") or 0.05)
    low_gain_limit = int(budget.get("consecutive_low_gain_limit") or 2)
    top_k = 4 if query_scope == "title_only" else 6

    session_id = str((runtime.context.session_id if runtime.context else "") or "").strip() or None
    user_id = str((runtime.context.user_id if runtime.context else "") or "").strip() or None
    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    user_input = str(state.get("user_input") or "").strip()
    file_tree_path_active = bool(state.get("file_tree_path_active"))
    query_mode = "mix"

    rag_calls = 0
    low_gain_rounds = 0
    cursor = 0
    stop_reason = "budget_exhausted"
    rewrite_used = False
    selected_nodes: List[Dict[str, Any]] = []
    evidence_items: List[Dict[str, Any]] = []
    gains: List[float] = []
    aggregated_knowledge = ""
    seen_query_keys: set[str] = set()
    duplicate_queries = 0
    hit_count = 0
    miss_count = 0
    retrieval_events: List[Dict[str, Any]] = []

    while cursor < len(candidates) and rag_calls < max_rag_calls:
        round_nodes = candidates[cursor : cursor + max_nodes_per_round]
        cursor += max_nodes_per_round
        if not round_nodes:
            break

        for node in round_nodes:
            if rag_calls >= max_rag_calls:
                stop_reason = "max_rag_calls_reached"
                break
            query = build_node_query(
                user_input,
                node,
                include_user_input=True,
            )
            if not query:
                continue
            query_key = _normalize_query_key(query)
            if query_key in seen_query_keys:
                duplicate_queries += 1
                retrieval_events.append({"query": query, "reason_code": "duplicate"})
                continue
            seen_query_keys.add(query_key)
            rag_calls += 1
            result = await query_knowledge.ainvoke(
                {
                    "query": query,
                    "mode": query_mode,
                    "top_k": top_k,
                    "session_id": session_id,
                    "file_ids": file_ids,
                    "user_id": user_id,
                }
            )
            content = str(result.get("content") or "").strip()
            refs = result.get("refs") or []
            gain = information_gain(content, aggregated_knowledge)
            gains.append(round(gain, 4))
            if content:
                hit_count += 1
                retrieval_events.append({"query": query, "reason_code": "hit"})
                selected_nodes.append(node)
                evidence_items.append(
                    {
                        "query": query,
                        "content": content[:2000],
                        "refs": refs,
                        "node": node,
                        "information_gain": gain,
                        "reason_codes": ["hit"],
                    }
                )
                aggregated_knowledge = f"{aggregated_knowledge}\n\n{content[:2000]}".strip()
            else:
                miss_count += 1
                retrieval_events.append({"query": query, "reason_code": "miss"})
            if gain < min_gain:
                low_gain_rounds += 1
            else:
                low_gain_rounds = 0

            if query_scope == "title_only" and evidence_items:
                stop_reason = "title_only_sufficient"
                break
            if low_gain_rounds >= low_gain_limit:
                stop_reason = "low_information_gain"
                break

        if stop_reason in {"title_only_sufficient", "low_information_gain", "max_rag_calls_reached"}:
            break

    if not evidence_items and rag_calls < max_rag_calls:
        rewrite_used = not file_tree_path_active
        fallback_node = candidates[0] if candidates else {}
        if file_tree_path_active:
            fallback_query = build_node_query(
                user_input,
                fallback_node,
                include_user_input=True,
            )
            if not fallback_query:
                fallback_query = (
                    "Extract concrete key facts, definitions, and core concepts from the uploaded file "
                    "for flashcard generation."
                )
        else:
            fallback_query = (
                f"Document title only: {user_input}" if query_scope == "title_only" else f"Key points for card generation: {user_input}"
            )
        if not fallback_query:
            fallback_query = user_input
        rag_calls += 1
        fallback = await query_knowledge.ainvoke(
            {
                "query": fallback_query,
                "mode": query_mode,
                "top_k": top_k,
                "session_id": session_id,
                "file_ids": file_ids,
                "user_id": user_id,
            }
        )
        fallback_content = str(fallback.get("content") or "").strip()
        if fallback_content:
            hit_count += 1
            retrieval_events.append({"query": fallback_query, "reason_code": "hit"})
            evidence_items.append(
                {
                    "query": fallback_query,
                    "content": fallback_content[:2000],
                    "refs": fallback.get("refs") or [],
                    "node": None,
                    "information_gain": information_gain(fallback_content, aggregated_knowledge),
                    "reason_codes": ["hit"],
                }
            )
            aggregated_knowledge = f"{aggregated_knowledge}\n\n{fallback_content[:2000]}".strip()
            stop_reason = "fallback_rewrite_hit"
        else:
            miss_count += 1
            retrieval_events.append({"query": fallback_query, "reason_code": "miss"})
            stop_reason = "fallback_rewrite_miss"

    if evidence_items and stop_reason == "budget_exhausted":
        stop_reason = "evidence_sufficient"

    status = "evidence_ready" if evidence_items else "need_user_input"
    pending_questions: List[Dict[str, Any]] = []
    if status != "evidence_ready":
        pending_questions = [
            {
                "question_id": 1,
                "question_text": "No valid information has been extracted currently. Please provide a more specific scope or re-upload the file.",
                "info_type": "evidence_context",
                "is_required": True,
                "suggested_answers": [],
            }
        ]

    report = {
        "scope": query_scope,
        "rag_calls": rag_calls,
        "candidate_nodes": len(candidates),
        "selected_nodes": len(selected_nodes),
        "information_gain_trace": gains,
        "stop_reason": stop_reason,
        "rewrite_used": rewrite_used,
        "evidence_hit_rate": round(hit_count / max(1, rag_calls), 4),
        "duplicate_query_count": duplicate_queries,
        "duplicate_query_ratio": round(duplicate_queries / max(1, (rag_calls + duplicate_queries)), 4),
        "coverage_rate": round(len(selected_nodes) / max(1, len(candidates)), 4),
        "reason_code_counts": {
            "hit": hit_count,
            "miss": miss_count,
            "duplicate": duplicate_queries,
            "coverage_gap": max(0, len(candidates) - len(selected_nodes)),
        },
        "retrieval_events": retrieval_events[:50],
    }
    logger.info(
        "evidence loop completed",
        session_id=session_id or "default",
        report=report,
    )
    return {
        "evidence_status": status,
        "pending_questions": pending_questions,
        "selected_nodes": selected_nodes,
        "evidence_items": evidence_items,
        "evidence_store": {
            "schema_version": EVIDENCE_STORE_SCHEMA_VERSION,
            "items": evidence_items,
            "index": {
                _normalize_query_key(str(item.get("query") or "")): str(item.get("query") or "")
                for item in evidence_items
                if isinstance(item, dict) and str(item.get("query") or "").strip()
            },
            "reason_code_counts": report.get("reason_code_counts", {}),
            "duplicate_query_ratio": report.get("duplicate_query_ratio", 0.0),
            "hit_rate": report.get("evidence_hit_rate", 0.0),
        },
        "coverage_state": {
            "coverage_rate": report.get("coverage_rate", 0.0),
            "covered_node_ids": [
                str(node.get("node_id") or "").strip()
                for node in selected_nodes
                if isinstance(node, dict) and str(node.get("node_id") or "").strip()
            ],
            "total_node_count": len(candidates),
        },
        "evidence_loop_report": report,
        "synthesized_knowledge": aggregated_knowledge[:8000],
        "message_knowledge": aggregated_knowledge[:8000],
        "research_results": {"content": aggregated_knowledge[:8000], "evidence_items": evidence_items},
    }


async def run_evidence_builder(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Single retrieval entrypoint for evidence construction."""
    return await run_evidence_loop(state, runtime)


async def run_card_supervisor(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    file_tree_path_active = bool(state.get("file_tree_path_active"))
    current_retry_count = int(state.get("evidence_retry_count") or 0)
    qa_safety_cap = max(3, min(20, int(os.getenv(QA_SAFETY_CAP_ENV, "8"))))
    result = await card_supervisor_agent.ainvoke(
        {
            "user_input": state.get("user_input"),
            "message_knowledge": state.get("message_knowledge"),
            "subject_domain": state.get("subject_domain"),
            "learning_units": [] if file_tree_path_active else (state.get("learning_units") or []),
            "query_scope": state.get("query_scope"),
            "evidence_items": state.get("evidence_items") or [],
            "document_trees": state.get("document_trees") or [],
            "template_profiles": state.get("template_profiles") or [],
            "template_default_profile": state.get("template_default_profile"),
            "selected_template_profile": state.get("selected_template_profile"),
            "file_ids": state.get("file_ids") or [],
            "judge_score_threshold": 90,
            "max_qa_iterations": qa_safety_cap,
            "min_evidence_coverage": 0.60,
            "min_gain_delta": 0.02,
            "language": state.get("language"),
        },
        context=context,
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
    retryable_file_tree_failure = file_tree_path_active and failure_reason in {
        "missing_file_tree_evidence_items",
        "missing_file_tree_evidence",
    }
    if retryable_file_tree_failure and current_retry_count < 1:
        base_budget = dict(state.get("retrieval_budget") or {})
        if not base_budget:
            query_scope = str(state.get("query_scope") or "focused").strip().lower() or "focused"
            base_budget = scope_budget(query_scope)
        expanded_budget = dict(base_budget)
        expanded_budget["max_rag_calls"] = int(expanded_budget.get("max_rag_calls") or 6) + 4
        expanded_budget["max_nodes_per_round"] = int(expanded_budget.get("max_nodes_per_round") or 2) + 1
        expanded_budget["consecutive_low_gain_limit"] = int(expanded_budget.get("consecutive_low_gain_limit") or 2) + 1
        payload["evidence_retry_count"] = current_retry_count + 1
        payload["retrieval_budget"] = expanded_budget
        logger.warning(
            "card supervisor requested evidence retry",
            session_id=str((context.session_id if context else "") or "") or "default",
            reason=failure_reason,
            retry_count=current_retry_count + 1,
            expanded_budget=expanded_budget,
        )
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

    explicit_status = str(state.get("status") or "").strip().lower()
    card_status = str(state.get("card_status") or "").strip().lower()
    workflow_error = str(state.get("error") or "").strip()

    if explicit_status == "need_user_input":
        final_status = "need_user_input"
    elif explicit_status == "failed" or workflow_error:
        final_status = "failed"
    elif card_status:
        final_status = "success" if card_status == "quality_pass" else "failed"
    else:
        final_status = "success"

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

    if langfuse.enabled:
        try:
            langfuse.flush()
        except Exception:
            pass

    final_message = str(state.get("message") or "").strip()
    if not final_message:
        if final_status == "failed":
            final_message = str(state.get("error") or "").strip() or "Workflow failed"
        elif final_status == "need_user_input":
            final_message = "Additional user input is required to continue."
        elif cards:
            final_message = f"Generated {len(cards)} flashcards"
        else:
            final_message = "Workflow completed successfully"

    return {
        "status": final_status,
        "message": final_message,
        "final_cards": cards,
        "approved_cards": cards,
        "saved_card_ids": saved_card_ids,
        "completed_at": datetime.utcnow().isoformat(),
    }
