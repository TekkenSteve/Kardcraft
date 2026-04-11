"""Nodes for card supervisor agent with adversarial QA loop."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from langchain_core.tools import tool
from langgraph.runtime import Runtime

from kardcraft.agent_skills import (
    SkillSelectorUnavailableError,
    build_skill_guidance_text,
)
from kardcraft.llm.client import chat_complete
from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger
from kardcraft.workflow.graphs.main_graph.state import Context

from .quality_metrics import reason_code_coverage_rate
from .state import CardSupervisorState

FILE_TREE_SCOPES = {"title_only", "focused", "full_doc"}
HARD_REASON_CODES = {
    "hard_front_too_long",
    "hard_back_too_long",
    "hard_non_atomic_back",
    "hard_title_scope_drift",
}
SOFT_REASON_CODES = {
    "soft_low_clarity",
    "soft_low_learnability",
    "soft_overloaded",
    "soft_uncertain_grounding",
    "soft_model_reject",
    "soft_judge_missing_decision",
}


@dataclass(frozen=True, slots=True)
class PolicyProfile:
    profile_id: str
    max_front_len: int
    max_back_len: int
    atomic_back_char_limit: int
    require_title_alignment: bool
    soft_min_score: float


def _resolve_policy_profile(subject_domain: str, query_scope: str) -> PolicyProfile:
    domain = str(subject_domain or "").strip().lower()
    scope = str(query_scope or "").strip().lower()
    if scope == "title_only":
        return PolicyProfile(
            profile_id="title_focus_strict",
            max_front_len=140,
            max_back_len=360,
            atomic_back_char_limit=220,
            require_title_alignment=True,
            soft_min_score=0.65,
        )
    if domain in {"law", "legal", "medicine", "medical"}:
        return PolicyProfile(
            profile_id="high_precision_domain",
            max_front_len=160,
            max_back_len=420,
            atomic_back_char_limit=260,
            require_title_alignment=False,
            soft_min_score=0.72,
        )
    return PolicyProfile(
        profile_id="general_progressive_disclosure",
        max_front_len=180,
        max_back_len=500,
        atomic_back_char_limit=280,
        require_title_alignment=False,
        soft_min_score=0.60,
    )


async def _format_principles_for_prompt(task_context: str) -> str:
    text, selection = await build_skill_guidance_text(
        task_context=task_context,
        header="Follow these card design principles:",
        name_prefix="principle-",
        max_selected=6,
    )
    logger.info(
        "card principles selected",
        selected=selection.get("selected_skill_names", []),
        reason_codes=selection.get("reason_codes", []),
        confidence=selection.get("confidence", 0.0),
    )
    return text


def _collect_document_titles(payload: Dict[str, Any]) -> List[str]:
    titles: List[str] = []
    for tree in payload.get("document_trees") or []:
        if not isinstance(tree, dict):
            continue
        title = str(tree.get("title") or tree.get("doc_name") or "").strip()
        if title:
            titles.append(title)
    deduped: List[str] = []
    seen = set()
    for title in titles:
        folded = title.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        deduped.append(title)
    return deduped


def _card_budget_from_scope(scope: str, default_count: int) -> int:
    if scope == "title_only":
        return 2
    if scope == "focused":
        return min(8, max(2, default_count))
    return min(16, max(4, default_count))


def _contains_any_title(text: str, titles: List[str]) -> bool:
    normalized = str(text or "").strip().casefold()
    for title in titles:
        raw = str(title or "").strip()
        if not raw:
            continue
        if raw.casefold() in normalized:
            return True
    return False


def _intent_rule_violations(
    card: Dict[str, Any],
    *,
    query_scope: str,
    doc_titles: List[str],
    profile: PolicyProfile,
) -> List[str]:
    violations: List[str] = []
    front = str(card.get("front") or "").strip()
    back = str(card.get("back") or "").strip()
    if len(front) > profile.max_front_len:
        violations.append("hard_front_too_long")
    if len(back) > profile.max_back_len:
        violations.append("hard_back_too_long")
    if "\n\n" in back and len(back) > profile.atomic_back_char_limit:
        violations.append("hard_non_atomic_back")
    if profile.require_title_alignment and query_scope == "title_only" and doc_titles:
        if not (_contains_any_title(front, doc_titles) or _contains_any_title(back, doc_titles)):
            violations.append("hard_title_scope_drift")
    return violations


def _is_file_tree_input(payload: Dict[str, Any]) -> bool:
    query_scope = str(payload.get("query_scope") or "").strip().lower()
    file_ids = [str(x).strip() for x in (payload.get("file_ids") or []) if str(x).strip()]
    return bool(file_ids) and query_scope in FILE_TREE_SCOPES


def _normalize_card(item: Dict[str, Any], default_model: str = "default") -> Dict[str, Any] | None:
    front = str(item.get("front") or "").strip()
    back = str(item.get("back") or "").strip()
    if not front or not back:
        return None
    model = str(item.get("model") or default_model).strip() or default_model
    suggested_question_type = str(item.get("suggested_question_type") or model).strip() or model
    tags_raw = item.get("tags") or []
    tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
    return {
        "id": str(item.get("id") or f"card_{uuid.uuid4().hex[:8]}"),
        "model": model,
        "suggested_question_type": suggested_question_type,
        "front": front,
        "back": back,
        "tags": tags,
        "source_unit_id": item.get("source_unit_id"),
        "status": str(item.get("status") or "draft"),
    }


async def _generate_cards_with_llm(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    units = payload.get("learning_units") or []
    evidence_items = payload.get("evidence_items") or []
    file_ids = payload.get("file_ids") or []
    session_id = payload.get("session_id")
    user_input = str(payload.get("user_input") or "").strip()
    message_knowledge = str(payload.get("message_knowledge") or "").strip()
    subject_domain = str(payload.get("subject_domain") or "general")
    query_scope = str(payload.get("query_scope") or "focused")
    document_titles = _collect_document_titles(payload)
    file_tree_input = _is_file_tree_input(payload)
    preferred_model = str(
        payload.get("selected_template_profile")
        or payload.get("template_default_profile")
        or "default"
    )
    available_models = [
        str(item).strip()
        for item in (payload.get("template_profiles") or [])
        if str(item).strip()
    ]
    if preferred_model not in available_models and available_models:
        preferred_model = available_models[0]

    evidence_blocks: List[Dict[str, str]] = []
    if isinstance(evidence_items, list) and evidence_items:
        for idx, item in enumerate(evidence_items[:24], start=1):
            if not isinstance(item, dict):
                continue
            node = item.get("node") if isinstance(item.get("node"), dict) else {}
            title = str(node.get("title") or f"Node {idx}").strip()
            summary = str(node.get("summary") or "").strip()
            evidence = str(item.get("content") or "").strip()
            if not evidence:
                continue
            evidence_blocks.append(
                {
                    "unit_id": str(node.get("node_id") or f"node_{idx}"),
                    "title": title,
                    "summary": summary,
                    "evidence": evidence[:1800],
                }
            )
    elif file_tree_input:
        # On file-tree path, never fall back to legacy unit-driven retrieval.
        return []
    elif isinstance(units, list):
        for unit in units[:8]:
            if not isinstance(unit, dict):
                continue
            title = str(unit.get("title") or "").strip()
            summary = str(unit.get("content_summary") or unit.get("description") or "").strip()
            evidence = ""
            rag_query = "\n".join([x for x in [user_input, title, summary] if x]).strip()
            if rag_query:
                try:
                    rag = await query_knowledge.ainvoke(
                        {
                            "query": rag_query,
                            "mode": "mix",
                            "top_k": 5,
                            "session_id": session_id,
                            "file_ids": [],
                            "user_id": None,
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

    if file_tree_input and not evidence_blocks:
        # Hard stop: file-tree path requires evidence-loop output.
        return []
    if not evidence_blocks:
        return []

    principles_text = await _format_principles_for_prompt(
        json.dumps(
            {
                "stage": "generate_cards",
                "user_input": user_input,
                "query_scope": query_scope,
                "subject_domain": subject_domain,
            },
            ensure_ascii=False,
        )
    )
    system_prompt = (
        "You are a multilingual flashcard generator. "
        "Generate accurate cards from node evidence, independent of language. "
        "Return JSON only: {\"cards\": [{\"front\": str, \"back\": str, \"source_unit_id\": str, \"model\": str, \"suggested_question_type\": str, \"tags\": [str]}]}. "
        "If available_models has more than one item, choose the most suitable model per card and avoid putting all cards in the same model unless truly necessary. "
        "Apply progressive disclosure: front should be focused and answerable; back should be concise and not overload unrelated details. "
        "Hard constraints: each question must be directly answerable from the provided evidence; do not ask generic or undefined 'what is X' questions unless evidence explicitly defines X; "
        "avoid vague fronts, avoid missing context, and keep each card atomic to one testable fact/rule/procedure."
    )
    if query_scope == "title_only":
        system_prompt += " Strictly stay on document title intent. Produce at most 2 cards."
    if principles_text:
        system_prompt = f"{system_prompt}\n\n{principles_text}"
    default_count = max(2, len(evidence_blocks) * 2)
    max_cards = _card_budget_from_scope(query_scope, default_count=default_count)
    profile = _resolve_policy_profile(subject_domain=subject_domain, query_scope=query_scope)
    user_prompt = {
        "user_input": user_input,
        "query_scope": query_scope,
        "document_titles": document_titles,
        "subject_domain": subject_domain,
        "available_models": available_models,
        "preferred_model": preferred_model,
        "max_cards": max_cards,
        "message_knowledge": message_knowledge[:2000],
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
                if normalized and available_models:
                    model = str(normalized.get("model") or "").strip()
                    if model not in available_models:
                        normalized["model"] = preferred_model
                if normalized:
                    violations = _intent_rule_violations(
                        normalized,
                        query_scope=query_scope,
                        doc_titles=document_titles,
                        profile=profile,
                    )
                    if violations:
                        continue
                    cards.append(normalized)
        if query_scope == "title_only":
            cards = cards[:2]
        return cards
    except Exception:
        return []


async def _refine_cards_with_llm(cards: List[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not cards:
        return []
    available_models = [
        str(item).strip()
        for item in (payload.get("template_profiles") or [])
        if str(item).strip()
    ]
    preferred_model = str(
        payload.get("selected_template_profile")
        or payload.get("template_default_profile")
        or "default"
    )
    if preferred_model not in available_models and available_models:
        preferred_model = available_models[0]

    principles_text = await _format_principles_for_prompt(
        json.dumps(
            {
                "stage": "refine_cards",
                "subject_domain": payload.get("subject_domain") or "general",
                "difficulty": payload.get("difficulty_level") or "medium",
            },
            ensure_ascii=False,
        )
    )
    system_prompt = (
        "You are a multilingual flashcard editor. "
        "Improve clarity, reduce ambiguity, and split overloaded cards when needed. "
        "Return JSON only: {\"cards\": [{\"id\": str, \"front\": str, \"back\": str, \"model\": str, \"tags\": [str], \"source_unit_id\": str}]}. "
        "Preserve original language and keep evidence concise."
    )
    if principles_text:
        system_prompt = f"{system_prompt}\n\n{principles_text}"
    user_prompt = {
        "subject_domain": payload.get("subject_domain") or "general",
        "difficulty": payload.get("difficulty_level") or "medium",
        "available_models": available_models,
        "preferred_model": preferred_model,
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
                normalized = _normalize_card(item, default_model=preferred_model)
                if normalized and available_models:
                    model = str(normalized.get("model") or "").strip()
                    if model not in available_models:
                        normalized["model"] = preferred_model
                if normalized:
                    normalized["status"] = "refined"
                    refined.append(normalized)
        return refined or cards
    except Exception:
        return cards


async def _assign_question_types_with_llm(cards: List[Dict[str, Any]], available_models: List[str], preferred_model: str) -> List[Dict[str, Any]]:
    if not cards or len(available_models) <= 1:
        for card in cards:
            if isinstance(card, dict):
                model = str(card.get("model") or preferred_model).strip() or preferred_model
                card["model"] = model
                card["suggested_question_type"] = model
        return cards

    system_prompt = (
        "You are a flashcard typing classifier. "
        "For each card, choose the best model from available_models only. "
        "Return JSON only: {\"assignments\": [{\"id\": str, \"model\": str}]}. "
        "Use at least two models when content allows."
    )
    condensed_cards = [
        {
            "id": str(card.get("id") or ""),
            "front": str(card.get("front") or "")[:240],
            "back": str(card.get("back") or "")[:240],
        }
        for card in cards[:80]
        if isinstance(card, dict)
    ]
    user_prompt = {
        "available_models": available_models,
        "preferred_model": preferred_model,
        "cards": condensed_cards,
    }

    assignments: Dict[str, str] = {}
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
        raw = parsed.get("assignments") if isinstance(parsed, dict) else []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                card_id = str(item.get("id") or "").strip()
                model = str(item.get("model") or "").strip()
                if not card_id or model not in available_models:
                    continue
                assignments[card_id] = model
    except Exception:
        assignments = {}

    typed_cards: List[Dict[str, Any]] = []
    for idx, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "").strip()
        model = assignments.get(card_id) or str(card.get("model") or preferred_model).strip()
        if model not in available_models:
            model = preferred_model
        card["model"] = model
        card["suggested_question_type"] = model
        typed_cards.append(card)

    # Degenerate outputs from model assignment are common; keep distribution usable.
    used_models = {str(card.get("model") or "").strip() for card in typed_cards if isinstance(card, dict)}
    if len(used_models) <= 1 and len(available_models) > 1 and len(typed_cards) > 1:
        for idx, card in enumerate(typed_cards):
            model = available_models[idx % len(available_models)]
            card["model"] = model
            card["suggested_question_type"] = model

    return typed_cards


def _sanitize_soft_reason_codes(raw_codes: Any) -> List[str]:
    if not isinstance(raw_codes, list):
        return []
    out: List[str] = []
    seen = set()
    for item in raw_codes:
        code = str(item or "").strip()
        if not code or code not in SOFT_REASON_CODES or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


async def _soft_judge_with_llm(
    cards: List[Dict[str, Any]],
    *,
    query_scope: str,
    document_titles: List[str],
    principles_text: str,
    profile: PolicyProfile,
) -> Dict[str, Dict[str, Any]]:
    if not cards:
        return {}
    system_prompt = (
        "You are a multilingual flashcard soft-quality judge. "
        "Judge only teaching quality dimensions: clarity, learnability, conciseness. "
        "Do not judge hard structural constraints. "
        "Return JSON only: "
        "{\"results\": [{\"card_id\": str, \"decision\": \"approve|reject\", \"score\": number, \"reason_codes\": [str]}]}."
    )
    if query_scope == "title_only":
        system_prompt += " Keep strict intent relevance to document title."
    if principles_text:
        system_prompt = f"{system_prompt}\n\n{principles_text}"
    user_prompt = {
        "query_scope": query_scope,
        "document_titles": document_titles,
        "soft_min_score": profile.soft_min_score,
        "allowed_reason_codes": sorted(SOFT_REASON_CODES),
        "cards": cards[:60],
    }
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

    judged: Dict[str, Dict[str, Any]] = {}
    raw_results = parsed.get("results") if isinstance(parsed, dict) else []
    if not isinstance(raw_results, list):
        return judged
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        card_id = str(item.get("card_id") or "").strip()
        if not card_id:
            continue
        decision = str(item.get("decision") or "").strip().lower()
        try:
            score = float(item.get("score", 0.0) or 0.0)
        except Exception:
            score = 0.0
        score = max(0.0, min(1.0, score))
        reason_codes = _sanitize_soft_reason_codes(item.get("reason_codes"))
        if decision not in {"approve", "reject"}:
            decision = "reject"
            if "soft_judge_missing_decision" not in reason_codes:
                reason_codes.append("soft_judge_missing_decision")
        if decision == "reject" and not reason_codes:
            reason_codes = ["soft_model_reject"]
        judged[card_id] = {"decision": decision, "score": score, "reason_codes": reason_codes}
    return judged


async def _quality_gate_with_llm(
    cards: List[Dict[str, Any]],
    *,
    query_scope: str,
    document_titles: List[str],
    subject_domain: str,
) -> Dict[str, Any]:
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

    principles_text = await _format_principles_for_prompt(
        json.dumps(
            {
                "stage": "quality_gate",
                "query_scope": query_scope,
                "document_titles": document_titles[:4],
            },
            ensure_ascii=False,
        )
    )
    profile = _resolve_policy_profile(subject_domain=subject_domain, query_scope=query_scope)
    id_to_card = {str(card.get("id")): card for card in cards if isinstance(card, dict)}

    approved_cards: List[Dict[str, Any]] = []
    failed_cards: List[Dict[str, Any]] = []

    hard_failed: Dict[str, List[str]] = {}
    hard_pass_cards: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "").strip()
        if not card_id:
            continue
        violations = _intent_rule_violations(
            card,
            query_scope=query_scope,
            doc_titles=document_titles,
            profile=profile,
        )
        if violations:
            hard_failed[card_id] = violations
        else:
            hard_pass_cards.append(card)

    soft_judged = await _soft_judge_with_llm(
        hard_pass_cards,
        query_scope=query_scope,
        document_titles=document_titles,
        principles_text=principles_text,
        profile=profile,
    )

    for card in hard_pass_cards:
        cid = str(card.get("id") or "")
        decision = soft_judged.get(cid, {})
        is_approved = str(decision.get("decision") or "reject") == "approve"
        soft_score = float(decision.get("score", 0.0) or 0.0)
        if is_approved and soft_score >= profile.soft_min_score:
            approved_cards.append(card)
            continue
        reasons = list(decision.get("reason_codes") or [])
        if not reasons and soft_score < profile.soft_min_score:
            reasons = ["soft_low_clarity"]
        failed_cards.append(
            {
                "card": card,
                "reason_codes": reasons or ["soft_model_reject"],
                "critical": False,
                "score": soft_score,
            }
        )

    approved_set = {str(card.get("id")) for card in approved_cards}

    for card in cards:
        cid = str(card.get("id"))
        if cid in approved_set:
            continue
        if any(str((f.get("card") or {}).get("id")) == cid for f in failed_cards):
            continue
        if cid in hard_failed:
            failed_cards.append(
                {
                    "card": card,
                    "reason_codes": hard_failed[cid],
                    "critical": True,
                    "score": 0.0,
                }
            )
            continue
        failed_cards.append(
            {
                "card": card,
                "reason_codes": ["soft_model_reject"],
                "critical": False,
                "score": 0.0,
            }
        )

    checked = len(cards)
    approved = len(approved_cards)
    failed = len(failed_cards)
    critical = sum(1 for item in failed_cards if item.get("critical"))
    pass_rate = (approved / checked) if checked else 0.0

    reason_code_counts: Dict[str, int] = {}
    for item in failed_cards:
        codes = item.get("reason_codes") if isinstance(item, dict) else []
        if not isinstance(codes, list):
            continue
        for code in codes:
            normalized = str(code or "").strip()
            if not normalized:
                continue
            reason_code_counts[normalized] = reason_code_counts.get(normalized, 0) + 1

    return {
        "approved_cards": approved_cards,
        "quality_report": {
            "checked": checked,
            "approved": approved,
            "failed": failed,
            "pass_rate": pass_rate,
            "critical_failures": critical,
            "failed_cards": failed_cards,
            "policy_profile_id": profile.profile_id,
            "reason_code_counts": reason_code_counts,
            "reason_code_coverage": reason_code_coverage_rate({"failed_cards": failed_cards}),
        },
    }


@tool
async def run_card_iteration(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run one generate->refine->quality iteration."""
    work_state = dict(payload)
    try:
        raw_cards = work_state.get("raw_cards") or []
        if not raw_cards:
            raw_cards = await _generate_cards_with_llm(work_state)

        refined_cards = await _refine_cards_with_llm(raw_cards, work_state)
        available_models = [
            str(item).strip()
            for item in (work_state.get("template_profiles") or [])
            if str(item).strip()
        ]
        preferred_model = str(
            work_state.get("selected_template_profile")
            or work_state.get("template_default_profile")
            or "default"
        )
        if preferred_model not in available_models and available_models:
            preferred_model = available_models[0]
        typed_cards = await _assign_question_types_with_llm(
            refined_cards,
            available_models=available_models,
            preferred_model=preferred_model,
        )
        quality = await _quality_gate_with_llm(
            typed_cards,
            query_scope=str(work_state.get("query_scope") or "focused"),
            document_titles=_collect_document_titles(work_state),
            subject_domain=str(work_state.get("subject_domain") or "general"),
        )

        report = quality.get("quality_report") or {}
        return {
            "approved_cards": quality.get("approved_cards") or [],
            "quality_report": report,
            "raw_cards": raw_cards,
            "refined_cards": typed_cards,
        }
    except SkillSelectorUnavailableError:
        return {
            "fatal_error": "selector_unavailable",
            "approved_cards": [],
            "quality_report": {},
            "raw_cards": [],
            "refined_cards": [],
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
                "reason_codes": item.get("reason_codes") or item.get("violations") or [],
                "critical": bool(item.get("critical")),
            }
        )
    return findings


