"""Nodes for syllabus supervisor agent."""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.agent_skills import SkillSelectorUnavailableError
from kardcraft.ragix import RagixClient
from kardcraft.utils.logger import logger
from kardcraft.utils.main_graph_helpers import (
    determine_query_scope,
    scope_budget,
    select_candidate_nodes,
)
from kardcraft.workflow.graphs.main_graph.state import Context

from .state import State
from .utils import (
    _augment_learning_units_with_sources,
    _candidate_nodes_from_outline,
    _deep_research_summary,
    _ensure_outline_source_links,
    _flatten_outline_nodes,
    _generate_outline_with_llm,
    _outline_sources_from_candidate_nodes,
    _resolve_doc_title,
    _syllabus_failed,
)


async def _collect_lightrag_file_summaries(
    *,
    session_id: str | None,
    user_id: str | None,
    file_ids: List[str],
) -> List[Dict[str, Any]]:
    if not session_id or not user_id or not file_ids:
        return []
    ragix = RagixClient()
    try:
        await ragix.initialize()
        return await ragix.get_file_track_summaries(
            session_id=session_id,
            user_id=user_id,
            file_ids=file_ids,
        )
    finally:
        await ragix.shutdown()


async def _resolve_query_scope_and_budget(state: State, user_input: str) -> tuple[str, Dict[str, Any]]:
    raw_scope = str(state.get("query_scope") or "").strip().lower()
    query_scope = raw_scope or await determine_query_scope(user_input, has_files=bool(state.get("file_ids") or []))
    retrieval_budget = dict(state.get("retrieval_budget") or scope_budget(query_scope))
    return query_scope, retrieval_budget


async def prepare_syllabus_supervisor_inputs_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    return {
        "_user_input": str(state.get("user_input") or "").strip(),
        "_file_ids": [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()],
        "_driven_mode": str(state.get("driven_mode") or "").strip().lower(),
        "_file_tree_path_active": bool(state.get("file_tree_path_active")),
        "_session_id": str((context.session_id if context else "") or "").strip() or None,
        "_user_id": str((context.user_id if context else "") or "").strip() or None,
        "_document_trees": list(state.get("document_trees") or []),
    }


async def validate_syllabus_supervisor_inputs_node(state: State) -> Dict[str, Any]:
    driven_mode = str(state.get("_driven_mode") or state.get("driven_mode") or "").strip().lower()
    file_ids = state.get("_file_ids") if isinstance(state.get("_file_ids"), list) else []

    if driven_mode not in {"topic_driven", "content_driven"}:
        return {
            "_should_terminate": True,
            "_terminal_payload": _syllabus_failed(
                reason="unsupported_driven_mode",
                error=f"unsupported_driven_mode:{driven_mode or 'unknown'}",
            ),
        }

    if driven_mode == "content_driven" and not file_ids:
        return {
            "_should_terminate": True,
            "_terminal_payload": _syllabus_failed(
                reason="content_driven_requires_files",
                error="content_driven_requires_files",
            ),
        }

    return {"_should_terminate": False}


def route_after_syllabus_supervisor_validation(state: State) -> str:
    return "done" if bool(state.get("_should_terminate")) else "run_generate"


