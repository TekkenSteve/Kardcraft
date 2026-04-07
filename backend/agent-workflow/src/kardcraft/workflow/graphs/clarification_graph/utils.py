"""Utility helpers for clarification graph."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Dict

from kardcraft.llm.client import chat_complete
from kardcraft.utils.llm_json import safe_parse_llm_json

DEFAULT_MISSING = ["learning_goal", "scope", "source_material"]
MAX_QUESTIONS_PER_ROUND = 2
DUPLICATE_SIMILARITY_THRESHOLD = 0.9


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text


def cosine_similarity(left: str, right: str) -> float:
    left_tokens = [tok for tok in normalize_text(left).split(" ") if tok]
    right_tokens = [tok for tok in normalize_text(right).split(" ") if tok]
    if not left_tokens or not right_tokens:
        return 0.0

    left_counter = Counter(left_tokens)
    right_counter = Counter(right_tokens)
    common = set(left_counter) & set(right_counter)
    dot = sum(left_counter[token] * right_counter[token] for token in common)
    left_norm = math.sqrt(sum(v * v for v in left_counter.values()))
    right_norm = math.sqrt(sum(v * v for v in right_counter.values()))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return float(dot / (left_norm * right_norm))


def build_question_id(session_id: str, question_text: str, round_index: int) -> str:
    normalized_question = normalize_text(question_text)
    seed = f"{session_id}|{normalized_question}|{int(round_index)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"q_{digest}"


def extract_question_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    for key in ("question_text", "question", "text", "content", "message", "title"):
        candidate = str(item.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def normalize_pending_questions(
    raw_questions: Any,
    *,
    session_id: str,
    round_index: int,
    asked_questions: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_questions, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen_texts: list[str] = list(asked_questions)

    for item in raw_questions:
        question_text = extract_question_text(item)
        if not question_text:
            continue

        is_duplicate = False
        for historical in seen_texts:
            if cosine_similarity(question_text, historical) > DUPLICATE_SIMILARITY_THRESHOLD:
                is_duplicate = True
                break
        if is_duplicate:
            continue

        info_type = "general"
        required = True
        input_type = "free_text"
        options: list[str] = []

        if isinstance(item, dict):
            info_type = str(item.get("info_type") or "general").strip() or "general"
            raw_required = item.get("required")
            if isinstance(raw_required, bool):
                required = raw_required
            elif "is_required" in item:
                required = bool(item.get("is_required"))

            input_type_value = str(item.get("input_type") or "").strip().lower()
            if input_type_value in {"free_text", "single_select", "multi_select", "file_upload"}:
                input_type = input_type_value

            raw_options = item.get("options")
            if not isinstance(raw_options, list):
                raw_options = item.get("suggested_answers")
            if isinstance(raw_options, list):
                options = [str(x).strip() for x in raw_options if str(x).strip()]

        normalized.append(
            {
                "id": build_question_id(session_id, question_text, round_index),
                "question_text": question_text,
                "info_type": info_type,
                "required": required,
                "input_type": input_type,
                "options": options,
            }
        )
        seen_texts.append(question_text)
        if len(normalized) >= MAX_QUESTIONS_PER_ROUND:
            break

    return normalized


async def assess_information_sufficiency(
    *,
    user_input: str,
    message_knowledge: str,
    file_count: int,
) -> Dict[str, Any]:
    system_prompt = (
        "You are a multilingual clarification judge. "
        "Decide whether input is sufficient for accurate flashcard generation. "
        "Return JSON only: "
        "{\"is_sufficient\": bool, \"missing_info\": [string], \"reason\": string}."
    )
    user_prompt = (
        f"user_input:\n{user_input}\n\n"
        f"message_knowledge:\n{message_knowledge}\n\n"
        f"file_count:{file_count}\n"
    )

    try:
        response = await chat_complete(
            intent="classify",
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
            default={
                "is_sufficient": False,
                "missing_info": list(DEFAULT_MISSING),
                "reason": "model_parse_fallback",
            },
        )
        if not isinstance(parsed, dict):
            parsed = {}
        is_sufficient = bool(parsed.get("is_sufficient"))
        missing_info = [str(x).strip() for x in (parsed.get("missing_info") or []) if str(x).strip()]
        reason = str(parsed.get("reason") or "model_decision")
        return {
            "is_sufficient": is_sufficient,
            "missing_info": [] if is_sufficient else (missing_info or list(DEFAULT_MISSING)),
            "reason": reason,
        }
    except Exception:
        return {
            "is_sufficient": False,
            "missing_info": list(DEFAULT_MISSING),
            "reason": "model_unavailable",
        }