def _normalize_lookup_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _token_set(value: str) -> set[str]:
    return {tok for tok in _normalize_lookup_key(value).split(" ") if len(tok) > 1}


def _pick_best_evidence(front: str, source_unit_id: str, evidence_index: Dict[str, str]) -> str:
    if not evidence_index:
        return ""
    if source_unit_id:
        direct_by_unit = str(evidence_index.get(source_unit_id) or "").strip()
        if direct_by_unit:
            return direct_by_unit
    normalized_front = _normalize_lookup_key(front)
    direct = str(evidence_index.get(normalized_front) or "").strip()
    if direct:
        return direct
    front_tokens = _token_set(front)
    best_text = ""
    best_score = 0
    for key, value in evidence_index.items():
        evidence = str(value or "").strip()
        if not evidence:
            continue
        score = len(front_tokens & _token_set(key)) if front_tokens else 0
        if score > best_score:
            best_score = score
            best_text = evidence
    if best_text:
        return best_text
    return str(next(iter(evidence_index.values()), "") or "").strip()


@tool
async def fixer_apply_repair(
    failed_cards: List[Dict[str, Any]],
    session_id: str | None,
    user_id: str | None,
    file_ids: List[str],
    evidence_cache: Dict[str, str] | None = None,
    evidence_index: Dict[str, str] | None = None,
) -> List[Dict[str, Any]]:
    """Fixer: backfill failed cards with existing evidence only."""
    cache = evidence_cache if isinstance(evidence_cache, dict) else {}
    support_index = evidence_index if isinstance(evidence_index, dict) else {}
    seen_fronts: set[str] = set()
    updated: List[Dict[str, Any]] = []
    for item in failed_cards[:10]:
        card = item.get("card") if isinstance(item, dict) else None
        if not isinstance(card, dict):
            continue
        front = str(card.get("front") or "").strip()
        if not front or front in seen_fronts:
            continue
        seen_fronts.add(front)
        source_unit_id = str(card.get("source_unit_id") or "").strip()
        cache_key = source_unit_id or str(card.get("id") or "").strip() or _normalize_lookup_key(front)
        evidence = str(cache.get(cache_key) or "").strip()
        if not evidence:
            evidence = _pick_best_evidence(front, source_unit_id, support_index)
        if evidence:
            cache[cache_key] = evidence
            back = str(card.get("back") or "").strip()
            evidence_block = f"Evidence:\n{evidence[:1200]}".strip()
            if evidence_block not in back:
                card["back"] = f"{back}\n\n{evidence_block}".strip()
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


