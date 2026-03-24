"""Nodes for card supervisor agent with adversarial QA loop."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from langchain_core.tools import tool

from kardcraft.llm.client import chat_complete
from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.utils.llm_json import safe_parse_llm_json

from .state import CardSupervisorState


def _normalize_card(item: Dict[str, Any], default_model: str = "default") -> Dict[str, Any] | None:
    front = str(item.get("front") or "").strip()
    back = str(item.get("back") or "").strip()
    if not front or not back:
        return None
    model = str(item.get("model") or default_model).strip() or default_model
    tags_raw = item.get("tags") or []
    tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
    return {
        "id": str(item.get("id") or f"card_{uuid.uuid4().hex[:8]}"),
        "model": model,
        "front": front,
        "back": back,
        "tags": tags,
        "source_unit_id": item.get("source_unit_id"),
        "status": str(item.get("status") or "draft"),
    }


async def _generate_cards_with_llm(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    units = state.get("learning_units") or []
    if not isinstance(units, list) or not units:
        return []

    file_ids = state.get("file_ids") or []
    session_id = state.get("session_id")
    user_id = state.get("user_id")
    user_input = str(state.get("user_input") or "").strip()
    source_content = str(state.get("source_content") or "").strip()
    subject_domain = str(state.get("subject_domain") or "general")
    preferred_model = str(
        state.get("selected_template_profile")
        or state.get("template_default_profile")
        or "default"
    )

    evidence_blocks: List[Dict[str, str]] = []
    for unit in units[:8]:
        if not isinstance(unit, dict):
            continue
        title = str(unit.get("title") or "").strip()
        summary = str(unit.get("content_summary") or unit.get("description") or "").strip()
        evidence = ""
        if file_ids and title:
            rag_query = "\n".join([x for x in [user_input, title, summary] if x]).strip()
            if rag_query:
                try:
                    rag = await query_knowledge.ainvoke(
                        {
                            "query": rag_query,
                            "mode": "mix",
                            "top_k": 5,
                            "session_id": session_id,
                            "file_ids": file_ids,
                            "user_id": user_id,
                        }
                    )
                    evidence = str(rag.get("content") or "").strip()[:1600]
                except Exception:
                    evidence = ""
        evidence_blocks.append(
            {
                "unit_id": str(unit.get("id") or ""),
                "title": title,
                "summary": summary,
                "evidence": evidence,
            }
        )

    system_prompt = (
        "You are a multilingual flashcard generator. "
        "Generate accurate cards from learning units and evidence, independent of language. "
        "Return JSON only: {\"cards\": [{\"front\": str, \"back\": str, \"source_unit_id\": str, \"model\": str, \"tags\": [str]}]}."
    )
    user_prompt = {
        "user_input": user_input,
        "subject_domain": subject_domain,
        "preferred_model": preferred_model,
        "max_cards": max(8, min(24, len(evidence_blocks) * 3)),
        "source_content": source_content[:2000],
        "units": evidence_blocks,
    }

    try:
        response = await chat_complete(
            intent="agent",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(user_prompt)},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={"cards": []})
        cards_raw = parsed.get("cards") if isinstance(parsed, dict) else []
        cards: List[Dict[str, Any]] = []
        if isinstance(cards_raw, list):
            for item in cards_raw:
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_card(item, default_model=preferred_model)
                if normalized:
                    cards.append(normalized)
        return cards
    except Exception:
        return []


async def _refine_cards_with_llm(cards: List[Dict[str, Any]], state: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not cards:
        return []

    system_prompt = (
        "You are a multilingual flashcard editor. "
        "Improve clarity, reduce ambiguity, and split overloaded cards when needed. "
        "Return JSON only: {\"cards\": [{\"id\": str, \"front\": str, \"back\": str, \"model\": str, \"tags\": [str], \"source_unit_id\": str}]}."
    )
    user_prompt = {
        "subject_domain": state.get("subject_domain") or "general",
        "difficulty": state.get("difficulty_level") or "medium",
        "cards": cards[:40],
    }

    try:
        response = await chat_complete(
            intent="reasoning",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(user_prompt)},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={"cards": cards})
        cards_raw = parsed.get("cards") if isinstance(parsed, dict) else cards
        refined: List[Dict[str, Any]] = []
        if isinstance(cards_raw, list):
            for item in cards_raw:
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_card(item, default_model=str(item.get("model") or "default"))
                if normalized:
                    normalized["status"] = "refined"
                    refined.append(normalized)
        return refined or cards
    except Exception:
        return cards


async def _quality_gate_with_llm(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not cards:
        return {
            "approved_cards": [],
            "quality_report": {
                "checked": 0,
                "approved": 0,
                "failed": 0,
                "pass_rate": 0.0,
                "critical_failures": 0,
                "failed_cards": [],
            },
        }

    system_prompt = (
        "You are a strict multilingual flashcard QA reviewer. "
        "Evaluate each card for correctness, clarity, and learnability. "
        "Return JSON only: "
        "{\"approved_card_ids\": [str], \"failed\": [{\"card_id\": str, \"violations\": [str], \"critical\": bool, \"score\": number}]}."
    )
    user_prompt = {"cards": cards[:60]}

    try:
        response = await chat_complete(
            intent="fast",
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(user_prompt)},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={})
    except Exception:
        parsed = {}

    id_to_card = {str(card.get("id")): card for card in cards if isinstance(card, dict)}
    approved_ids = parsed.get("approved_card_ids") if isinstance(parsed, dict) else []
    failed_raw = parsed.get("failed") if isinstance(parsed, dict) else []

    approved_cards: List[Dict[str, Any]] = []
    failed_cards: List[Dict[str, Any]] = []

    if isinstance(approved_ids, list):
        for cid in approved_ids:
            card = id_to_card.get(str(cid))
            if card:
                approved_cards.append(card)

    approved_set = {str(card.get("id")) for card in approved_cards}
    if isinstance(failed_raw, list):
        for item in failed_raw:
            if not isinstance(item, dict):
                continue
            card = id_to_card.get(str(item.get("card_id")))
            if not card:
                continue
            failed_cards.append(
                {
                    "card": card,
                    "violations": item.get("violations") or ["model_rejected"],
                    "critical": bool(item.get("critical")),
                    "score": float(item.get("score", 0.0) or 0.0),
                }
            )

    if not approved_cards and not failed_cards:
        # Runtime fallback: keep structurally valid cards available for review.
        approved_cards = [c for c in cards if str(c.get("front") or "").strip() and str(c.get("back") or "").strip()]
        approved_set = {str(card.get("id")) for card in approved_cards}

    for card in cards:
        cid = str(card.get("id"))
        if cid in approved_set:
            continue
        if any(str((f.get("card") or {}).get("id")) == cid for f in failed_cards):
            continue
        failed_cards.append(
            {
                "card": card,
                "violations": ["not_in_approved_set"],
                "critical": False,
                "score": 0.0,
            }
        )

    checked = len(cards)
    approved = len(approved_cards)
    failed = len(failed_cards)
    critical = sum(1 for item in failed_cards if item.get("critical"))
    pass_rate = (approved / checked) if checked else 0.0

    return {
        "approved_cards": approved_cards,
        "quality_report": {
            "checked": checked,
            "approved": approved,
            "failed": failed,
            "pass_rate": pass_rate,
            "critical_failures": critical,
            "failed_cards": failed_cards,
        },
    }


@tool
async def run_card_iteration(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run one generate->refine->quality iteration."""
    work_state = dict(payload)

    raw_cards = work_state.get("raw_cards") or []
    if not raw_cards:
        raw_cards = await _generate_cards_with_llm(work_state)

    refined_cards = await _refine_cards_with_llm(raw_cards, work_state)
    quality = await _quality_gate_with_llm(refined_cards)

    report = quality.get("quality_report") or {}
    return {
        "approved_cards": quality.get("approved_cards") or [],
        "quality_report": report,
        "raw_cards": raw_cards,
        "refined_cards": refined_cards,
    }


