"""Utility helpers for output agent."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.tools import tool

from kardcraft.llm.client import chat_complete
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger


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
    selected = str(payload.get("selected_template_profile") or "").strip()
    if selected:
        return selected
    default_profile = str(payload.get("template_default_profile") or "").strip()
    if default_profile:
        return default_profile
    return "default"


def _pick_front_back_from_fields(fields: Dict[str, Any]) -> tuple[str, str]:
    if not isinstance(fields, dict):
        return "", ""
    front = ""
    back = ""
    for key, value in fields.items():
        name = str(key or "").strip().lower()
        text = str(value or "").strip()
        if not text:
            continue
        if not front and name == "front":
            front = text
        if not back and name == "back":
            back = text
    return front, back


def _is_effectively_unformatted(
    *,
    question: str,
    answer: str,
    front: str,
    back: str,
) -> bool:
    return front.strip() == question.strip() and back.strip() == answer.strip()


async def _rewrite_single_card(
    *,
    row: Dict[str, Any],
    selected_qtype: str,
    profile_hint: Dict[str, Any],
    available_models: List[str],
) -> Dict[str, Any]:
    system_prompt = (
        "You are a flashcard formatting agent. "
        "Rewrite one question+answer pair into template-conformant card fields using the selected question type sample. "
        "Return JSON only: {\"id\": str, \"front\": str, \"back\": str, \"model\": str, "
        "\"suggested_question_type\": str, \"source_unit_id\": str, \"tags\": [str]}."
    )
    user_payload: Dict[str, Any] = {
        "selected_question_type": selected_qtype,
        "qa_pair": row,
        "profile_prompt_hint": profile_hint,
    }
    if available_models:
        user_payload["available_models"] = available_models
    try:
        response = await chat_complete(
            intent="reasoning",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            content = getattr(response.choices[0].message, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={})
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


@tool
async def run_output_generation(
    cards: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate final front/back cards from quality-approved QA cards."""
    work_state = dict(payload or {})
    selected_qtype = _resolve_selected_question_type(work_state)
    profile_hint = _safe_profile_prompt_hint(work_state)
    available_models = [
        str(item).strip()
        for item in (work_state.get("template_profiles") or [])
        if str(item).strip()
    ]

    qa_rows: List[Dict[str, Any]] = []
    for item in cards or []:
        if not isinstance(item, dict):
            continue
        card_id = str(item.get("id") or "").strip()
        if not card_id:
            continue
        question = str(item.get("front") or item.get("question") or "").strip()
        answer = str(item.get("back") or item.get("answer") or "").strip()
        if not question or not answer:
            continue
        qa_rows.append(
            {
                "id": card_id,
                "question": question,
                "answer": answer,
                "question_type": str(item.get("suggested_question_type") or item.get("model") or selected_qtype).strip() or selected_qtype,
                "source_unit_id": str(item.get("source_unit_id") or "").strip(),
                "tags": [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()],
            }
        )

    if not qa_rows:
        return {"output_cards": []}

    system_prompt = (
        "You are a flashcard output agent. "
        "You must use the selected template question-type example and its sample fields to organize each provided question+answer pair. "
        "Do not return plain question-answer copies unless sample_fields explicitly use that style. "
        "Preserve id mapping and source_unit_id. "
        "Return JSON only: {\"cards\": [{\"id\": str, \"front\": str, \"back\": str, \"model\": str, "
        "\"suggested_question_type\": str, \"source_unit_id\": str, \"tags\": [str], \"fields\": object?}]}."
    )
    user_prompt: Dict[str, Any] = {
        "selected_question_type": selected_qtype,
        "qa_pairs": qa_rows[:40],
    }
    if profile_hint:
        user_prompt["profile_prompt_hint"] = profile_hint
    if available_models:
        user_prompt["available_models"] = available_models

    llm_cards: List[Dict[str, Any]] = []
    try:
        response = await chat_complete(
            intent="reasoning",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            content = getattr(response.choices[0].message, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={"cards": []})
        raw_cards = parsed.get("cards") if isinstance(parsed, dict) else []
        if isinstance(raw_cards, list):
            llm_cards = [item for item in raw_cards if isinstance(item, dict)]
    except Exception:
        llm_cards = []

    llm_by_id = {str(item.get("id") or "").strip(): item for item in llm_cards if str(item.get("id") or "").strip()}
    output_cards: List[Dict[str, Any]] = []
    fallback_passthrough_count = 0
    rewritten_count = 0
    for row in qa_rows:
        card_id = str(row.get("id") or "").strip()
        candidate = llm_by_id.get(card_id) or {}
        original_question = str(row.get("question") or "")
        original_answer = str(row.get("answer") or "")
        front = str(candidate.get("front") or row.get("question") or "").strip()
        back = str(candidate.get("back") or row.get("answer") or "").strip()
        if (not front or not back) and isinstance(candidate.get("fields"), dict):
            front_from_fields, back_from_fields = _pick_front_back_from_fields(candidate.get("fields") or {})
            if not front and front_from_fields:
                front = front_from_fields
            if not back and back_from_fields:
                back = back_from_fields

        # If batch output failed to actually format the card, do one-card rewrite with full profile sample.
        if not front or not back or _is_effectively_unformatted(
            question=original_question,
            answer=original_answer,
            front=front,
            back=back,
        ):
            rewritten = await _rewrite_single_card(
                row=row,
                selected_qtype=selected_qtype,
                profile_hint=profile_hint,
                available_models=available_models,
            )
            if rewritten:
                candidate = rewritten
                front = str(rewritten.get("front") or front or "").strip()
                back = str(rewritten.get("back") or back or "").strip()
                if (not front or not back) and isinstance(rewritten.get("fields"), dict):
                    front_from_fields, back_from_fields = _pick_front_back_from_fields(rewritten.get("fields") or {})
                    if not front and front_from_fields:
                        front = front_from_fields
                    if not back and back_from_fields:
                        back = back_from_fields
                if front and back:
                    rewritten_count += 1
        if not front or not back:
            continue
        if _is_effectively_unformatted(
            question=original_question,
            answer=original_answer,
            front=front,
            back=back,
        ):
            fallback_passthrough_count += 1
        model = str(candidate.get("model") or row.get("question_type") or selected_qtype).strip() or selected_qtype
        if available_models and model not in available_models:
            model = selected_qtype if selected_qtype in available_models else available_models[0]
        output_cards.append(
            {
                "id": card_id,
                "front": front,
                "back": back,
                "model": model,
                "suggested_question_type": str(candidate.get("suggested_question_type") or model).strip() or model,
                "source_unit_id": str(candidate.get("source_unit_id") or row.get("source_unit_id") or "").strip(),
                "tags": [str(t).strip() for t in (candidate.get("tags") or row.get("tags") or []) if str(t).strip()],
                "status": "output_draft",
            }
        )

    logger.debug(
        "output agent stage summary",
        selected_question_type=selected_qtype,
        qa_pairs_count=len(qa_rows),
        output_cards_count=len(output_cards),
        llm_cards_count=len(llm_cards),
        rewritten_count=rewritten_count,
        fallback_passthrough_count=fallback_passthrough_count,
        hint_resolution=str(profile_hint.get("resolution") or ""),
    )
    return {"output_cards": output_cards}
