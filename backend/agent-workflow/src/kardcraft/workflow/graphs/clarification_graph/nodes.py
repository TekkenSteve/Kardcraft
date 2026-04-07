"""Nodes for clarification graph."""

from __future__ import annotations

from typing import Dict

from kardcraft.tools.clarification_tools import generate_clarification_questions

from .state import State
from .utils import (
    DEFAULT_MISSING,
    assess_information_sufficiency,
    normalize_pending_questions,
)


async def run_clarification(state: State) -> Dict[str, object]:
    session_id = str(state.get("session_id") or "").strip() or "unknown_session"
    try:
        round_index = int(state.get("round_index") or 1)
    except Exception:
        round_index = 1

    asked_questions = [
        str(x).strip() for x in (state.get("asked_questions") or []) if str(x).strip()
    ]
    pending = state.get("pending_questions") or []
    if pending:
        normalized_pending = normalize_pending_questions(
            pending,
            session_id=session_id,
            round_index=round_index,
            asked_questions=asked_questions,
        )
        return {
            "status": "need_user_input",
            "clarification_state": "collecting",
            "termination_reason": None,
            "reason": "pending_questions_exist",
            "missing_info": [],
            "pending_questions": normalized_pending,
            "message": (
                normalized_pending[0]["question_text"]
                if normalized_pending
                else "Additional user input is required."
            ),
        }

    user_input = str(state.get("user_input") or "").strip()
    message_knowledge = str(state.get("message_knowledge") or "").strip()
    file_count = len(state.get("file_ids") or [])

    decision = await assess_information_sufficiency(
        user_input=user_input,
        message_knowledge=message_knowledge,
        file_count=file_count,
    )

    is_sufficient = bool(decision.get("is_sufficient"))
    reason = str(decision.get("reason") or "clarification_decision")
    missing_info = [
        str(x).strip() for x in (decision.get("missing_info") or []) if str(x).strip()
    ]

    if is_sufficient:
        return {
            "status": "success",
            "clarification_state": "resolved",
            "termination_reason": None,
            "reason": reason,
            "missing_info": [],
            "pending_questions": [],
            "message": "",
        }

    if not missing_info:
        missing_info = list(DEFAULT_MISSING)

    questions = await generate_clarification_questions.ainvoke(
        {
            "required_info": missing_info,
            "source_agent": "clarification_graph",
            "target_object": "flashcards",
            "context_summary": user_input,
        }
    )

    normalized_pending = normalize_pending_questions(
        questions,
        session_id=session_id,
        round_index=round_index,
        asked_questions=asked_questions,
    )
    if not normalized_pending:
        return {
            "status": "failed",
            "clarification_state": "exhausted",
            "termination_reason": "clarification_generation_failed",
            "reason": "clarification_generation_failed",
            "missing_info": missing_info,
            "pending_questions": [],
            "message": "Unable to generate actionable clarification questions.",
        }

    return {
        "status": "need_user_input",
        "clarification_state": "collecting",
        "termination_reason": None,
        "reason": reason,
        "missing_info": missing_info,
        "pending_questions": normalized_pending,
        "message": normalized_pending[0]["question_text"],
    }
