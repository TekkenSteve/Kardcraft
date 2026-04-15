"""Nodes for card aggregation agent."""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.utils.logger import logger
from kardcraft.workflow.graphs.main_graph.state import Context
from kardcraft.workflow.graphs.main_graph.subgraph.card_generation_agent import (
    card_generation_agent,
)

from .state import State


def _dedupe_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        front = str(card.get("front") or "").strip().lower()
        back = str(card.get("back") or "").strip().lower()
        key = f"{front}|||{back}"
        if not front or not back or key in seen:
            continue
        seen.add(key)
        deduped.append(card)
    return deduped


async def run_card_aggregation_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    scope_chunks = list(state.get("scope_chunks") or [])
    scoped_learning_units = list(state.get("scoped_learning_units") or state.get("learning_units") or [])
    if not scope_chunks:
        logger.warning(
            "card aggregation skipped: missing scope chunks",
            scoped_learning_units_count=len(scoped_learning_units),
            evidence_items_count=len(list(state.get("evidence_items") or [])),
        )
        return {
            "status": "failed",
            "reason": "missing_scope_chunks",
            "approved_cards": [],
            "quality_report": {},
            "qa_loop_report": {
                "scope_chunks": 0,
                "chunks_succeeded": 0,
                "chunks_failed": 0,
                "stop_reason": "missing_scope_chunks",
                "chunk_reports": [],
            },
        }

    all_cards: List[Dict[str, Any]] = []
    chunk_reports: List[Dict[str, Any]] = []
    chunks_succeeded = 0
    chunks_failed = 0

    for chunk in scope_chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        unit_ids = [str(x).strip() for x in (chunk.get("unit_ids") or []) if str(x).strip()]
        result = await card_generation_agent.ainvoke(
            {
                "chunk_id": chunk_id,
                "unit_ids": unit_ids,
                "template_id": state.get("template_id"),
                "template_version": state.get("template_version"),
                "user_input": state.get("user_input") or "",
                "message_knowledge": state.get("message_knowledge") or "",
                "subject_domain": state.get("subject_domain") or "general",
                "query_scope": state.get("query_scope") or "focused",
                "learning_units": scoped_learning_units,
                "evidence_items": state.get("evidence_items") or [],
                "document_trees": state.get("document_trees") or [],
                "template_profiles": state.get("template_profiles") or [],
                "template_default_profile": state.get("template_default_profile"),
                "selected_template_profile": state.get("selected_template_profile"),
                "profile_prompt_hint": state.get("profile_prompt_hint") or {},
                "file_ids": state.get("file_ids") or [],
            },
            context=runtime.context,
        )
        fatal_error = str(result.get("fatal_error") or "").strip()
        cards = result.get("approved_cards") or []
        quality_report = result.get("quality_report") or {}
        logger.debug(
            "card aggregation chunk result",
            chunk_id=chunk_id,
            unit_ids=unit_ids,
            fatal_error=fatal_error or None,
            approved_cards_count=len(cards),
            quality_checked=int(quality_report.get("checked") or 0),
            quality_failed=int(quality_report.get("failed") or 0),
            quality_pass_rate=float(quality_report.get("pass_rate") or 0.0),
        )
        if fatal_error:
            chunks_failed += 1
            chunk_reports.append(
                {
                    "chunk_id": chunk_id,
                    "unit_ids": unit_ids,
                    "status": "failed",
                    "reason": fatal_error,
                    "approved": 0,
                }
            )
            continue

        chunks_succeeded += 1
        all_cards.extend([card for card in cards if isinstance(card, dict)])
        chunk_reports.append(
            {
                "chunk_id": chunk_id,
                "unit_ids": unit_ids,
                "status": "success",
                "approved": len(cards),
                "failed": int(quality_report.get("failed") or 0),
                "pass_rate": float(quality_report.get("pass_rate") or 0.0),
            }
        )

    merged_cards = _dedupe_cards(all_cards)
    status = "quality_pass" if merged_cards else "failed"
    reason = "merged_scope_cards" if merged_cards else "no_cards_generated"
    logger.info(
        "card aggregation final result",
        scope_chunks=len(scope_chunks),
        chunks_succeeded=chunks_succeeded,
        chunks_failed=chunks_failed,
        raw_card_count=len(all_cards),
        deduped_card_count=len(merged_cards),
        status=status,
        reason=reason,
    )

    return {
        "status": status,
        "reason": reason,
        "approved_cards": merged_cards,
        "quality_report": {
            "checked": len(merged_cards),
            "approved": len(merged_cards),
            "failed": 0,
            "pass_rate": 1.0 if merged_cards else 0.0,
        },
        "qa_loop_report": {
            "scope_chunks": len(scope_chunks),
            "chunks_succeeded": chunks_succeeded,
            "chunks_failed": chunks_failed,
            "stop_reason": "completed" if merged_cards else "no_cards_generated",
            "chunk_reports": chunk_reports,
        },
    }
