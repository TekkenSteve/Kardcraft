"""Utility helpers for card generation agent."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from langchain_core.tools import tool

from kardcraft.agent_skills import (
    SkillSelectorUnavailableError,
    build_skill_guidance_text,
)
from kardcraft.llm.client import chat_complete
from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger


FILE_TREE_SCOPES = {"title_only", "focused", "full_doc"}
HARD_REASON_CODES = {
    "hard_front_too_long",
    "hard_back_too_long",
    "hard_non_atomic_back",
    "hard_title_scope_drift",
    "hard_question_type_mismatch",
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
    expected_question_type: str = "",
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
    expected_qtype = str(expected_question_type or "").strip()
    if expected_qtype:
        card_qtype = str(card.get("suggested_question_type") or card.get("model") or "").strip()
        if card_qtype and card_qtype != expected_qtype:
            violations.append("hard_question_type_mismatch")
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


def _safe_profile_prompt_hint(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("profile_prompt_hint")
    if not isinstance(raw, dict):
        return {}
    sample_fields = raw.get("sample_fields") if isinstance(raw.get("sample_fields"), dict) else {}
    return {
        "requested_profile": str(raw.get("requested_profile") or "").strip(),
        "resolved_profile": str(raw.get("resolved_profile") or "").strip(),
        "resolution": str(raw.get("resolution") or "").strip(),
        "sample_fields": {str(k): str(v) for k, v in sample_fields.items() if str(k).strip()},
        "field_order": [str(x).strip() for x in (raw.get("field_order") or []) if str(x).strip()],
    }


def _resolve_selected_question_type(payload: Dict[str, Any]) -> str:
    hint = _safe_profile_prompt_hint(payload)
    resolved = str(hint.get("resolved_profile") or "").strip()
    if resolved:
        return resolved
    preferred_model = str(
        payload.get("selected_template_profile")
        or payload.get("template_default_profile")
        or "default"
    ).strip()
    return preferred_model or "default"


def _evidence_unit_id(node: Dict[str, Any], fallback: str) -> str:
    node_id = str(node.get("node_id") or "").strip()
    file_id = str(node.get("file_id") or "").strip()
    if file_id and node_id:
        return f"{file_id}:{node_id}"
    if node_id:
        return node_id
    return fallback


def _split_unit_id(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    if ":" not in text:
        return "", text
    file_id, node_id = text.rsplit(":", 1)
    return file_id.strip(), node_id.strip()


async def _generate_questions_with_llm(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    preferred_model = _resolve_selected_question_type(payload)
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
                    "unit_id": _evidence_unit_id(node, f"node_{idx}"),
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
    profile_hint = _safe_profile_prompt_hint(payload)
    system_prompt = (
        "You are a multilingual flashcard question generator. "
        "Generate question drafts only from evidence. "
        "Return JSON only: {\"questions\": [{\"question\": str, \"source_unit_id\": str, \"tags\": [str]}]}. "
        "Each question must be directly answerable from provided evidence and align with selected question_type."
    )
    if query_scope == "title_only":
        system_prompt += " Strictly stay on document title intent. Produce at most 2 cards."
    if principles_text:
        system_prompt = f"{system_prompt}\n\n{principles_text}"
    default_count = max(2, len(evidence_blocks) * 2)
    max_cards = _card_budget_from_scope(query_scope, default_count=default_count)
    user_prompt: Dict[str, Any] = {
        "user_input": user_input,
        "query_scope": query_scope,
        "document_titles": document_titles,
        "subject_domain": subject_domain,
        "question_type": preferred_model,
        "max_cards": max_cards,
        "message_knowledge": message_knowledge[:2000],
        "units": evidence_blocks,
    }
    if profile_hint:
        user_prompt["profile_prompt_hint"] = profile_hint
    if available_models:
        user_prompt["available_models"] = available_models

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
        parsed = safe_parse_llm_json(content, default={"questions": []})
        questions_raw = parsed.get("questions") if isinstance(parsed, dict) else []
        questions: List[Dict[str, Any]] = []
        dropped = 0
        if isinstance(questions_raw, list):
            for item in questions_raw:
                if not isinstance(item, dict):
                    continue
                front = str(item.get("question") or item.get("front") or "").strip()
                if not front:
                    dropped += 1
                    continue
                source_unit_id = str(item.get("source_unit_id") or "").strip()
                tags_raw = item.get("tags") if isinstance(item.get("tags"), list) else []
                tags = [str(t).strip() for t in tags_raw if str(t).strip()]
                questions.append(
                    {
                        "id": str(item.get("id") or f"card_{uuid.uuid4().hex[:8]}"),
                        "front": front,
                        "source_unit_id": source_unit_id,
                        "question_type": preferred_model,
                        "model": preferred_model,
                        "suggested_question_type": preferred_model,
                        "tags": tags,
                        "status": "question_draft",
                    }
                )
        if query_scope == "title_only":
            questions = questions[:2]
        if questions:
            logger.debug(
                "question generation llm output summary",
                evidence_block_count=len(evidence_blocks),
                llm_question_count=len(questions_raw) if isinstance(questions_raw, list) else 0,
                normalized_question_count=len(questions),
                normalized_drop_count=dropped,
                query_scope=query_scope,
                question_type=preferred_model,
                hint_resolution=str(profile_hint.get("resolution") or ""),
            )
        else:
            logger.warning(
                "question generation produced zero normalized questions",
                evidence_block_count=len(evidence_blocks),
                llm_question_count=len(questions_raw) if isinstance(questions_raw, list) else 0,
                normalized_drop_count=dropped,
                query_scope=query_scope,
                question_type=preferred_model,
            )
        return questions
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
    expected_question_type: str = "",
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
            expected_question_type=expected_question_type,
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
async def run_question_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Generate question drafts scoped by selected evidence/units."""
    work_state = dict(payload or {})
    try:
        question_drafts = await _generate_questions_with_llm(work_state)
        selected_qtype = _resolve_selected_question_type(work_state)
        for draft in question_drafts:
            if isinstance(draft, dict):
                draft["question_type"] = str(draft.get("question_type") or selected_qtype).strip() or selected_qtype
        logger.debug(
            "question generation stage summary",
            question_drafts_count=len(question_drafts),
            evidence_items_count=len(work_state.get("evidence_items") or []),
            learning_units_count=len(work_state.get("learning_units") or []),
            selected_question_type=selected_qtype,
        )
        return {"question_drafts": question_drafts}
    except SkillSelectorUnavailableError:
        return {"fatal_error": "selector_unavailable", "question_drafts": []}


