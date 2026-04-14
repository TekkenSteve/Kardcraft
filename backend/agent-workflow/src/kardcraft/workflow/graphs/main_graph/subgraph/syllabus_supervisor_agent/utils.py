"""Utility helpers for syllabus supervisor agent nodes."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage

from kardcraft.agent_skills import build_skill_guidance_text
from kardcraft.llm import configure_dspy_lm
from kardcraft.llm.client import chat_complete
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger
from kardcraft.workflow.graphs.deep_research_graph import deep_research_graph
from langchain_core.runnables import RunnableConfig


from .prompt import OutlinePlanningPrompt


def _syllabus_failed(
    *,
    reason: str,
    error: str,
    outline_sources: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "syllabus_status": "failed",
        "learning_units": [],
        "syllabus_outline": [],
        "outline_sources": outline_sources or [],
        "pending_questions": [],
        "clarification_responses": {},
        "status": "failed",
        "clarification_state": "exhausted",
        "termination_reason": reason,
        "error": error,
    }


async def _principles_prompt_text(task_context: str) -> str:
    text, _selection = await build_skill_guidance_text(
        task_context=task_context,
        header="Selection principles:",
        name_prefix="principle-",
        max_selected=6,
    )
    return text


def _outline_sources_from_candidate_nodes(candidate_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for idx, node in enumerate(candidate_nodes[:48], start=1):
        if not isinstance(node, dict):
            continue
        title = str(node.get("title") or "").strip()
        summary = str(node.get("summary") or "").strip()
        if not (title or summary):
            continue
        file_id = str(node.get("file_id") or "").strip() or "unknown_file"
        node_id = str(node.get("node_id") or f"node_{idx}").strip()
        source_id = f"{file_id}:{node_id}"
        sources.append(
            {
                "id": source_id,
                "file_id": file_id,
                "file_name": str(node.get("doc_name") or "").strip(),
                "node_id": node_id,
                "title": title or f"Node {idx}",
                "summary": summary,
                "doc_title": str(node.get("doc_title") or node.get("doc_name") or "").strip(),
                "depth": int(node.get("depth") or 0),
                "priority": float(node.get("priority") or 0.0),
                "source_type": "pageindex",
            }
        )
    return sources


def _source_token_set(source: Dict[str, Any]) -> set[str]:
    text = " ".join(
        [
            str(source.get("title") or ""),
            str(source.get("summary") or ""),
            str(source.get("doc_title") or ""),
            str(source.get("file_name") or ""),
            str(source.get("file_id") or ""),
        ]
    ).lower()
    return {tok for tok in re.findall(r"[\w\u4e00-\u9fff]+", text) if len(tok) > 1}


def _node_token_set(node: Dict[str, Any]) -> set[str]:
    text = " ".join(
        [
            str(node.get("title") or ""),
            str(node.get("summary") or ""),
        ]
    ).lower()
    return {tok for tok in re.findall(r"[\w\u4e00-\u9fff]+", text) if len(tok) > 1}


def _best_source_id_for_outline_node(node: Dict[str, Any], sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return ""
    node_tokens = _node_token_set(node)
    best_id = str(sources[0].get("id") or "").strip()
    best_score = -1
    for source in sources:
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        source_tokens = _source_token_set(source)
        overlap = len(node_tokens & source_tokens) if node_tokens else 0
        score = overlap
        if score > best_score:
            best_score = score
            best_id = source_id
    return best_id


def _ensure_outline_source_links(
    outline_nodes: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not outline_nodes:
        return []
    valid_source_ids = {str(src.get("id") or "").strip() for src in sources if str(src.get("id") or "").strip()}
    node_id_aliases: Dict[str, List[str]] = defaultdict(list)
    for src in sources:
        source_id = str(src.get("id") or "").strip()
        node_id = str(src.get("node_id") or "").strip()
        if source_id and node_id:
            node_id_aliases[node_id].append(source_id)

    def _walk(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for node in items:
            if not isinstance(node, dict):
                continue
            raw_ids = [str(x).strip() for x in (node.get("source_ids") or []) if str(x).strip()]
            resolved_ids: List[str] = []
            for source_id in raw_ids:
                if source_id in valid_source_ids:
                    resolved_ids.append(source_id)
                    continue
                aliased = node_id_aliases.get(source_id) or []
                if len(aliased) == 1:
                    resolved_ids.append(aliased[0])
            if not resolved_ids:
                best_source_id = _best_source_id_for_outline_node(node, sources)
                if best_source_id:
                    resolved_ids = [best_source_id]
            children = _walk(node.get("children") or [])
            normalized.append(
                {
                    "id": str(node.get("id") or "").strip(),
                    "title": str(node.get("title") or "").strip(),
                    "summary": str(node.get("summary") or "").strip(),
                    "children": children,
                    "source_ids": resolved_ids,
                }
            )
        return normalized

    return _walk(outline_nodes)


def _normalize_outline_nodes(raw_nodes: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_nodes, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_nodes, start=1):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or f"outline_{idx}").strip()
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not title:
            continue
        children = _normalize_outline_nodes(item.get("children") or [])
        normalized.append(
            {
                "id": node_id,
                "title": title,
                "summary": summary,
                "children": children,
                "source_ids": [str(x).strip() for x in (item.get("source_ids") or []) if str(x).strip()],
            }
        )
    return normalized


def _flatten_outline_nodes(nodes: List[Dict[str, Any]], max_units: int = 24) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []

    def _walk(items: List[Dict[str, Any]], depth: int = 0) -> None:
        for node in items:
            if len(flat) >= max_units:
                return
            title = str(node.get("title") or "").strip()
            summary = str(node.get("summary") or "").strip()
            if not title:
                continue
            flat.append(
                {
                    "id": str(node.get("id") or f"unit_{len(flat)+1}"),
                    "title": title,
                    "content_summary": summary,
                    "key_concepts": [],
                    "difficulty": "intermediate",
                    "estimated_time": None,
                    "prerequisites": [],
                    "status": "draft",
                    "depth": depth,
                }
            )
            _walk(node.get("children") or [], depth + 1)

    _walk(nodes, 0)
    return flat


def _augment_learning_units_with_sources(
    learning_units: List[Dict[str, Any]],
    outline_sources: List[Dict[str, Any]],
    *,
    max_units: int = 48,
) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = [dict(item) for item in (learning_units or []) if isinstance(item, dict)]
    seen_ids = {str(item.get("id") or "").strip() for item in units if str(item.get("id") or "").strip()}
    for source in (outline_sources or []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id or source_id in seen_ids:
            continue
        units.append(
            {
                "id": source_id,
                "title": str(source.get("title") or "Untitled").strip() or "Untitled",
                "content_summary": str(source.get("summary") or "").strip(),
                "key_concepts": [],
                "difficulty": "intermediate",
                "estimated_time": None,
                "prerequisites": [],
                "status": "draft",
                "depth": int(source.get("depth") or 0),
            }
        )
        seen_ids.add(source_id)
        if len(units) >= max_units:
            break
    return units[:max_units]


def _candidate_nodes_from_outline(
    outline_nodes: List[Dict[str, Any]],
    *,
    doc_title: str,
    file_id: str,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    def _walk(items: List[Dict[str, Any]], depth: int = 0) -> None:
        for idx, node in enumerate(items, start=1):
            title = str(node.get("title") or "").strip()
            summary = str(node.get("summary") or "").strip()
            if not title:
                continue
            node_id = str(node.get("id") or f"outline_{depth}_{idx}").strip()
            candidates.append(
                {
                    "node_id": node_id,
                    "title": title,
                    "summary": summary,
                    "doc_title": doc_title,
                    "doc_name": doc_title,
                    "file_id": file_id,
                    "depth": depth,
                    "priority": max(0.1, 1.0 - (depth * 0.15)),
                }
            )
            _walk(node.get("children") or [], depth + 1)

    _walk(outline_nodes, 0)
    return candidates[:48]


def _resolve_doc_title(
    *,
    outline_sources: List[Dict[str, Any]],
    document_trees: List[Dict[str, Any]],
    file_id: str,
) -> str:
    for src in outline_sources:
        title = str(src.get("doc_title") or src.get("title") or "").strip()
        if title and title != file_id:
            return title
    for tree in document_trees:
        title = str(
            tree.get("doc_title")
            or tree.get("doc_name")
            or tree.get("title")
            or ""
        ).strip()
        if title and title != file_id:
            return title
    return file_id


async def _generate_outline_with_llm(
    *,
    user_input: str,
    language: str,
    driven_mode: str,
    source_kind: str,
    sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    principles_text = await _principles_prompt_text(
        json.dumps(
            {
                "stage": "outline_planning",
                "task": user_input,
                "driven_mode": driven_mode,
                "source_kind": source_kind,
            },
            ensure_ascii=False,
        )
    )
    payload = {
        "task": user_input,
        "driven_mode": driven_mode,
        "source_kind": source_kind,
        "sources": sources[:48],
        "selection_rule": "progressive_disclosure_and_relevance",
    }
    planner = OutlinePlanningPrompt(lang=language or "en")
    try:
        lm = configure_dspy_lm()
        if lm is not None:
            result = planner(
                task=user_input,
                driven_mode=driven_mode,
                source_kind=source_kind,
                selection_rule="progressive_disclosure_and_relevance",
                principles_text=principles_text,
                sources_json=json.dumps(sources[:48], ensure_ascii=False),
            )
            outline_raw = str(getattr(result, "outline_json", "") or "")
        else:
            raise RuntimeError("DSPy LM unavailable")
        parsed = safe_parse_llm_json(outline_raw, default={"outline": []})
        outline_nodes = _normalize_outline_nodes(parsed.get("outline") if isinstance(parsed, dict) else [])
        return outline_nodes
    except Exception as exc:
        logger.warning("dspy outline planning failed, fallback to chat_complete", error=str(exc))
    try:
        resp = await chat_complete(
            intent="reasoning",
            temperature=0.1,
            messages=[
                {"role": "system", "content": planner.resolved_prompt.text},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        content = ""
        if resp and getattr(resp, "choices", None):
            content = getattr(resp.choices[0].message, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={"outline": []})
        return _normalize_outline_nodes(parsed.get("outline") if isinstance(parsed, dict) else [])
    except Exception as exc:
        logger.warning("outline generation failed", error=str(exc))
        return []


async def _deep_research_summary(user_input: str) -> str:
    import uuid

    try:
        config = RunnableConfig(configurable={"thread_id": f"outline_deep_research_{uuid.uuid4().hex[:8]}"})
        result = await deep_research_graph.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )
        messages = result.get("messages") if isinstance(result, dict) else None
        if isinstance(messages, list) and messages:
            last = messages[-1]
            return str(getattr(last, "content", last) or "").strip()
    except Exception as exc:
        logger.warning("deep research outline fetch failed", error=str(exc))
    return ""
