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
) -> Dict[str, Any]:
    """调用澄清图进行信息充分性判断与问题生成。"""
    from . import clarification_graph

    config = {"configurable": {"thread_id": f"clarification_{uuid.uuid4().hex[:8]}"}}
    result = await clarification_graph.ainvoke(
        {
            "user_input": user_input,
            "message_knowledge": message_knowledge,
            "file_ids": file_ids or [],
            "language": language,
        },
        config=config,
    )
    if isinstance(result, dict):
        return {
            "status": result.get("status", "failed"),
            "reason": result.get("reason", "clarification_failed"),
            "missing_info": result.get("missing_info") or [],
            "pending_questions": result.get("pending_questions") or [],
        }
    return {
        "status": "failed",
        "reason": "clarification_failed",
        "missing_info": [],
        "pending_questions": [],
    }

