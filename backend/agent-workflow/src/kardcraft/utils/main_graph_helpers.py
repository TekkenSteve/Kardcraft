"""Helpers for main graph orchestration and file-tree planning."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Mapping

from kardcraft.llm.client import chat_complete
from kardcraft.pageindex import flatten_nodes, prune_nodes
from kardcraft.utils.llm_json import safe_parse_llm_json

SOC_PRECHECK_INTENTS = {"create_cards"}
SOC_PREFLIGHT_CONFIDENCE_THRESHOLD = 0.75

FILE_TREE_PATH_ENABLED_ENV = "KARD_FILE_TREE_PATH_ENABLED"
FILE_TREE_PATH_USER_ALLOWLIST_ENV = "KARD_FILE_TREE_PATH_USERS"

SCOPE_BUDGETS: Dict[str, Dict[str, float | int]] = {
    "title_only": {
        "max_nodes_per_round": 1,
        "max_rag_calls": 2,
        "min_information_gain": 0.08,
        "consecutive_low_gain_limit": 1,
        "max_cards": 2,
    },
    "focused": {
        "max_nodes_per_round": 2,
        "max_rag_calls": 6,
        "min_information_gain": 0.05,
        "consecutive_low_gain_limit": 2,
        "max_cards": 8,
    },
    "full_doc": {
        "max_nodes_per_round": 3,
        "max_rag_calls": 10,
        "min_information_gain": 0.03,
        "consecutive_low_gain_limit": 3,
        "max_cards": 16,
    },
}
VALID_QUERY_SCOPES = {"title_only", "focused", "full_doc"}


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text


def parse_bool_env(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "off", "no", ""}


def is_file_tree_path_enabled(user_id: str | None) -> bool:
    if not parse_bool_env(os.getenv(FILE_TREE_PATH_ENABLED_ENV), default=True):
        return False
    allowlist = [x.strip() for x in str(os.getenv(FILE_TREE_PATH_USER_ALLOWLIST_ENV) or "").split(",") if x.strip()]
    if not allowlist:
        return True
    return str(user_id or "").strip() in set(allowlist)


async def determine_query_scope(user_input: str, *, has_files: bool = False) -> str:
    prompt = (
        "Classify the query scope for flashcard generation.\n"
        "Return JSON only: {\"query_scope\":\"title_only|focused|full_doc\",\"explicit_title_only\":true|false}.\n"
        "Rules:\n"
        "- title_only: user explicitly asks for cards ONLY about document title/topic metadata\n"
        "- focused: user wants a chapter/section/part/topic subset\n"
        "- full_doc: user asks for whole document coverage"
    )
    response = await chat_complete(
        intent="extract",
        temperature=0.0,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": str(user_input or "")},
        ],
    )
    content = ""
    if response and getattr(response, "choices", None):
        msg = response.choices[0].message
        content = str(getattr(msg, "content", "") or "")
    parsed = safe_parse_llm_json(content, default={})
    scope = ""
    if isinstance(parsed, dict):
        scope = str(parsed.get("query_scope") or "").strip().lower()
    if scope not in VALID_QUERY_SCOPES:
        raise ValueError("query_scope_classification_failed")

    # File-driven flows must be content-grounded by default.
    # `title_only` is allowed only when caller explicitly sets state.query_scope.
    if has_files and scope == "title_only":
        scope = "focused"
    return scope


def scope_budget(scope: str) -> Dict[str, Any]:
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope not in VALID_QUERY_SCOPES:
        raise ValueError("invalid_query_scope")
    base = SCOPE_BUDGETS[normalized_scope]
    return {
        "max_nodes_per_round": int(base["max_nodes_per_round"]),
        "max_rag_calls": int(base["max_rag_calls"]),
        "min_information_gain": float(base["min_information_gain"]),
        "consecutive_low_gain_limit": int(base["consecutive_low_gain_limit"]),
        "max_cards": int(base["max_cards"]),
    }


def query_token_set(value: str) -> set[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", normalize_text(value))
    return {token for token in tokens if len(token) > 1}


def score_candidate_node(node: Dict[str, Any], query_tokens: set[str], scope: str) -> float:
    title = str(node.get("title") or "")
    summary = str(node.get("summary") or "")
    haystack = f"{title} {summary}".lower()
    overlap = sum(1 for token in query_tokens if token in haystack)
    depth = int(node.get("depth") or 1)
    base = 0.1 + overlap
    if scope == "title_only":
        return base + (2.0 if depth <= 1 else 0.0)
    if scope == "focused":
        return base + (1.0 if depth <= 2 else 0.0)
    return base + max(0.0, 1.5 - (depth * 0.1))


def information_gain(new_content: str, known_content: str) -> float:
    new_tokens = query_token_set(new_content)
    if not new_tokens:
        return 0.0
    known_tokens = query_token_set(known_content)
    gain_tokens = new_tokens - known_tokens
    return float(len(gain_tokens) / max(1, len(new_tokens)))


def extract_first_question(pending_questions: list[dict[str, Any]]) -> str:
    for item in pending_questions:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question_text") or "").strip()
        if text:
            return text
    return ""


def build_question_id(session_id: str, question_text: str, round_index: int) -> str:
    normalized_question = normalize_text(question_text)
    seed = f"{session_id}|{normalized_question}|{int(round_index)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"q_{digest}"


def token_set(value: str) -> set[str]:
    return {tok for tok in normalize_text(value).split(" ") if tok}


def information_gain_score(responses: dict[str, str], base_context: str) -> float:
    merged_response = " ".join(str(v).strip() for v in responses.values() if str(v).strip())
    response_tokens = token_set(merged_response)
    if not response_tokens:
        return 0.0
    base_tokens = token_set(base_context)
    new_tokens = response_tokens - base_tokens
    return float(len(new_tokens) / max(1, len(response_tokens)))


def extract_pending_question_ids(pending_questions: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in pending_questions:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id") or "").strip()
        if question_id:
            ids.add(question_id)
    return ids


def collect_asked_question_texts(existing: Any, pending_questions: list[dict[str, Any]]) -> list[str]:
    asked: list[str] = []
    if isinstance(existing, list):
        asked.extend([str(x).strip() for x in existing if str(x).strip()])
    for item in pending_questions:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question_text") or "").strip()
        if text:
            asked.append(text)
    deduped: list[str] = []
    for text in asked:
        if text not in deduped:
            deduped.append(text)
    return deduped


def normalize_clarification_responses(raw: Any) -> tuple[dict[str, str], str]:
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "clarification_responses must be an object"

    normalized: dict[str, str] = {}
    for key, value in raw.items():
        question_id = str(key or "").strip()
        if not question_id:
            return {}, "clarification_responses contains empty question id"
        if not isinstance(value, str):
            return {}, f"clarification_responses[{question_id}] must be a string"
        answer = value.strip()
        if not answer:
            return {}, f"clarification_responses[{question_id}] must be a non-empty string"
        normalized[question_id] = answer
    return normalized, ""


def validate_pending_questions_strict(pending_questions: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(pending_questions, list):
        return [], "pending_questions must be a list"
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(pending_questions):
        if not isinstance(item, dict):
            return [], f"pending_questions[{idx}] must be an object"
        question_id = str(item.get("id") or "").strip()
        question_text = str(item.get("question_text") or "").strip()
        info_type = str(item.get("info_type") or "").strip()
        required = item.get("required")
        input_type = str(item.get("input_type") or "").strip()
        options = item.get("options")
        if not question_id:
            return [], f"pending_questions[{idx}].id is required"
        if not question_text:
            return [], f"pending_questions[{idx}].question_text is required"
        if not info_type:
            return [], f"pending_questions[{idx}].info_type is required"
        if not isinstance(required, bool):
            return [], f"pending_questions[{idx}].required must be boolean"
        if input_type not in {"free_text", "single_select", "multi_select", "file_upload"}:
            return [], f"pending_questions[{idx}].input_type is invalid"
        if not isinstance(options, list):
            return [], f"pending_questions[{idx}].options must be an array"
        normalized.append(
            {
                "id": question_id,
                "question_text": question_text,
                "info_type": info_type,
                "required": required,
                "input_type": input_type,
                "options": [str(x).strip() for x in options if str(x).strip()],
            }
        )
    return normalized, ""


def normalize_pending_questions_strict(
    pending_questions: Any,
    *,
    session_id: str,
    round_index: int,
) -> list[dict[str, Any]]:
    if not isinstance(pending_questions, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in pending_questions:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            normalized.append(
                {
                    "id": build_question_id(session_id, text, round_index),
                    "question_text": text,
                    "info_type": "general",
                    "required": True,
                    "input_type": "free_text",
                    "options": [],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        question_text = str(
            item.get("question_text")
            or item.get("question")
            or item.get("text")
            or item.get("content")
            or ""
        ).strip()
        if not question_text:
            continue
        raw_id = str(item.get("id") or item.get("question_id") or "").strip()
        question_id = raw_id or build_question_id(session_id, question_text, round_index)
        info_type = str(item.get("info_type") or "general").strip() or "general"
        raw_required = item.get("required")
        if isinstance(raw_required, bool):
            required = raw_required
        elif "is_required" in item:
            required = bool(item.get("is_required"))
        else:
            required = True
        input_type = str(item.get("input_type") or "").strip().lower()
        if input_type not in {"free_text", "single_select", "multi_select", "file_upload"}:
            input_type = "free_text"
        raw_options = item.get("options")
        if not isinstance(raw_options, list):
            raw_options = item.get("suggested_answers")
        options = [str(x).strip() for x in (raw_options or []) if str(x).strip()]
        normalized.append(
            {
                "id": question_id,
                "question_text": question_text,
                "info_type": info_type,
                "required": required,
                "input_type": input_type,
                "options": options,
            }
        )
    return normalized[:2]


def should_trigger_preflight(state: Mapping[str, Any]) -> tuple[bool, str]:
    intent_type = str(state.get("intent_type") or "").strip().lower()
    if intent_type not in SOC_PRECHECK_INTENTS:
        return False, "intent_not_targeted"

    file_ids = [str(x).strip() for x in (state.get("file_ids") or []) if str(x).strip()]
    if file_ids:
        return False, "has_files"

    message_knowledge = str(state.get("message_knowledge") or "").strip()
    if message_knowledge:
        return False, "has_inline_knowledge"

    driven_mode = str(state.get("driven_mode") or "").strip().lower()
    confidence = float(state.get("classification_confidence") or 0.0)
    low_confidence = confidence < SOC_PREFLIGHT_CONFIDENCE_THRESHOLD
    topic_driven = driven_mode == "topic_driven"
    if not low_confidence and not topic_driven:
        return False, "signals_sufficient"
    return True, "topic_or_low_confidence"


async def separate_content_and_task(user_input: str) -> Dict[str, str]:
    """Split message into source content and task demand using LLM."""
    prompt = (
        "Please split the user input into JSON:\n"
        "{\"message_knowledge\": \"Knowledge material\", \"topic\": \"Task requirement\"}\n"
        "If knowledge material is missing, message_knowledge can be empty."
    )
    try:
        response = await chat_complete(
            intent="extract",
            temperature=0.0,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={})
        if not isinstance(parsed, dict):
            parsed = {}
        source = str(parsed.get("message_knowledge") or "").strip()
        topic = str(parsed.get("topic") or "").strip() or user_input
        return {"message_knowledge": source, "topic": topic}
    except Exception:
        return {"message_knowledge": user_input, "topic": user_input}


def select_candidate_nodes(
    *,
    document_trees: List[Dict[str, Any]],
    user_input: str,
    query_scope: str,
    retrieval_budget: Dict[str, Any],
) -> List[Dict[str, Any]]:
    query_tokens = query_token_set(user_input)
    include_root = query_scope == "title_only"
    ranked: List[Dict[str, Any]] = []
    for tree in document_trees:
        if not isinstance(tree, dict):
            continue
        nodes = flatten_nodes(
            file_id=str(tree.get("file_id") or ""),
            doc_name=str(tree.get("doc_name") or ""),
            doc_title=str(tree.get("title") or tree.get("doc_name") or ""),
            nodes=tree.get("nodes") or [],
            include_root=include_root,
            root=tree,
        )
        for node in nodes:
            score = score_candidate_node(node, query_tokens=query_tokens, scope=query_scope)
            ranked.append({**node, "priority": round(float(score), 4)})

    if query_scope == "title_only":
        ranked.sort(
            key=lambda item: (
                float(item.get("priority") or 0.0),
                -int(item.get("depth") or 0),
            ),
            reverse=True,
        )
    else:
        # For focused/full_doc paths, prefer deeper content nodes over metadata-like shallow roots.
        ranked.sort(
            key=lambda item: (
                float(item.get("priority") or 0.0),
                int(item.get("depth") or 0),
            ),
            reverse=True,
        )
    max_rag_calls = int(retrieval_budget.get("max_rag_calls") or 6)
    max_nodes = max(3, max_rag_calls * 3)
    max_depth = 1 if query_scope == "title_only" else (3 if query_scope == "focused" else 6)
    pruned = prune_nodes(ranked, max_nodes=max_nodes, max_depth=max_depth)
    seen: set[tuple[str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for item in pruned:
        key = (str(item.get("file_id") or ""), str(item.get("node_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
