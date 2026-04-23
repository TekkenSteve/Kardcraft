"""Nodes for evidence ReAct agent."""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from kardcraft.utils.main_graph_helpers import normalize_pending_questions_strict, scope_budget
from kardcraft.utils.logger import logger
from kardcraft.utils.react_runtime import run_react_structured
from kardcraft.workflow.graphs.main_graph.state import EVIDENCE_STORE_SCHEMA_VERSION, Context

from .state import State
from .tools import (
    EvidenceReactToolContext,
    build_evidence_react_tools,
    normalize_query_key,
)


class EvidenceReactSummary(BaseModel):
    stop_reason: str = Field(default="evidence_sufficient")
    queried_node_ids: List[str] = Field(default_factory=list)


def _min_selected_nodes_for_scope(query_scope: str, candidate_count: int, max_rag_calls: int, max_nodes_per_round: int) -> int:
    if candidate_count <= 0:
        return 0
    scope = str(query_scope or "").strip().lower()
    budget_cap = max(1, min(candidate_count, max_rag_calls))
    if scope == "title_only":
        return 1
    if scope == "focused":
        return min(budget_cap, max(3, max_nodes_per_round))
    return min(budget_cap, max(4, max_nodes_per_round))


def _build_evidence_pending_questions(session_id: str, question_text: str) -> List[Dict[str, Any]]:
    return normalize_pending_questions_strict(
        [
            {
                "question_text": question_text,
                "info_type": "evidence_context",
                "required": True,
                "input_type": "free_text",
                "options": [],
            }
        ],
        session_id=session_id,
        round_index=1,
    )