async def run_syllabus_supervisor_generate_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    user_input = str(state.get("_user_input") or state.get("user_input") or "").strip()
    file_ids = state.get("_file_ids") if isinstance(state.get("_file_ids"), list) else [
        str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()
    ]
    driven_mode = str(state.get("_driven_mode") or state.get("driven_mode") or "").strip().lower()
    file_tree_path_active = bool(state.get("_file_tree_path_active"))
    session_id = str(state.get("_session_id") or "").strip() or None
    user_id = str(state.get("_user_id") or "").strip() or None

    outline_nodes: List[Dict[str, Any]] = []
    outline_sources: List[Dict[str, Any]] = []
    evidence_items: List[Dict[str, Any]] = []
    candidate_nodes: List[Dict[str, Any]] = list(state.get("candidate_nodes") or [])
    document_trees = list(state.get("_document_trees") or state.get("document_trees") or [])

    query_scope = None
    retrieval_budget: Dict[str, Any] | None = None

    if driven_mode == "topic_driven":
        research = await _deep_research_summary(user_input)
        if not research:
            return _syllabus_failed(reason="deep_research_empty", error="deep_research_empty")
        outline_sources = [
            {
                "id": "deep_research_1",
                "title": "Deep Research Summary",
                "summary": research[:6000],
                "source_type": "deep_research",
            }
        ]
        try:
            outline_nodes = await _generate_outline_with_llm(
                user_input=user_input,
                language=str(state.get("language") or "en"),
                driven_mode=driven_mode,
                source_kind="deep_research",
                sources=outline_sources,
            )
        except SkillSelectorUnavailableError:
            return _syllabus_failed(
                reason="selector_unavailable",
                error="selector_unavailable",
                outline_sources=outline_sources,
            )
        evidence_items.append(
            {
                "query": user_input,
                "content": research[:2000],
                "refs": [],
                "node": {"node_id": "deep_research_1", "title": "Deep Research Summary", "summary": research[:180]},
                "information_gain": 1.0,
            }
        )
    elif driven_mode == "content_driven":
        try:
            query_scope, retrieval_budget = await _resolve_query_scope_and_budget(state, user_input)
        except Exception as exc:
            return _syllabus_failed(
                reason="query_scope_resolution_failed",
                error=f"query_scope_resolution_failed:{str(exc)}",
            )

        if file_tree_path_active and document_trees and not candidate_nodes:
            candidate_nodes = select_candidate_nodes(
                document_trees=document_trees,
                user_input=user_input,
                query_scope=query_scope,
                retrieval_budget=retrieval_budget,
            )
        if file_tree_path_active and document_trees and candidate_nodes:
            outline_sources = _outline_sources_from_candidate_nodes(candidate_nodes)
            try:
                outline_nodes = await _generate_outline_with_llm(
                    user_input=user_input,
                    language=str(state.get("language") or "en"),
                    driven_mode="content_driven",
                    source_kind="pageindex",
                    sources=outline_sources,
                )
            except SkillSelectorUnavailableError:
                return _syllabus_failed(
                    reason="selector_unavailable",
                    error="selector_unavailable",
                    outline_sources=outline_sources,
                )
        else:
            file_summaries: List[Dict[str, Any]] = []
            try:
                file_summaries = await _collect_lightrag_file_summaries(
                    session_id=session_id,
                    user_id=user_id,
                    file_ids=file_ids,
                )
            except Exception as exc:
                logger.warning(
                    "collect lightrag summaries failed",
                    session_id=session_id or "default",
                    file_count=len(file_ids),
                    error=str(exc),
                )

            if file_summaries:
                combined = "\n\n".join(
                    [
                        f"[{str(item.get('filename') or item.get('file_id') or '')}]"
                        f"\n{str(item.get('summary') or '').strip()}"
                        for item in file_summaries
                        if str(item.get("summary") or "").strip()
                    ]
                ).strip()
                if not combined:
                    combined = str(file_summaries[0].get("summary") or "").strip()

                outline_sources = [
                    {
                        "id": "lightrag_track_summary_1",
                        "title": "LightRAG Track Summary",
                        "summary": combined[:6000],
                        "source_type": "lightrag_track_summary",
                    }
                ]
                try:
                    outline_nodes = await _generate_outline_with_llm(
                        user_input=user_input,
                        language=str(state.get("language") or "en"),
                        driven_mode="content_driven",
                        source_kind="lightrag_track_summary",
                        sources=outline_sources,
                    )
                except SkillSelectorUnavailableError:
                    return _syllabus_failed(
                        reason="selector_unavailable",
                        error="selector_unavailable",
                        outline_sources=outline_sources,
                    )

    if outline_sources:
        outline_nodes = _ensure_outline_source_links(outline_nodes, outline_sources)

    learning_units = _flatten_outline_nodes(outline_nodes, max_units=24)
    learning_units = _augment_learning_units_with_sources(
        learning_units,
        outline_sources,
        max_units=48,
    )
    if not outline_nodes or not learning_units:
        return _syllabus_failed(
            reason="outline_generation_failed",
            error="outline_generation_failed",
            outline_sources=outline_sources,
        )

    logger.info(
        "syllabus outline generated",
        driven_mode=driven_mode,
        source_count=len(outline_sources),
        node_count=len(outline_nodes),
        unit_count=len(learning_units),
        session_id=session_id or "default",
    )

    payload: Dict[str, Any] = {
        "syllabus_status": "outline_ready",
        "learning_units": learning_units,
        "syllabus_outline": outline_nodes,
        "outline_sources": outline_sources,
        "pending_questions": [],
        "clarification_responses": {},
        "status": "success",
        "clarification_state": state.get("clarification_state") or "resolved",
        "termination_reason": None,
    }
    if driven_mode == "content_driven" and query_scope is not None and retrieval_budget is not None:
        payload["query_scope"] = query_scope
        payload["retrieval_budget"] = retrieval_budget
    if evidence_items:
        payload["evidence_items"] = evidence_items
    if file_ids:
        if driven_mode == "content_driven" and candidate_nodes:
            payload["candidate_nodes"] = candidate_nodes
        elif not state.get("candidate_nodes"):
            doc_title = _resolve_doc_title(
                outline_sources=outline_sources,
                document_trees=document_trees,
                file_id=file_ids[0],
            )
            payload["candidate_nodes"] = _candidate_nodes_from_outline(
                outline_nodes,
                doc_title=doc_title,
                file_id=file_ids[0],
            )
    logger.debug(
        "syllabus supervisor output",
        session_id=session_id or "default",
        result=payload,
    )
    return payload


async def run_syllabus_supervisor_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Execute syllabus flow in a single node entrypoint."""
    prepared = await prepare_syllabus_supervisor_inputs_node(state, runtime)
    merged_state: State = {**state, **prepared}
    validated = await validate_syllabus_supervisor_inputs_node(merged_state)
    merged_state = {**merged_state, **validated}
    if route_after_syllabus_supervisor_validation(merged_state) == "done":
        return dict(validated.get("_terminal_payload") or _syllabus_failed(reason="validation_failed", error="validation_failed"))
    return await run_syllabus_supervisor_generate_node(merged_state, runtime)
