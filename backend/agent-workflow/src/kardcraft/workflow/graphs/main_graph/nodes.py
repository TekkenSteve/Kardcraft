"""Thin orchestration nodes for main graph v3 (no legacy runtime dependency)."""

from __future__ import annotations

import hashlib
import re
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
from kardcraft.workflow.graphs.clarification_graph.tool import clarify
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

SOC_PRECHECK_INTENTS = {"create_cards"}
SOC_PREFLIGHT_CONFIDENCE_THRESHOLD = 0.75
SOC_MAX_ROUNDS = 3
SOC_MIN_INFORMATION_GAIN = 0.05


def _extract_first_question(pending_questions: list[dict[str, Any]]) -> str:
    for item in pending_questions:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question_text") or "").strip()
        if text:
            return text
    return ""


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text


def _build_question_id(session_id: str, question_text: str, round_index: int) -> str:
    normalized_question = _normalize_text(question_text)
    seed = f"{session_id}|{normalized_question}|{int(round_index)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"q_{digest}"


def _token_set(value: str) -> set[str]:
    return {tok for tok in _normalize_text(value).split(" ") if tok}


def _information_gain_score(responses: dict[str, str], base_context: str) -> float:
    merged_response = " ".join(str(v).strip() for v in responses.values() if str(v).strip())
    response_tokens = _token_set(merged_response)
    if not response_tokens:
        return 0.0
    base_tokens = _token_set(base_context)
    new_tokens = response_tokens - base_tokens
    return float(len(new_tokens) / max(1, len(response_tokens)))


