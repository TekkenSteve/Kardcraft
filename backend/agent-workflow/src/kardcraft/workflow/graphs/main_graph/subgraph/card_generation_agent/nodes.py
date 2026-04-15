"""Nodes for card generation agent."""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.workflow.graphs.main_graph.state import Context
from kardcraft.workflow.graphs.main_graph.subgraph.output_agent import output_agent
from kardcraft.workflow.graphs.main_graph.subgraph.render_validation_react_agent import (
    render_validation_react_agent,
)
from kardcraft.utils.logger import logger
from .utils import (
    run_answer_generation,
    run_card_assembly,
    run_card_quality_pipeline,
    run_question_generation,
)

from .state import State


def _split_unit_id(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    if ":" not in text:
        return "", text
    file_id, node_id = text.rsplit(":", 1)
    return file_id.strip(), node_id.strip()


def _candidate_unit_keys(node: Dict[str, Any]) -> set[str]:
    node_id = str(node.get("node_id") or "").strip()
    file_id = str(node.get("file_id") or "").strip()
    keys: set[str] = set()
    if node_id:
        keys.add(node_id)
    if node_id and file_id:
        keys.add(f"{file_id}:{node_id}")
    return keys


def _filter_learning_units_by_scope(
    learning_units: List[Dict[str, Any]],
    unit_ids: List[str],
) -> List[Dict[str, Any]]:
    if not unit_ids:
        return list(learning_units or [])
    wanted = {str(x).strip() for x in unit_ids if str(x).strip()}
    return [
        unit
        for unit in (learning_units or [])
        if isinstance(unit, dict) and str(unit.get("id") or "").strip() in wanted
    ]


def _filter_evidence_items_by_scope(
    evidence_items: List[Dict[str, Any]],
    unit_ids: List[str],
) -> List[Dict[str, Any]]:
    if not unit_ids:
        return list(evidence_items or [])
    wanted_full = {str(x).strip() for x in unit_ids if str(x).strip()}
    wanted_node_ids = {
        node_id
        for _, node_id in (_split_unit_id(x) for x in unit_ids)
        if node_id
    }
    filtered: List[Dict[str, Any]] = []
    for item in evidence_items or []:
        if not isinstance(item, dict):
            continue
        node = item.get("node") if isinstance(item.get("node"), dict) else {}
        keys = _candidate_unit_keys(node)
        if keys & wanted_full:
            filtered.append(item)
            continue
        node_id = str(node.get("node_id") or "").strip()
        if node_id and node_id in wanted_node_ids:
            filtered.append(item)
    return filtered


async def run_card_generation_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    unit_ids = [str(x).strip() for x in (state.get("unit_ids") or []) if str(x).strip()]
    scoped_units = _filter_learning_units_by_scope(
        list(state.get("learning_units") or []),
        unit_ids,
    )
    scoped_evidence = _filter_evidence_items_by_scope(
        list(state.get("evidence_items") or []),
        unit_ids,
    )
    payload: Dict[str, Any] = {
        "template_id": state.get("template_id"),
        "template_version": state.get("template_version"),
        "user_input": state.get("user_input") or "",
        "message_knowledge": state.get("message_knowledge") or "",
        "subject_domain": state.get("subject_domain") or "general",
        "query_scope": state.get("query_scope") or "focused",
        "learning_units": scoped_units,
        "evidence_items": scoped_evidence,
        "document_trees": state.get("document_trees") or [],
        "template_profiles": state.get("template_profiles") or [],
        "template_default_profile": state.get("template_default_profile"),
        "selected_template_profile": state.get("selected_template_profile"),
        "profile_prompt_hint": state.get("profile_prompt_hint") or {},
        "file_ids": state.get("file_ids") or [],
    }

    question_stage = await run_question_generation.ainvoke({"payload": payload})
    if str(question_stage.get("fatal_error") or "").strip() == "selector_unavailable":
        return {
            "fatal_error": "selector_unavailable",
            "approved_cards": [],
            "quality_report": {},
            "raw_cards": [],
            "refined_cards": [],
        }

    question_drafts = question_stage.get("question_drafts") or []
    logger.debug(
        "card generation question stage",
        chunk_id=str(state.get("chunk_id") or ""),
        unit_ids=unit_ids,
        scoped_units_count=len(scoped_units),
        scoped_evidence_count=len(scoped_evidence),
        question_drafts_count=len(question_drafts),
    )

    answer_stage = await run_answer_generation.ainvoke(
        {
            "question_drafts": question_drafts,
            "payload": payload,
        }
    )
    assembled_stage = await run_card_assembly.ainvoke(
        {
            "question_drafts": question_drafts,
            "answer_drafts": answer_stage.get("answer_drafts") or [],
            "payload": payload,
        }
    )
    quality_stage = await run_card_quality_pipeline.ainvoke(
        {
            "cards": assembled_stage.get("assembled_cards") or [],
            "payload": payload,
        }
    )
    if str(quality_stage.get("fatal_error") or "").strip() == "selector_unavailable":
        return {
            "fatal_error": "selector_unavailable",
            "approved_cards": [],
            "quality_report": {},
            "raw_cards": [],
            "refined_cards": [],
        }

    approved_cards = quality_stage.get("approved_cards") or []
    quality_report = quality_stage.get("quality_report") or {}
    output_stage = await output_agent.ainvoke(
        {
            "cards": approved_cards,
            "payload": payload,
        },
        context=runtime.context,
    )
    render_validation_stage = await render_validation_react_agent.ainvoke(
        {
            "cards": output_stage.get("output_cards") or [],
            "payload": payload,
        },
        context=runtime.context,
    )
    validated_cards = render_validation_stage.get("validated_cards") or []
    output_cards = output_stage.get("output_cards") or []
    failed_cards = quality_report.get("failed_cards") if isinstance(quality_report, dict) else []
    failed_preview: List[Dict[str, Any]] = []
    if isinstance(failed_cards, list):
        for item in failed_cards[:3]:
            if not isinstance(item, dict):
                continue
            card = item.get("card") if isinstance(item.get("card"), dict) else {}
            failed_preview.append(
                {
                    "id": str(card.get("id") or ""),
                    "front": str(card.get("front") or "")[:80],
                    "reason_codes": item.get("reason_codes") if isinstance(item.get("reason_codes"), list) else [],
                    "score": float(item.get("score") or 0.0),
                    "critical": bool(item.get("critical")),
                }
            )
    logger.debug(
        "card generation quality stage",
        chunk_id=str(state.get("chunk_id") or ""),
        answer_drafts_count=len(answer_stage.get("answer_drafts") or []),
        output_cards_count=len(output_cards),
        validated_cards_count=len(validated_cards),
        approved_cards_count=len(approved_cards),
        quality_checked=int(quality_report.get("checked") or 0),
        quality_failed=int(quality_report.get("failed") or 0),
        policy_profile_id=str(quality_report.get("policy_profile_id") or ""),
        reason_code_counts=quality_report.get("reason_code_counts") if isinstance(quality_report, dict) else {},
        failed_preview=failed_preview,
    )
    chunk_id = str(state.get("chunk_id") or "").strip()
    if chunk_id:
        for card in validated_cards:
            if isinstance(card, dict):
                card["scope_chunk_id"] = chunk_id

    return {
        "approved_cards": validated_cards,
        "quality_report": quality_stage.get("quality_report") or {},
        "raw_cards": validated_cards,
        "refined_cards": quality_stage.get("refined_cards") or [],
        "render_validation_report": render_validation_stage.get("render_validation_report") or {},
    }