@tool
async def reviewer_readonly(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read-only reviewer: extract issue list from quality report without editing cards."""
    findings: List[Dict[str, Any]] = []
    for item in (report.get("failed_cards") or []):
        card = item.get("card") if isinstance(item, dict) else None
        if not isinstance(card, dict):
            continue
        findings.append(
            {
                "card_id": card.get("id"),
                "front": card.get("front"),
                "violations": item.get("violations") or [],
                "critical": bool(item.get("critical")),
            }
        )
    return findings


@tool
async def fixer_apply_repair(
    failed_cards: List[Dict[str, Any]],
    session_id: str | None,
    user_id: str | None,
    file_ids: List[str],
) -> List[Dict[str, Any]]:
    """Fixer: backfill failed cards with ragix evidence and return repaired candidates."""
    updated: List[Dict[str, Any]] = []
    for item in failed_cards[:10]:
        card = item.get("card") if isinstance(item, dict) else None
        if not isinstance(card, dict):
            continue
        front = str(card.get("front") or "").strip()
        if not front:
            continue
        try:
            rag = await query_knowledge.ainvoke(
                {
                    "query": front,
                    "mode": "mix",
                    "top_k": 5,
                    "session_id": session_id,
                    "file_ids": file_ids,
                    "user_id": user_id,
                }
            )
            evidence = str(rag.get("content") or "").strip()
            if evidence:
                card["back"] = f"{str(card.get('back') or '').strip()}\n\nEvidence:\n{evidence[:1200]}".strip()
        except Exception:
            pass
        card["status"] = "repaired"
        updated.append(card)
    return updated


@tool
async def judge_score(report: Dict[str, Any]) -> Dict[str, Any]:
    """Judge: model-based scoring (0-100), language-agnostic."""
    system_prompt = (
        "You are a strict QA judge for flashcards. "
        "Score current card set quality from 0 to 100 based on report quality, defects and critical failures. "
        "Return JSON only: "
        "{\"score\": int, \"reason\": string, \"confidence\": number}."
    )
    report_text = json.dumps(report or {}, ensure_ascii=False, default=str)
    if len(report_text) > 4000:
        report_text = report_text[:4000]
    user_prompt = f"quality_report:\n{report_text}"
    try:
        response = await chat_complete(
            intent="fast",
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(
            content,
            default={"score": 0, "reason": "model_parse_fallback", "confidence": 0.0},
        )
        if not isinstance(parsed, dict):
            parsed = {}
        score = int(parsed.get("score", 0) or 0)
        score = max(0, min(100, score))
        return {
            "score": score,
            "reason": str(parsed.get("reason") or "model_decision"),
            "confidence": float(parsed.get("confidence", 0.0) or 0.0),
        }
    except Exception as exc:
        detail = str(exc).replace("\n", " ")[:160]
        return {
            "score": 0,
            "reason": f"model_unavailable:{type(exc).__name__}:{detail}",
            "confidence": 0.0,
        }


async def run_card_supervisor(state: CardSupervisorState) -> Dict[str, Any]:
    threshold = int(state.get("judge_score_threshold") or 90)
    max_iterations = int(state.get("max_qa_iterations") or 5)

    work_state: Dict[str, Any] = {
        "user_id": state.get("user_id"),
        "session_id": state.get("session_id"),
        "user_input": state.get("user_input", ""),
        "topic": state.get("user_input", ""),
        "source_content": state.get("source_content", ""),
        "subject_domain": state.get("subject_domain", "general"),
        "learning_units": state.get("learning_units") or [],
        "template_profiles": state.get("template_profiles") or [],
        "template_default_profile": state.get("template_default_profile"),
        "selected_template_profile": state.get("selected_template_profile"),
        "file_ids": state.get("file_ids") or [],
    }

    if not work_state["learning_units"]:
        return {
            "status": "failed",
            "reason": "missing_learning_units",
            "approved_cards": [],
            "quality_report": {},
            "qa_loop_report": {
                "max_iterations": max_iterations,
                "iterations_used": 0,
                "best_score": 0,
                "final_score": 0,
                "exit_reason": "missing_learning_units",
                "review_findings": [],
                "judge_scores": [],
                "fix_actions": [],
            },
        }

    last_report: Dict[str, Any] = {}
    approved_cards: List[Dict[str, Any]] = []
    best_score = 0
    final_score = 0
    review_findings_log: List[Dict[str, Any]] = []
    judge_scores_log: List[Dict[str, Any]] = []
    fix_actions_log: List[Dict[str, Any]] = []

    for iteration in range(1, max_iterations + 1):
        iteration_result = await run_card_iteration.ainvoke({"payload": work_state})
        report = iteration_result.get("quality_report") or {}
        approved_cards = iteration_result.get("approved_cards") or []
        last_report = report

        findings = await reviewer_readonly.ainvoke({"report": report})
        review_findings_log.append({"iteration": iteration, "findings": findings})

        failed_cards = report.get("failed_cards") or []
        repaired_cards = await fixer_apply_repair.ainvoke(
            {
                "failed_cards": failed_cards,
                "session_id": state.get("session_id"),
                "user_id": state.get("user_id"),
                "file_ids": state.get("file_ids") or [],
            }
        )
        fix_actions_log.append(
            {
                "iteration": iteration,
                "failed_cards": len(failed_cards),
                "repaired_cards": len(repaired_cards),
            }
        )
        if repaired_cards:
            work_state["raw_cards"] = repaired_cards

        judged = await judge_score.ainvoke({"report": report})
        score = int(judged.get("score", 0) or 0)
        final_score = score
        best_score = max(best_score, score)
        judge_scores_log.append({"iteration": iteration, **judged})

        if score > threshold:
            return {
                "status": "quality_pass",
                "reason": "judge_score_passed",
                "approved_cards": approved_cards,
                "quality_report": report,
                "qa_loop_report": {
                    "max_iterations": max_iterations,
                    "iterations_used": iteration,
                    "best_score": best_score,
                    "final_score": final_score,
                    "exit_reason": "score_passed",
                    "review_findings": review_findings_log,
                    "judge_scores": judge_scores_log,
                    "fix_actions": fix_actions_log,
                },
            }

    usable = bool(approved_cards)
    return {
        "status": "need_user_review" if usable else "failed",
        "reason": "max_iterations_reached",
        "approved_cards": approved_cards,
        "quality_report": last_report,
        "qa_loop_report": {
            "max_iterations": max_iterations,
            "iterations_used": max_iterations,
            "best_score": best_score,
            "final_score": final_score,
            "exit_reason": "max_iterations_reached",
            "review_findings": review_findings_log,
            "judge_scores": judge_scores_log,
            "fix_actions": fix_actions_log,
        },
    }
