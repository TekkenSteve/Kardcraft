"""Nodes for clarification graph."""

from __future__ import annotations

from typing import Any, Dict, List

from kardcraft.llm.client import chat_complete
from kardcraft.tools.clarification_tools import generate_clarification_questions
from kardcraft.utils.llm_json import safe_parse_llm_json

from .state import ClarificationGraphState

DEFAULT_MISSING = ["learning_goal", "scope", "source_material"]


async def run_clarification(state: ClarificationGraphState) -> Dict[str, Any]:
    pending = state.get("pending_questions") or []
    if pending:
        return {
            "status": "need_user_input",
            "reason": "pending_questions_exist",
            "missing_info": [],
            "pending_questions": pending,
        }

    user_input = str(state.get("user_input") or "").strip()
    message_knowledge = str(state.get("message_knowledge") or "").strip()
    file_count = len(state.get("file_ids") or [])

    decision = await _assess_information_sufficiency(
        user_input=user_input,
        message_knowledge=message_knowledge,
        file_count=file_count,
    )

    is_sufficient = bool(decision.get("is_sufficient"))
    reason = str(decision.get("reason") or "clarification_decision")
    missing_info = [str(x).strip() for x in (decision.get("missing_info") or []) if str(x).strip()]

    if is_sufficient:
        return {
            "status": "sufficient",
            "reason": reason,
            "missing_info": [],
            "pending_questions": [],
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
    return {
        "status": "need_user_input",
        "reason": reason,
        "missing_info": missing_info,
        "pending_questions": questions,
    }


async def _assess_information_sufficiency(
    *,
    user_input: str,
    message_knowledge: str,
    file_count: int,
) -> Dict[str, Any]:
    system_prompt = (
        "You are a multilingual clarification judge. "
        "Decide whether input is sufficient for accurate flashcard generation. "
        "Return JSON only: "
        "{\"is_sufficient\": bool, \"missing_info\": [string], \"reason\": string}."
    )
    user_prompt = (
        f"user_input:\n{user_input}\n\n"
        f"message_knowledge:\n{message_knowledge}\n\n"
        f"file_count:{file_count}\n"
    )

    try:
        response = await chat_complete(
            intent="classify",
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(
            content,
            default={
                "is_sufficient": False,
                "missing_info": list(DEFAULT_MISSING),
                "reason": "model_parse_fallback",
            },
        )
        if not isinstance(parsed, dict):
            parsed = {}
        is_sufficient = bool(parsed.get("is_sufficient"))
        missing_info = [str(x).strip() for x in (parsed.get("missing_info") or []) if str(x).strip()]
        reason = str(parsed.get("reason") or "model_decision")
        return {
            "is_sufficient": is_sufficient,
            "missing_info": [] if is_sufficient else (missing_info or list(DEFAULT_MISSING)),
            "reason": reason,
        }
    except Exception:
        return {
            "is_sufficient": False,
            "missing_info": list(DEFAULT_MISSING),
            "reason": "model_unavailable",
        }