def _score_from_quality_report(report: Dict[str, Any]) -> Dict[str, Any]:
    checked = max(0, int(report.get("checked") or 0))
    approved = max(0, int(report.get("approved") or 0))
    critical = max(0, int(report.get("critical_failures") or 0))
    if checked <= 0:
        return {"score": 0, "reason": "empty_quality_report", "confidence": 1.0}
    pass_rate = max(0.0, min(1.0, float(report.get("pass_rate") or (approved / checked))))
    base_score = int(round(pass_rate * 100))
    critical_penalty = critical * 20
    score = max(0, min(100, base_score - critical_penalty))
    reason = (
        f"rule_based_quality_score:"
        f"pass_rate={pass_rate:.2f},"
        f"checked={checked},approved={approved},critical_failures={critical},"
        f"penalty={critical_penalty}"
    )
    return {"score": score, "reason": reason, "confidence": 1.0}


def _compute_evidence_coverage(cards: List[Dict[str, Any]], evidence_items: List[Dict[str, Any]]) -> float:
    """计算卡片对证据的覆盖率，更宽松的计算方式"""
    if not evidence_items:
        return 1.0 if cards else 0.0  # 如果没有证据要求，有卡片就算100%
    
    all_units = set()
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        node = item.get("node") if isinstance(item.get("node"), dict) else {}
        node_id = str(node.get("node_id") or "").strip()
        if node_id:
            all_units.add(node_id)
    
    if not all_units:
        return 1.0 if cards else 0.0  # 如果没有可追踪的单元，有卡片就算100%
    
    covered_units = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        unit_id = str(card.get("source_unit_id") or "").strip()
        if unit_id and unit_id in all_units:
            covered_units.add(unit_id)
    
    # 如果有卡片但没有匹配到 source_unit_id，给予基础覆盖率
    if not covered_units and cards:
        # 基于卡片数量给予合理的覆盖率估算
        return min(1.0, len(cards) / max(1, len(all_units)))
    
    return len(covered_units) / max(1, len(all_units))