async def run_evidence_react_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    session_id = str((runtime.context.session_id if runtime.context else "") or "").strip() or "default"
    candidates = list(state.get("candidate_nodes") or [])
    if not candidates:
        return {
            "status": "need_user_input",
            "clarification_state": "collecting",
            "termination_reason": None,
            "evidence_status": "need_user_input",
            "pending_questions": _build_evidence_pending_questions(
                session_id,
                "No candidate sections were found for retrieval. Please specify the target chapter/section or re-upload the file.",
            ),
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

    session_id_opt = session_id or None
    user_id = str((runtime.context.user_id if runtime.context else "") or "").strip() or None
    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    user_input = str(state.get("user_input") or "").strip()

    node_map: Dict[str, Dict[str, Any]] = {}
    for node in candidates:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "").strip()
        if node_id:
            node_map[node_id] = node

    tool_context = EvidenceReactToolContext(
        candidates=candidates,
        node_map=node_map,
        user_input=user_input,
        query_scope=query_scope,
        max_nodes_per_round=max_nodes_per_round,
        max_rag_calls=max_rag_calls,
        min_gain=min_gain,
        low_gain_limit=low_gain_limit,
        top_k=top_k,
        session_id=session_id_opt,
        user_id=user_id,
        file_ids=file_ids,
    )
    react_tools = build_evidence_react_tools(tool_context)

    react_prompt = (
        "You are an evidence retrieval agent for flashcard generation.\n"
        "Use tools to retrieve node-grounded evidence and decide when to stop.\n"
        "Rules:\n"
        "1) Call get_next_nodes to fetch candidate nodes.\n"
        "2) Call query_node_evidence for each selected node id.\n"
        "3) Stop when progress indicates title_only_sufficient, low_information_gain, or max_rag_calls_reached.\n"
        "4) Prefer high-priority nodes first and keep coverage broad.\n"
        "5) Return structured summary with stop_reason and queried_node_ids.\n"
    )

    summary = await run_react_structured(
        prompt=react_prompt,
        tools=react_tools,
        response_schema=EvidenceReactSummary,
        user_payload={
            "user_input": user_input,
            "query_scope": query_scope,
            "budget": budget,
            "candidate_count": len(candidates),
        },
        name="evidence_react_agent",
    )

    if summary:
        proposed_stop_reason = str(summary.get("stop_reason") or tool_context.stop_reason).strip() or tool_context.stop_reason
        if (
            proposed_stop_reason == "low_information_gain"
            and not tool_context.evidence_items
            and tool_context.rag_calls < tool_context.min_rag_calls_before_low_gain_stop()
        ):
            pass
        else:
            tool_context.stop_reason = proposed_stop_reason
    elif tool_context.stop_reason == "budget_exhausted" and tool_context.rag_calls >= max_rag_calls:
        tool_context.stop_reason = "max_rag_calls_reached"

    # Avoid premature "evidence_sufficient" when coverage is too shallow.
    min_selected_nodes = _min_selected_nodes_for_scope(
        query_scope=query_scope,
        candidate_count=len(candidates),
        max_rag_calls=max_rag_calls,
        max_nodes_per_round=max_nodes_per_round,
    )
    prefill_selected = len(tool_context.selected_nodes)
    prefill_rag_calls = tool_context.rag_calls
    while (
        tool_context.rag_calls < max_rag_calls
        and len(tool_context.selected_nodes) < min_selected_nodes
    ):
        next_nodes = tool_context.next_nodes(1)
        if not next_nodes:
            break
        node_id = str(next_nodes[0].get("node_id") or "").strip()
        if not node_id:
            continue
        await tool_context.query_node_evidence(node_id)
        if tool_context.stop_reason in {"low_information_gain", "max_rag_calls_reached"}:
            break

    if len(tool_context.selected_nodes) != prefill_selected or tool_context.rag_calls != prefill_rag_calls:
        logger.debug(
            "evidence coverage topup",
            selected_nodes_before=prefill_selected,
            selected_nodes_after=len(tool_context.selected_nodes),
            rag_calls_before=prefill_rag_calls,
            rag_calls_after=tool_context.rag_calls,
            min_selected_nodes=min_selected_nodes,
            stop_reason=tool_context.stop_reason,
        )

    if tool_context.evidence_items and tool_context.stop_reason == "budget_exhausted":
        tool_context.stop_reason = "evidence_sufficient"

    status = "evidence_ready" if tool_context.evidence_items else "need_user_input"
    pending_questions: List[Dict[str, Any]] = []
    if status != "evidence_ready":
        stop_reason = str(tool_context.stop_reason or "").strip() or "unknown"
        reason_hints = {
            "low_information_gain": "retrieval repeatedly returned low-information snippets",
            "max_rag_calls_reached": "retrieval budget was exhausted without grounded evidence",
            "budget_exhausted": "candidate exploration ended without grounded evidence",
        }
        hint = reason_hints.get(stop_reason, "grounded evidence was not found")
        if tool_context.degraded_zero_ref_count > 0:
            hint = (
                "retrieval repeatedly returned responses without any source references "
                "(possible workspace/runtime degradation)"
            )
        pending_questions = _build_evidence_pending_questions(
            session_id,
            f"No valid information was extracted because {hint}. "
            "Please specify a concrete section/node title (e.g., 题目1/题目2) or re-upload a clearer source file.",
        )

    report = {
        "scope": query_scope,
        "rag_calls": tool_context.rag_calls,
        "candidate_nodes": len(candidates),
        "selected_nodes": len(tool_context.selected_nodes),
        "information_gain_trace": tool_context.gains,
        "stop_reason": tool_context.stop_reason,
        "rewrite_used": False,
        "evidence_hit_rate": round(tool_context.hit_count / max(1, tool_context.rag_calls), 4),
        "duplicate_query_count": tool_context.duplicate_queries,
        "duplicate_query_ratio": round(tool_context.duplicate_queries / max(1, (tool_context.rag_calls + tool_context.duplicate_queries)), 4),
        "coverage_rate": round(len(tool_context.selected_nodes) / max(1, len(candidates)), 4),
        "reason_code_counts": {
            "hit": tool_context.hit_count,
            "miss": tool_context.miss_count,
            "ungrounded": tool_context.ungrounded_count,
            "backend_degraded": tool_context.degraded_zero_ref_count,
            "low_quality": tool_context.low_quality_count,
            "duplicate": tool_context.duplicate_queries,
            "coverage_gap": max(0, len(candidates) - len(tool_context.selected_nodes)),
        },
        "retrieval_events": tool_context.retrieval_events[:50],
    }

    payload: Dict[str, Any] = {
        "evidence_status": status,
        "pending_questions": pending_questions,
        "selected_nodes": tool_context.selected_nodes,
        "evidence_items": tool_context.evidence_items,
        "evidence_store": {
            "schema_version": EVIDENCE_STORE_SCHEMA_VERSION,
            "items": tool_context.evidence_items,
            "index": {
                normalize_query_key(str(item.get("query") or "")): str(item.get("query") or "")
                for item in tool_context.evidence_items
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
                for node in tool_context.selected_nodes
                if isinstance(node, dict) and str(node.get("node_id") or "").strip()
            ],
            "total_node_count": len(candidates),
        },
        "evidence_loop_report": report,
        "synthesized_knowledge": tool_context.aggregated_knowledge[:8000],
        "message_knowledge": tool_context.aggregated_knowledge[:8000],
        "research_results": {
            "content": tool_context.aggregated_knowledge[:8000],
            "evidence_items": tool_context.evidence_items,
        },
    }
    if status != "evidence_ready":
        payload.update(
            {
                "status": "need_user_input",
                "clarification_state": "collecting",
                "termination_reason": None,
                "question": pending_questions[0]["question_text"] if pending_questions else "",
                "message": pending_questions[0]["question_text"] if pending_questions else "Additional user input is required to continue.",
            }
        )
    return payload