@tool
async def run_answer_generation(
    question_drafts: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate answer drafts via LLM using question drafts + selected question type."""
    work_state = dict(payload or {})
    profile_hint = _safe_profile_prompt_hint(work_state)
    selected_qtype = _resolve_selected_question_type(work_state)
    evidence_index = _build_evidence_index(work_state)
    if not question_drafts:
        return {"answer_drafts": []}

    condensed_questions: List[Dict[str, Any]] = []
    for draft in question_drafts:
        if not isinstance(draft, dict):
            continue
        card_id = str(draft.get("id") or "").strip()
        front = str(draft.get("front") or "").strip()
        source_unit_id = str(draft.get("source_unit_id") or "").strip()
        if not card_id or not front:
            continue
        evidence = _pick_best_evidence(front, source_unit_id, evidence_index)
        condensed_questions.append(
            {
                "id": card_id,
                "question": front[:260],
                "question_type": str(draft.get("question_type") or selected_qtype).strip() or selected_qtype,
                "source_unit_id": source_unit_id,
                "evidence": evidence[:600],
            }
        )

    if not condensed_questions:
        return {"answer_drafts": []}

    system_prompt = (
        "You are a multilingual flashcard answer generator. "
        "Generate concise, evidence-grounded answer drafts for each question. "
        "Return JSON only: {\"answers\": [{\"id\": str, \"answer\": str, \"question_type\": str}]}. "
        "Respect the question_type style and do not invent unsupported facts."
    )
    user_prompt: Dict[str, Any] = {
        "selected_question_type": selected_qtype,
        "questions": condensed_questions[:40],
    }
    if profile_hint:
        user_prompt["profile_prompt_hint"] = profile_hint

    answers_by_id: Dict[str, Dict[str, Any]] = {}
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
        parsed = safe_parse_llm_json(content, default={"answers": []})
        answers_raw = parsed.get("answers") if isinstance(parsed, dict) else []
        if isinstance(answers_raw, list):
            for item in answers_raw:
                if not isinstance(item, dict):
                    continue
                card_id = str(item.get("id") or "").strip()
                answer = str(item.get("answer") or item.get("back") or "").strip()
                if not card_id or not answer:
                    continue
                qtype = str(item.get("question_type") or "").strip() or selected_qtype
                answers_by_id[card_id] = {"answer": answer, "question_type": qtype}
    except Exception:
        answers_by_id = {}

    answer_drafts: List[Dict[str, Any]] = []
    for draft in question_drafts or []:
        if not isinstance(draft, dict):
            continue
        card_id = str(draft.get("id") or "").strip()
        front = str(draft.get("front") or "").strip()
        source_unit_id = str(draft.get("source_unit_id") or "").strip()
        if not card_id or not front:
            continue
        question_type = str(draft.get("question_type") or selected_qtype).strip() or selected_qtype
        answer = str((answers_by_id.get(card_id) or {}).get("answer") or "").strip()
        answer_qtype = str((answers_by_id.get(card_id) or {}).get("question_type") or question_type).strip() or question_type
        if not answer:
            answer = _pick_best_evidence(front, source_unit_id, evidence_index)
            answer_qtype = question_type
        if not answer:
            continue
        answer_drafts.append(
            {
                "id": card_id,
                "answer": answer,
                "back": answer,
                "question_type": answer_qtype,
                "status": "answer_draft",
            }
        )
    return {"answer_drafts": answer_drafts}


@tool
async def run_card_assembly(
    question_drafts: List[Dict[str, Any]],
    answer_drafts: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble QA cards (front=question, back=answer) for quality evaluation."""
    work_state = dict(payload or {})
    selected_qtype = _resolve_selected_question_type(work_state)
    answer_by_id = {
        str(item.get("id") or "").strip(): item
        for item in (answer_drafts or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    assembled_cards: List[Dict[str, Any]] = []
    for draft in question_drafts or []:
        if not isinstance(draft, dict):
            continue
        card_id = str(draft.get("id") or "").strip()
        front = str(draft.get("front") or "").strip()
        if not card_id or not front:
            continue
        answer_item = answer_by_id.get(card_id) or {}
        back = str(answer_item.get("answer") or answer_item.get("back") or "").strip()
        if not back:
            continue
        question_type = str(
            answer_item.get("question_type")
            or draft.get("question_type")
            or selected_qtype
        ).strip() or selected_qtype
        assembled_cards.append(
            {
                "id": card_id,
                "front": front,
                "back": back,
                "model": question_type,
                "suggested_question_type": question_type,
                "source_unit_id": draft.get("source_unit_id"),
                "tags": [str(t).strip() for t in (draft.get("tags") or []) if str(t).strip()],
                "status": "assembled",
            }
        )
    return {"assembled_cards": assembled_cards}


@tool
async def run_card_quality_pipeline(cards: List[Dict[str, Any]], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run refinement, typing, and quality gate on output-agent cards."""
    work_state = dict(payload or {})
    try:
        refined_cards = await _refine_cards_with_llm(cards, work_state)
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
        # Keep selected question type linked across the pipeline for this run.
        typed_cards = await _assign_question_types_with_llm(
            refined_cards,
            available_models=[preferred_model] if preferred_model else available_models,
            preferred_model=preferred_model,
        )
        quality = await _quality_gate_with_llm(
            typed_cards,
            query_scope=str(work_state.get("query_scope") or "focused"),
            document_titles=_collect_document_titles(work_state),
            subject_domain=str(work_state.get("subject_domain") or "general"),
            expected_question_type=_resolve_selected_question_type(work_state),
        )
        return {
            "approved_cards": quality.get("approved_cards") or [],
            "quality_report": quality.get("quality_report") or {},
            "refined_cards": typed_cards,
        }
    except SkillSelectorUnavailableError:
        return {
            "fatal_error": "selector_unavailable",
            "approved_cards": [],
            "quality_report": {},
            "refined_cards": [],
        }


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
        file_id = str(node.get("file_id") or "").strip()
        keys = [
            str(item.get("query") or "").strip(),
            str(node.get("title") or "").strip(),
            str(node.get("summary") or "").strip(),
        ]
        if node_id:
            index[node_id] = content
        if file_id and node_id:
            index[f"{file_id}:{node_id}"] = content
        source_unit_id = str(item.get("source_unit_id") or "").strip()
        if source_unit_id:
            index[source_unit_id] = content
            _, source_node_id = _split_unit_id(source_unit_id)
            if source_node_id:
                index[source_node_id] = content
        for raw_key in keys:
            key = _normalize_lookup_key(raw_key)
            if key and key not in index:
                index[key] = content
    return index




def reason_code_coverage_rate(report: Dict[str, Any]) -> float:
    failed_cards = report.get("failed_cards") if isinstance(report.get("failed_cards"), list) else []
    if not failed_cards:
        return 1.0
    covered = 0
    for item in failed_cards:
        if not isinstance(item, dict):
            continue
        codes = item.get("reason_codes")
        if not isinstance(codes, list):
            continue
        if any(str(code or "").strip() for code in codes):
            covered += 1
    return covered / max(1, len(failed_cards))
