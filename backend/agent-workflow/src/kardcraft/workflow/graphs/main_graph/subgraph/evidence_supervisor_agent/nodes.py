"""Nodes for evidence supervisor agent (ReAct)."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.workflow.graphs.main_graph.state import Context
from kardcraft.workflow.graphs.deep_research_graph import deep_research_graph
from kardcraft.utils.react_runtime import run_react_structured

from .prompt import resolve_prompt
from .state import EvidenceSupervisorState


class EvidenceDecision(BaseModel):
    status: str = Field(description="evidence_ready|need_user_input|failed")
    reason: str = ""


@tool
async def deep_research(query: str) -> str:
    """调用深度研究agent进行复杂搜索和分析。

    输入: 研究查询
    输出: 精炼的研究总结
    """
    import uuid

    config = {"configurable": {"thread_id": f"deep_research_{uuid.uuid4().hex[:8]}"}}
    result = await deep_research_graph.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config=config,
    )
    messages = result.get("messages") if isinstance(result, dict) else None
    if isinstance(messages, list) and messages:
        last = messages[-1]
        return str(getattr(last, "content", last) or "").strip()
    return ""


@tool
async def invoke_deep_research(query: str) -> Dict[str, Any]:
    """Invoke deep research graph and normalize output."""
    content = await deep_research.ainvoke({"query": query})
    return {
        "content": content,
        "evidence_items": [{"source": "deep_research_graph", "content": content}] if content else [],
        "coverage_score": None,
        "gaps": [] if content else ["insufficient_evidence"],
        "trace": {"status": "completed" if content else "empty", "error": None},
    }


@tool
async def query_ragix_evidence(
    query: str,
    top_k: int,
    session_id: str | None,
    file_ids: List[str],
    user_id: str | None,
) -> Dict[str, Any]:
    """Query ragix for evidence fallback."""
    rag = await query_knowledge.ainvoke(
        {
            "query": query,
            "mode": "mix",
            "top_k": top_k,
            "session_id": session_id,
            "file_ids": file_ids,
            "user_id": user_id,
        }
    )
    content = str(rag.get("content") or "").strip()
    return {"content": content}


async def run_evidence_supervisor(
    state: EvidenceSupervisorState,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    learning_units = state.get("learning_units") or []
    if not learning_units:
        return {
            "status": "failed",
            "reason": "missing_learning_units",
            "pending_questions": [],
            "evidence_summary": "",
        }

    existing = str(state.get("synthesized_knowledge") or "").strip()
    if existing:
        return {
            "status": "evidence_ready",
            "reason": "synthesized_knowledge_exists",
            "evidence_summary": existing[:2000],
            "pending_questions": [],
            "research_results": {"content": existing},
        }

    user_input = str(state.get("user_input") or "").strip()
    rag_content = ""
    first = learning_units[0]
    rag_query = f"{user_input}\n{first.get('title', '')}\n{first.get('content_summary', '')}".strip()
    rag_result = await query_ragix_evidence.ainvoke(
        {
            "query": rag_query,
            "top_k": 8,
            "session_id": context.session_id if context else None,
            "file_ids": state.get("file_ids") or [],
            "user_id": context.user_id if context else None,
        }
    )
    rag_content = str(rag_result.get("content") or "").strip()

    deep_result: Dict[str, Any] = {}
    deep_content = ""
    if not rag_content:
        deep_result = await invoke_deep_research.ainvoke({"query": user_input})
        deep_content = str(deep_result.get("content") or "").strip()

    content = rag_content or deep_content

    prompt = resolve_prompt(state.get("language"))
    decision = await run_react_structured(
        prompt=prompt,
        tools=[invoke_deep_research, query_ragix_evidence],
        response_schema=EvidenceDecision,
        user_payload={
            "has_ragix_content": bool(rag_content),
            "has_deep_research_content": bool(deep_content),
            "required_output": "Decide evidence_ready/need_user_input/failed.",
        },
        name="evidence_supervisor_react",
    )

    status = str(decision.get("status") or "").strip()
    if status not in {"evidence_ready", "need_user_input", "failed"}:
        status = "failed"
    # Business-safe constraint: cannot be evidence_ready without any evidence payload.
    if status == "evidence_ready" and not content:
        status = "failed"
    elif content and status != "failed":
        status = "evidence_ready"

    evidence_items = deep_result.get("evidence_items") or []
    if rag_content and not evidence_items:
        evidence_items = [{"source": "ragix", "content": rag_content}]

    pending_questions: List[Dict[str, Any]] = []
    if not content and status != "failed":
        status = "need_user_input"
    if status == "need_user_input" and not pending_questions:
        pending_questions = [
            {
                "question_id": 1,
                "question_text": "当前无法从检索结果中提取足够证据。请补充主题范围、关键知识点，或上传更完整文件。",
                "info_type": "evidence_context",
                "is_required": True,
                "suggested_answers": [],
            }
        ]

    return {
        "status": status,
        "reason": str(decision.get("reason") or "evidence_decision"),
        "evidence_summary": content[:2000] if content else "",
        "pending_questions": pending_questions,
        "research_results": {
            "content": content,
            "evidence_items": evidence_items,
            "coverage_score": deep_result.get("coverage_score"),
            "gaps": deep_result.get("gaps") or [],
            "trace": deep_result.get("trace") or {},
        }
        if content
        else {},
    }
