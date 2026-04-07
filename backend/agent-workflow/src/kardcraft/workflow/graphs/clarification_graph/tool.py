"""Tool adapter for clarification graph."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from langchain_core.tools import tool


@tool
async def clarify(
    user_input: str,
    message_knowledge: str = "",
    file_ids: List[str] | None = None,
    language: str | None = None,
    session_id: str | None = None,
    round_index: int = 1,
    asked_questions: List[str] | None = None,
) -> Dict[str, Any]:
    """Use a clarification diagram to judge the sufficiency of information and generate questions."""
    from . import clarification_graph

    config = {"configurable": {"thread_id": f"clarification_{uuid.uuid4().hex[:8]}"}}
    result = await clarification_graph.ainvoke(
        {
            "user_input": user_input,
            "message_knowledge": message_knowledge,
            "file_ids": file_ids or [],
            "language": language,
            "session_id": session_id,
            "round_index": int(round_index) if round_index is not None else 1,
            "asked_questions": asked_questions or [],
        },
        config=config,
    )
    if isinstance(result, dict):
        return {
            "status": result.get("status", "failed"),
            "clarification_state": result.get("clarification_state"),
            "termination_reason": result.get("termination_reason"),
            "reason": result.get("reason", "clarification_failed"),
            "message": result.get("message"),
            "missing_info": result.get("missing_info") or [],
            "pending_questions": result.get("pending_questions") or [],
        }
    return {
        "status": "failed",
        "clarification_state": "exhausted",
        "termination_reason": "clarification_failed",
        "reason": "clarification_failed",
        "message": "Clarification failed.",
        "missing_info": [],
        "pending_questions": [],
    }
