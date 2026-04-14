"""Nodes for card scope supervisor agent."""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.utils.logger import logger
from kardcraft.utils.main_graph_helpers import (
    determine_query_scope,
    scope_budget,
    select_candidate_nodes,
)
from kardcraft.workflow.graphs.main_graph.state import Context

from .state import State


def _scoped_units_from_candidates(
    learning_units: List[Dict[str, Any]],
    candidate_nodes: List[Dict[str, Any]],
    *,
    max_units: int,
) -> List[Dict[str, Any]]:
    if not learning_units:
        return []
    if not candidate_nodes:
        return learning_units[:max_units]
    def _split_unit_id(value: str) -> tuple[str, str]:
        text = str(value or "").strip()
        if ":" not in text:
            return "", text
        file_id, node_id = text.rsplit(":", 1)
        return file_id.strip(), node_id.strip()

    candidate_keys: List[set[str]] = []
    for node in candidate_nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "").strip()
        file_id = str(node.get("file_id") or "").strip()
        if not node_id:
            continue
        keys = {node_id}
        if file_id:
            keys.add(f"{file_id}:{node_id}")
        candidate_keys.append(keys)
    if not candidate_keys:
        return learning_units[:max_units]

    unit_keys: List[set[str]] = []
    for unit in learning_units:
        if not isinstance(unit, dict):
            unit_keys.append(set())
            continue
        uid = str(unit.get("id") or "").strip()
        if not uid:
            unit_keys.append(set())
            continue
        _, node_suffix = _split_unit_id(uid)
        keys = {uid}
        if node_suffix:
            keys.add(node_suffix)
        unit_keys.append(keys)

    scoped: List[Dict[str, Any]] = []
    used = set()
    for keys in candidate_keys:
        for idx, unit in enumerate(learning_units):
            if idx in used or not isinstance(unit, dict):
                continue
            if unit_keys[idx] & keys:
                scoped.append(unit)
                used.add(idx)
                break
        if len(scoped) >= max_units:
            break
    return (scoped or learning_units)[:max_units]


def _units_to_candidate_nodes(learning_units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for idx, unit in enumerate(learning_units[:48], start=1):
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("id") or f"unit_{idx}").strip()
        title = str(unit.get("title") or "").strip()
        summary = str(unit.get("content_summary") or "").strip()
        if not (unit_id and title):
            continue
        candidates.append(
            {
                "node_id": unit_id,
                "title": title,
                "summary": summary,
                "doc_title": "Syllabus Scope",
                "doc_name": "Syllabus Scope",
                "file_id": "",
                "depth": int(unit.get("depth") or 0),
                "priority": float(max(0.1, 1.0 - (int(unit.get("depth") or 0) * 0.1))),
            }
        )
    return candidates


def _build_scope_chunks(
    scoped_learning_units: List[Dict[str, Any]],
    *,
    chunk_size: int = 3,
) -> List[Dict[str, Any]]:
    if not scoped_learning_units:
        return []
    chunks: List[Dict[str, Any]] = []
    chunk_index = 1
    for i in range(0, len(scoped_learning_units), chunk_size):
        block = scoped_learning_units[i : i + chunk_size]
        unit_ids = [str(unit.get("id") or "").strip() for unit in block if isinstance(unit, dict)]
        unit_ids = [x for x in unit_ids if x]
        if not unit_ids:
            continue
        title = str((block[0] or {}).get("title") or f"scope_{chunk_index}").strip()
        chunks.append(
            {
                "chunk_id": f"scope_{chunk_index}",
                "unit_ids": unit_ids,
                "title": title,
            }
        )
        chunk_index += 1
    return chunks


async def run_card_scope_supervisor_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    if str(state.get("syllabus_status") or "").strip().lower() != "outline_ready":
        return {
            "card_scope_status": "failed",
            "card_scope_report": {"reason": "syllabus_not_ready"},
            "error": "syllabus_not_ready",
        }

    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    query_scope = str(state.get("query_scope") or "").strip().lower()
    if not query_scope:
        try:
            query_scope = await determine_query_scope(
                str(state.get("user_input") or ""),
                has_files=bool(file_ids),
            )
        except Exception as exc:
            return {
                "card_scope_status": "failed",
                "card_scope_report": {"reason": "query_scope_resolution_failed"},
                "error": f"query_scope_resolution_failed:{str(exc)}",
            }
    retrieval_budget = dict(state.get("retrieval_budget") or scope_budget(query_scope))

    learning_units = list(state.get("learning_units") or [])
    candidate_nodes = list(state.get("candidate_nodes") or [])
    if not candidate_nodes and state.get("document_trees"):
        candidate_nodes = select_candidate_nodes(
            document_trees=list(state.get("document_trees") or []),
            user_input=str(state.get("user_input") or ""),
            query_scope=query_scope,
            retrieval_budget=retrieval_budget,
        )
    if not candidate_nodes and learning_units:
        candidate_nodes = _units_to_candidate_nodes(learning_units)

    max_cards = int(retrieval_budget.get("max_cards") or 8)
    scoped_learning_units = _scoped_units_from_candidates(
        learning_units,
        candidate_nodes,
        max_units=max_cards,
    )
    scope_chunks = _build_scope_chunks(scoped_learning_units)

    if not candidate_nodes and not state.get("evidence_items"):
        return {
            "card_scope_status": "need_user_input",
            "card_scope_report": {
                "reason": "no_scope_candidates",
                "candidate_nodes": 0,
                "selected_units": 0,
            },
            "message": "No scoped outline range found for card generation.",
        }

    logger.info(
        "card scope planned",
        session_id=str((runtime.context.session_id if runtime.context else "") or "") or "default",
        query_scope=query_scope,
        candidates=len(candidate_nodes),
        selected_units=len(scoped_learning_units),
    )
    return {
        "card_scope_status": "scope_ready",
        "card_scope_report": {
            "query_scope": query_scope,
            "candidate_nodes": len(candidate_nodes),
            "selected_units": len(scoped_learning_units),
            "scope_chunks": len(scope_chunks),
            "max_cards": max_cards,
        },
        "query_scope": query_scope,
        "retrieval_budget": retrieval_budget,
        "candidate_nodes": candidate_nodes,
        "scoped_learning_units": scoped_learning_units,
        "scope_chunks": scope_chunks,
        "learning_units": scoped_learning_units or learning_units,
    }
