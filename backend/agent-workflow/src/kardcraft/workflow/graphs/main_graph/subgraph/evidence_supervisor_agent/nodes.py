"""Nodes for evidence supervisor agent (ReAct)."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from kardcraft.tools.knowledge_tools import (
    fetch_file_excerpt,
    index_file_to_ragix,
    list_history_files,
    query_knowledge,
)
from kardcraft.workflow.graphs.main_graph.state import Context
from kardcraft.workflow.graphs.deep_research_graph import deep_research_graph
from kardcraft.utils.react_runtime import run_react_structured

from .prompt import resolve_prompt
from .state import EvidenceSupervisorState

MAX_NEW_FILE_FETCH_PER_TURN = 3
MAX_EXCERPT_CHARS_PER_TURN = 16000
MAX_LAZY_INDEX_RETRIES = 2


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
    refs = rag.get("refs") or []
    return {"content": content, "refs": refs}


@tool
async def fetch_history_file_excerpts(
    query: str,
    session_id: str | None,
    file_ids: List[str],
    user_id: str | None,
    max_files: int = MAX_NEW_FILE_FETCH_PER_TURN,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS_PER_TURN,
) -> Dict[str, Any]:
    """Fetch targeted excerpts from session history files when ragix retrieval misses."""
    if not session_id or not user_id:
        return {"content": "", "items": [], "source_file_ids": []}

    candidates = [fid for fid in (file_ids or []) if isinstance(fid, str) and fid.strip()]
    if not candidates:
        listed = await list_history_files.ainvoke(
            {
                "session_id": session_id,
                "user_id": user_id,
            }
        )
        listed_files = listed.get("files") or []
        candidates = [
            str(item.get("file_id") or "").strip()
            for item in listed_files
            if isinstance(item, dict) and str(item.get("file_id") or "").strip()
        ]

    if not candidates:
        return {"content": "", "items": [], "source_file_ids": []}

    per_file_chars = max(1200, int(max_excerpt_chars / max(1, min(max_files, len(candidates)))))
    selected = candidates[:max_files]
    items: List[Dict[str, Any]] = []
    refs: List[Dict[str, Any]] = []
    for file_id in selected:
        try:
            excerpt = await fetch_file_excerpt.ainvoke(
                {
                    "file_id": file_id,
                    "user_id": user_id,
                    "query": query,
                    "max_chars": per_file_chars,
                }
            )
        except Exception:
            continue
        text = str(excerpt.get("excerpt") or "").strip()
        if not text:
            continue
        excerpt_refs = excerpt.get("refs") or []
        if isinstance(excerpt_refs, list):
            refs.extend([r for r in excerpt_refs if isinstance(r, dict)])
        items.append(
            {
                "source": "file_excerpt",
                "file_id": file_id,
                "filename": excerpt.get("filename"),
                "content": text,
            }
        )

    content = "\n\n".join([str(item.get("content") or "") for item in items]).strip()
    return {
        "content": content,
        "items": items,
        "refs": refs,
        "source_file_ids": [item["file_id"] for item in items if item.get("file_id")],
    }


@tool
async def lazy_index_and_retry_ragix(
    query: str,
    top_k: int,
    session_id: str | None,
    file_ids: List[str],
    user_id: str | None,
    max_retries: int = MAX_LAZY_INDEX_RETRIES,
) -> Dict[str, Any]:
    """Trigger lazy indexing for candidate files, then retry ragix query."""
    if not session_id or not user_id:
        return {
            "content": "",
            "indexed_file_ids": [],
            "attempts": 0,
            "error": "missing session_id/user_id",
        }

    candidates = [fid for fid in (file_ids or []) if isinstance(fid, str) and fid.strip()]
    if not candidates:
        listed = await list_history_files.ainvoke(
            {
                "session_id": session_id,
                "user_id": user_id,
            }
        )
        listed_files = listed.get("files") or []
        candidates = [
            str(item.get("file_id") or "").strip()
            for item in listed_files
            if isinstance(item, dict) and str(item.get("file_id") or "").strip()
        ]

    if not candidates:
        return {
            "content": "",
            "indexed_file_ids": [],
            "attempts": 0,
            "error": "no candidate files",
        }

    indexed_file_ids: List[str] = []
    attempts = 0
    for attempt in range(max(1, max_retries)):
        attempts = attempt + 1
        for file_id in candidates[:MAX_NEW_FILE_FETCH_PER_TURN]:
            try:
                idx = await index_file_to_ragix.ainvoke(
                    {
                        "session_id": session_id,
                        "file_id": file_id,
                        "user_id": user_id,
                    }
                )
                if str(idx.get("status") or "").strip() in {"indexed", "submitted"}:
                    indexed_file_ids.append(file_id)
            except Exception:
                continue

        rag = await query_ragix_evidence.ainvoke(
            {
                "query": query,
                "top_k": top_k,
                "session_id": session_id,
                "file_ids": candidates,
                "user_id": user_id,
            }
        )
        content = str(rag.get("content") or "").strip()
        if content:
            return {
                "content": content,
                "indexed_file_ids": sorted(set(indexed_file_ids)),
                "attempts": attempts,
            }

    return {
        "content": "",
        "indexed_file_ids": sorted(set(indexed_file_ids)),
        "attempts": attempts,
    }


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
    strategy_trace: List[str] = []
    has_uploaded_files = bool(state.get("file_ids") or [])
    rag_content = ""
    rag_refs: List[Dict[str, Any]] = []
    first = learning_units[0]
    rag_query = f"{user_input}\n{first.get('title', '')}\n{first.get('content_summary', '')}".strip()
    excerpt_result: Dict[str, Any] = {}
    excerpt_content = ""
    excerpt_refs: List[Dict[str, Any]] = []
    # File-driven path: always try direct file excerpt first so downstream cards are grounded
    # in uploaded file content, not generic retrieval fallback.
    if has_uploaded_files:
        strategy_trace.append("fetch_file_excerpt")
        excerpt_result = await fetch_history_file_excerpts.ainvoke(
            {
                "query": rag_query or user_input,
                "session_id": context.session_id if context else None,
                "file_ids": state.get("file_ids") or [],
                "user_id": context.user_id if context else None,
                "max_files": MAX_NEW_FILE_FETCH_PER_TURN,
                "max_excerpt_chars": MAX_EXCERPT_CHARS_PER_TURN,
            }
        )
        excerpt_content = str(excerpt_result.get("content") or "").strip()
        excerpt_refs = excerpt_result.get("refs") or []

    strategy_trace.append("search_ragix")
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
    rag_refs = rag_result.get("refs") or []

    lazy_index_result: Dict[str, Any] = {}
    lazy_index_content = ""
    if not rag_content and not excerpt_content and has_uploaded_files:
        strategy_trace.append("lazy_index_retry")
        lazy_index_result = await lazy_index_and_retry_ragix.ainvoke(
            {
                "query": rag_query or user_input,
                "top_k": 8,
                "session_id": context.session_id if context else None,
                "file_ids": state.get("file_ids") or [],
                "user_id": context.user_id if context else None,
                "max_retries": MAX_LAZY_INDEX_RETRIES,
            }
        )
        lazy_index_content = str(lazy_index_result.get("content") or "").strip()

    deep_result: Dict[str, Any] = {}
    deep_content = ""
    # If user has uploaded files, do not use deep research to fabricate/replace missing
    # file evidence. Force an explicit evidence-missing outcome instead.
    if not has_uploaded_files and not rag_content and not excerpt_content and not lazy_index_content:
        strategy_trace.append("deep_research")
        deep_result = await invoke_deep_research.ainvoke({"query": user_input})
        deep_content = str(deep_result.get("content") or "").strip()

    content = rag_content or excerpt_content or lazy_index_content or deep_content

    # Deterministic gating:
    # - Any non-empty evidence content => evidence_ready
    # - No content => need_user_input
    #
    # This avoids LLM decision instability overriding concrete evidence.
    decision: Dict[str, Any] = {"status": "need_user_input", "reason": "insufficient_evidence"}
    status = "evidence_ready" if content else "need_user_input"

    evidence_items = deep_result.get("evidence_items") or []
    if rag_content and not evidence_items:
        evidence_items = [{"source": "ragix", "content": rag_content}]
    if excerpt_content:
        evidence_items = excerpt_result.get("items") or evidence_items
    if lazy_index_content and not evidence_items:
        evidence_items = [
            {
                "source": "ragix_lazy_index_retry",
                "content": lazy_index_content,
                "indexed_file_ids": lazy_index_result.get("indexed_file_ids") or [],
            }
        ]
    refs: List[Dict[str, Any]] = []
    for collection in (rag_refs, excerpt_refs):
        if isinstance(collection, list):
            refs.extend([item for item in collection if isinstance(item, dict)])
    if lazy_index_content and not refs:
        refs.append(
            {
                "ref_id": "ragix_lazy_index_retry",
                "source_type": "ragix",
                "source_id": ",".join(lazy_index_result.get("indexed_file_ids") or []),
                "title": "Ragix lazy index retry",
                "snippet": lazy_index_content[:800],
                "score": None,
                "metadata": {"attempts": int(lazy_index_result.get("attempts") or 0)},
            }
        )

    pending_questions: List[Dict[str, Any]] = []
    if not content and status != "failed":
        status = "need_user_input"
    if has_uploaded_files and not (excerpt_content or lazy_index_content or rag_content):
        status = "need_user_input"
    if status == "need_user_input" and not pending_questions:
        pending_questions = [
            {
                "question_id": 1,
                "question_text": "当前未能从已上传文件提取到可用证据，请重传文件或稍后重试。",
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
            "refs": refs,
            "coverage_score": deep_result.get("coverage_score"),
            "gaps": deep_result.get("gaps") or [],
            "trace": {
                **(deep_result.get("trace") or {}),
                "strategy_trace": strategy_trace,
                "rag_hit": bool(rag_content),
                "excerpt_hit": bool(excerpt_content),
                "lazy_index_hit": bool(lazy_index_content),
                "lazy_index_attempts": int(lazy_index_result.get("attempts") or 0),
            },
            "strategy_trace": strategy_trace,
        }
        if content
        else {},
    }