def _extract_pending_question_ids(pending_questions: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in pending_questions:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id") or "").strip()
        if question_id:
            ids.add(question_id)
    return ids


def _collect_asked_question_texts(existing: Any, pending_questions: list[dict[str, Any]]) -> list[str]:
    asked: list[str] = []
    if isinstance(existing, list):
        asked.extend([str(x).strip() for x in existing if str(x).strip()])
    for item in pending_questions:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question_text") or "").strip()
        if text:
            asked.append(text)
    deduped: list[str] = []
    for text in asked:
        if text not in deduped:
            deduped.append(text)
    return deduped


def _normalize_clarification_responses(raw: Any) -> tuple[dict[str, str], str]:
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "clarification_responses must be an object"

    normalized: dict[str, str] = {}
    for key, value in raw.items():
        question_id = str(key or "").strip()
        if not question_id:
            return {}, "clarification_responses contains empty question id"
        if not isinstance(value, str):
            return {}, f"clarification_responses[{question_id}] must be a string"
        answer = value.strip()
        if not answer:
            return {}, f"clarification_responses[{question_id}] must be a non-empty string"
        normalized[question_id] = answer
    return normalized, ""


def _validate_pending_questions_strict(pending_questions: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(pending_questions, list):
        return [], "pending_questions must be a list"
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(pending_questions):
        if not isinstance(item, dict):
            return [], f"pending_questions[{idx}] must be an object"
        question_id = str(item.get("id") or "").strip()
        question_text = str(item.get("question_text") or "").strip()
        info_type = str(item.get("info_type") or "").strip()
        required = item.get("required")
        input_type = str(item.get("input_type") or "").strip()
        options = item.get("options")
        if not question_id:
            return [], f"pending_questions[{idx}].id is required"
        if not question_text:
            return [], f"pending_questions[{idx}].question_text is required"
        if not info_type:
            return [], f"pending_questions[{idx}].info_type is required"
        if not isinstance(required, bool):
            return [], f"pending_questions[{idx}].required must be boolean"
        if input_type not in {"free_text", "single_select", "multi_select", "file_upload"}:
            return [], f"pending_questions[{idx}].input_type is invalid"
        if not isinstance(options, list):
            return [], f"pending_questions[{idx}].options must be an array"
        normalized.append(
            {
                "id": question_id,
                "question_text": question_text,
                "info_type": info_type,
                "required": required,
                "input_type": input_type,
                "options": [str(x).strip() for x in options if str(x).strip()],
            }
        )
    return normalized, ""


def _normalize_pending_questions_strict(
    pending_questions: Any,
    *,
    session_id: str,
    round_index: int,
) -> list[dict[str, Any]]:
    if not isinstance(pending_questions, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in pending_questions:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            normalized.append(
                {
                    "id": _build_question_id(session_id, text, round_index),
                    "question_text": text,
                    "info_type": "general",
                    "required": True,
                    "input_type": "free_text",
                    "options": [],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        question_text = str(
            item.get("question_text")
            or item.get("question")
            or item.get("text")
            or item.get("content")
            or ""
        ).strip()
        if not question_text:
            continue
        raw_id = str(item.get("id") or item.get("question_id") or "").strip()
        question_id = raw_id or _build_question_id(session_id, question_text, round_index)
        info_type = str(item.get("info_type") or "general").strip() or "general"
        raw_required = item.get("required")
        if isinstance(raw_required, bool):
            required = raw_required
        elif "is_required" in item:
            required = bool(item.get("is_required"))
        else:
            required = True
        input_type = str(item.get("input_type") or "").strip().lower()
        if input_type not in {"free_text", "single_select", "multi_select", "file_upload"}:
            input_type = "free_text"
        raw_options = item.get("options")
        if not isinstance(raw_options, list):
            raw_options = item.get("suggested_answers")
        options = [str(x).strip() for x in (raw_options or []) if str(x).strip()]
        normalized.append(
            {
                "id": question_id,
                "question_text": question_text,
                "info_type": info_type,
                "required": required,
                "input_type": input_type,
                "options": options,
            }
        )
    return normalized[:2]


def _should_trigger_preflight(state: State) -> tuple[bool, str]:
    intent_type = str(state.get("intent_type") or "").strip().lower()
    if intent_type not in SOC_PRECHECK_INTENTS:
        return False, "intent_not_targeted"

    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    if file_ids:
        return False, "has_files"

    message_knowledge = str(state.get("message_knowledge") or "").strip()
    if message_knowledge:
        return False, "has_inline_knowledge"

    driven_mode = str(state.get("driven_mode") or "").strip().lower()
    confidence = float(state.get("classification_confidence") or 0.0)
    low_confidence = confidence < SOC_PREFLIGHT_CONFIDENCE_THRESHOLD
    topic_driven = driven_mode == "topic_driven"
    if not low_confidence and not topic_driven:
        return False, "signals_sufficient"
    return True, "topic_or_low_confidence"


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
        "preflight_status": None,
        "preflight_reason": None,
        "clarification_state": None,
        "termination_reason": None,
        "clarification_round": 0,
        "max_rounds": SOC_MAX_ROUNDS,
        "clarification_responses": {},
        "asked_questions": [],
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
    pending_questions, pending_error = _validate_pending_questions_strict(pending_questions_raw)
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
    clarification_responses, response_error = _normalize_clarification_responses(raw_responses)
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
        question = _extract_first_question(pending_questions)
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

    should_trigger, reason = _should_trigger_preflight(state)
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
        allowed_ids = _extract_pending_question_ids(pending_questions)
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
    asked_questions = _collect_asked_question_texts(
        state.get("asked_questions"),
        pending_questions,
    )

    if clarification_responses and pending_questions:
        if _information_gain_score(clarification_responses, message_knowledge) < SOC_MIN_INFORMATION_GAIN:
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
    pending_questions, pending_error = _validate_pending_questions_strict(pending_questions_raw)
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
        question = _extract_first_question(pending_questions)
        updated_asked = _collect_asked_question_texts(asked_questions, pending_questions)
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
    supervisor_status = str(result.get("status") or "failed").strip().lower()
    normalized_pending = _normalize_pending_questions_strict(
        result.get("pending_questions") or [],
        session_id=str(context.session_id or ""),
        round_index=int(state.get("clarification_round") or 1),
    )
    payload: Dict[str, Any] = {
        "syllabus_status": result.get("status", "failed"),
        "learning_units": result.get("learning_units") or [],
        "pending_questions": normalized_pending,
        "clarification_responses": result.get("clarification_responses") or {},
        "error": state.get("error") if result.get("status") != "failed" else result.get("reason"),
    }
    if supervisor_status == "need_user_input":
        payload.update(
            {
                "status": "need_user_input",
                "clarification_state": "collecting",
                "termination_reason": None,
                "preflight_status": "need_user_input",
                "preflight_reason": str(result.get("reason") or "syllabus_need_user_input"),
                "message": _extract_first_question(normalized_pending)
                or "Additional user input is required to continue.",
            }
        )
    elif supervisor_status == "failed":
        payload.update(
            {
                "status": "failed",
                "clarification_state": "exhausted",
                "termination_reason": str(result.get("reason") or "syllabus_failed"),
            }
        )
    else:
        payload.update(
            {
                "status": "success",
                "clarification_state": state.get("clarification_state") or "resolved",
                "termination_reason": None,
            }
        )
    return payload


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
    supervisor_status = str(result.get("status") or "failed").strip().lower()
    normalized_pending = _normalize_pending_questions_strict(
        result.get("pending_questions") or [],
        session_id=str(context.session_id or ""),
        round_index=int(state.get("clarification_round") or 1),
    )
    research_content = str((result.get("research_results") or {}).get("content") or "").strip()

    payload: Dict[str, Any] = {
        "evidence_status": result.get("status", "failed"),
        "pending_questions": normalized_pending,
        "research_results": result.get("research_results") or {},
        "error": state.get("error") if result.get("status") != "failed" else result.get("reason"),
    }
    if supervisor_status == "need_user_input":
        payload.update(
            {
                "status": "need_user_input",
                "clarification_state": "collecting",
                "termination_reason": None,
                "message": _extract_first_question(normalized_pending)
                or "Additional user input is required to continue.",
            }
        )
    elif supervisor_status == "failed":
        payload.update(
            {
                "status": "failed",
                "clarification_state": "exhausted",
                "termination_reason": str(result.get("reason") or "evidence_failed"),
            }
        )
    else:
        payload.update(
            {
                "status": "success",
                "clarification_state": state.get("clarification_state") or "resolved",
                "termination_reason": None,
            }
        )
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