def _build_evidence_index(work_state: Dict[str, Any]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for item in (work_state.get("evidence_items") or []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        node = item.get("node") if isinstance(item.get("node"), dict) else {}
        node_id = str(node.get("node_id") or "").strip()
        keys = [
            str(item.get("query") or "").strip(),
            str(node.get("title") or "").strip(),
            str(node.get("summary") or "").strip(),
        ]
        if node_id:
            index[node_id] = content
        for raw_key in keys:
            key = _normalize_lookup_key(raw_key)
            if key and key not in index:
                index[key] = content
    return index


async def run_card_supervisor(
    state: CardSupervisorState,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    context = runtime.context
    threshold = int(state.get("judge_score_threshold") or 90)
    max_iterations = int(state.get("max_qa_iterations") or 5)
    min_coverage = float(state.get("min_evidence_coverage") or 0.40)  # 降低到40%，更实际
    min_gain_delta = float(state.get("min_gain_delta") or 0.02)
    file_tree_input = bool(state.get("file_ids")) and str(state.get("query_scope") or "").strip().lower() in FILE_TREE_SCOPES

    work_state: Dict[str, Any] = {
        "user_id": context.user_id if context else None,
        "session_id": context.session_id if context else None,
        "user_input": state.get("user_input", ""),
        "topic": state.get("user_input", ""),
        "message_knowledge": state.get("message_knowledge", ""),
        "subject_domain": state.get("subject_domain", "general"),
        "query_scope": state.get("query_scope") or "focused",
        "learning_units": state.get("learning_units") or [],
        "evidence_items": state.get("evidence_items") or [],
        "document_trees": state.get("document_trees") or [],
        "template_profiles": state.get("template_profiles") or [],
        "template_default_profile": state.get("template_default_profile"),
        "selected_template_profile": state.get("selected_template_profile"),
        "file_ids": state.get("file_ids") or [],
    }

    if file_tree_input:
        # File-tree path must come from evidence_loop output only.
        work_state["learning_units"] = []

    if file_tree_input and not work_state["evidence_items"]:
        return {
            "status": "failed",
            "reason": "missing_file_tree_evidence_items",
            "approved_cards": [],
            "quality_report": {},
            "qa_loop_report": {
                "max_iterations": max_iterations,
                "iterations_used": 0,
                "best_score": 0,
                "final_score": 0,
                "exit_reason": "missing_file_tree_evidence_items",
                "review_findings": [],
                "judge_scores": [],
                "fix_actions": [],
            },
        }

    if not file_tree_input and not work_state["learning_units"] and not work_state["evidence_items"]:
        return {
            "status": "failed",
            "reason": "missing_evidence_inputs",
            "approved_cards": [],
            "quality_report": {},
            "qa_loop_report": {
                "max_iterations": max_iterations,
                "iterations_used": 0,
                "best_score": 0,
                "final_score": 0,
                "exit_reason": "missing_evidence_inputs",
                "review_findings": [],
                "judge_scores": [],
                "fix_actions": [],
            },
        }

    last_report: Dict[str, Any] = {}
    approved_cards: List[Dict[str, Any]] = []
    best_effort_cards: List[Dict[str, Any]] = []
    best_score = 0
    final_score = 0
    review_findings_log: List[Dict[str, Any]] = []
    judge_scores_log: List[Dict[str, Any]] = []
    fix_actions_log: List[Dict[str, Any]] = []
    evidence_cache: Dict[str, str] = {}
    evidence_index = _build_evidence_index(work_state)
    stagnant_rounds = 0
    iterations_used = 0
    exit_reason = "max_iterations_reached"
    previous_score: int | None = None
    previous_coverage: float | None = None
    convergence_trace: List[Dict[str, Any]] = []

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        iteration_result = await run_card_iteration.ainvoke({"payload": work_state})
        if str(iteration_result.get("fatal_error") or "").strip() == "selector_unavailable":
            return {
                "status": "failed",
                "reason": "selector_unavailable",
                "approved_cards": [],
                "quality_report": {},
                "qa_loop_report": {
                    "max_iterations": max_iterations,
                    "iterations_used": iteration - 1,
                    "best_score": best_score,
                    "final_score": final_score,
                    "exit_reason": "selector_unavailable",
                    "review_findings": review_findings_log,
                    "judge_scores": judge_scores_log,
                    "fix_actions": fix_actions_log,
                    "convergence_trace": convergence_trace,
                },
            }
        report = iteration_result.get("quality_report") or {}
        approved_cards = iteration_result.get("approved_cards") or []
        best_effort_cards = (
            iteration_result.get("refined_cards")
            or iteration_result.get("raw_cards")
            or best_effort_cards
        )
        last_report = report

        findings = await reviewer_readonly.ainvoke({"report": report})
        review_findings_log.append({"iteration": iteration, "findings": findings})

        failed_cards = report.get("failed_cards") or []
        repaired_cards: List[Dict[str, Any]] = await fixer_apply_repair.ainvoke(
            {
                "failed_cards": failed_cards,
                "session_id": context.session_id if context else None,
                "user_id": context.user_id if context else None,
                "file_ids": state.get("file_ids") or [],
                "evidence_cache": evidence_cache,
                "evidence_index": evidence_index,
            }
        )
        fix_actions_log.append(
            {
                "iteration": iteration,
                "failed_cards": len(failed_cards),
                "repaired_cards": len(repaired_cards),
            }
        )
        
        # 关键修复：合并通过的卡片和修复的卡片，而不是只用修复的
        if repaired_cards:
            # 保留已批准的卡片 + 修复后的卡片
            combined_cards = list(approved_cards) if approved_cards else []
            combined_cards.extend(repaired_cards)
            work_state["raw_cards"] = combined_cards
        elif approved_cards:
            # 如果没有需要修复的，但有批准的卡片，继续用批准的卡片
            work_state["raw_cards"] = list(approved_cards)

        judged = _score_from_quality_report(report)
        score = int(judged.get("score", 0) or 0)
        final_score = score
        best_score = max(best_score, score)
        coverage = _compute_evidence_coverage(
            approved_cards if approved_cards else best_effort_cards,
            work_state.get("evidence_items") or [],
        )
        quality_delta = score if previous_score is None else (score - previous_score)
        coverage_delta = coverage if previous_coverage is None else (coverage - previous_coverage)
        normalized_gain = max(0.0, quality_delta / 100.0) + max(0.0, coverage_delta)
        convergence_trace.append(
            {
                "iteration": iteration,
                "score": score,
                "quality_delta": quality_delta,
                "coverage": round(coverage, 4),
                "coverage_delta": round(coverage_delta, 4),
                "normalized_gain": round(normalized_gain, 4),
                "repaired_cards": len(repaired_cards),
            }
        )
        judge_scores_log.append({"iteration": iteration, **judged})
        if previous_score is not None and normalized_gain < min_gain_delta and not repaired_cards:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
        previous_score = score
        previous_coverage = coverage

        # 提前退出条件：分数达标且覆盖率合理，或者分数很高
        if score >= threshold and coverage >= min_coverage:
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
                    "coverage": round(coverage, 4),
                    "coverage_target": min_coverage,
                    "exit_reason": "score_and_coverage_passed",
                    "review_findings": review_findings_log,
                    "judge_scores": judge_scores_log,
                    "fix_actions": fix_actions_log,
                    "convergence_trace": convergence_trace,
                },
            }
        
        # 新增：如果分数很高（>=95）且有批准的卡片，即使 coverage 稍低也接受
        if score >= 95 and approved_cards and coverage >= min_coverage * 0.5:
            return {
                "status": "quality_pass",
                "reason": "high_quality_score_passed",
                "approved_cards": approved_cards,
                "quality_report": report,
                "qa_loop_report": {
                    "max_iterations": max_iterations,
                    "iterations_used": iteration,
                    "best_score": best_score,
                    "final_score": final_score,
                    "coverage": round(coverage, 4),
                    "coverage_target": min_coverage,
                    "exit_reason": "high_quality_early_exit",
                    "review_findings": review_findings_log,
                    "judge_scores": judge_scores_log,
                    "fix_actions": fix_actions_log,
                    "convergence_trace": convergence_trace,
                },
            }
        
        if stagnant_rounds >= 2:
            exit_reason = "converged_low_gain"
            break

    # 循环结束后的处理逻辑
    final_cards = approved_cards if approved_cards else [c for c in best_effort_cards if isinstance(c, dict)]
    final_coverage = _compute_evidence_coverage(final_cards, work_state.get("evidence_items") or [])
    
    # 如果完全没有卡片，返回失败
    if not final_cards:
        return {
            "status": "failed",
            "reason": "missing_file_tree_evidence" if file_tree_input else "missing_file_grounded_evidence",
            "approved_cards": [],
            "quality_report": last_report,
            "qa_loop_report": {
                "max_iterations": max_iterations,
                "iterations_used": iterations_used,
                "best_score": best_score,
                "final_score": final_score,
                "exit_reason": "no_cards_generated",
                "review_findings": review_findings_log,
                "judge_scores": judge_scores_log,
                "fix_actions": fix_actions_log,
                "convergence_trace": convergence_trace,
            },
        }
    
    # 如果分数达标，即使 coverage 不够，也返回成功（降级接受）
    if final_score >= threshold:
        return {
            "status": "quality_pass",
            "reason": "judge_score_passed_coverage_low" if final_coverage < min_coverage else "judge_score_passed",
            "approved_cards": final_cards,
            "quality_report": last_report,
            "qa_loop_report": {
                "max_iterations": max_iterations,
                "iterations_used": iterations_used,
                "best_score": best_score,
                "final_score": final_score,
                "coverage": round(final_coverage, 4),
                "coverage_target": min_coverage,
                "exit_reason": exit_reason,
                "review_findings": review_findings_log,
                "judge_scores": judge_scores_log,
                "fix_actions": fix_actions_log,
                "convergence_trace": convergence_trace,
            },
        }
    
    # 分数不达标，但有卡片，返回失败但保留卡片
    return {
        "status": "failed",
        "reason": "quality_threshold_not_met",
        "approved_cards": final_cards,  # 保留卡片，不要清空
        "quality_report": last_report,
        "qa_loop_report": {
            "max_iterations": max_iterations,
            "iterations_used": iterations_used,
            "best_score": best_score,
            "final_score": final_score,
            "coverage": round(final_coverage, 4),
            "coverage_target": min_coverage,
            "exit_reason": exit_reason,
            "review_findings": review_findings_log,
            "judge_scores": judge_scores_log,
            "fix_actions": fix_actions_log,
            "convergence_trace": convergence_trace,
        },
    }
