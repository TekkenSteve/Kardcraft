"""Utility functions for syllabus outline extraction."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from kardcraft.utils.llm_json import safe_parse_llm_json

DIFFICULTY_VALUES = {"basic", "intermediate", "advanced"}


def _coerce_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def build_outline_source_chunks(
    user_input: str,
    subject_domain: str,
    user_knowledge: str,
    retrieved_context: List[Dict[str, Any]],
    max_chunk_chars: int = 6000,
    overlap_chars: int = 400,
) -> List[Dict[str, Any]]:
    """Build overlapping chunks for map-reduce style outline extraction."""
    normalized_parts: List[str] = []

    if user_input:
        normalized_parts.append(f"User Input:\n{user_input.strip()}")
    if subject_domain:
        normalized_parts.append(f"Subject Domain:\n{subject_domain.strip()}")
    if user_knowledge:
        normalized_parts.append(f"Primary Knowledge:\n{user_knowledge.strip()}")

    for index, ctx in enumerate(retrieved_context):
        content = (ctx.get("content") or "").strip()
        if not content:
            continue
        source = ctx.get("store", "unknown")
        normalized_parts.append(f"Context {index + 1} ({source}):\n{content}")

    full_text = "\n\n".join(normalized_parts).strip()
    if not full_text:
        return []

    if len(full_text) <= max_chunk_chars:
        return [{"chunk_id": "chunk_1", "content": full_text}]

    chunks: List[Dict[str, Any]] = []
    start = 0
    chunk_index = 1
    step = max(1, max_chunk_chars - overlap_chars)
    while start < len(full_text):
        end = min(start + max_chunk_chars, len(full_text))
        chunks.append(
            {
                "chunk_id": f"chunk_{chunk_index}",
                "content": full_text[start:end],
            }
        )
        if end >= len(full_text):
            break
        start += step
        chunk_index += 1

    return chunks


def _normalize_prerequisites(
    prerequisites: Any,
    unit_ids: List[str],
    unit_titles: List[str],
) -> List[str]:
    prereq_list = []
    for item in _coerce_list(prerequisites):
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate:
            continue
        if candidate in unit_ids:
            prereq_list.append(candidate)
            continue
        if candidate in unit_titles:
            index = unit_titles.index(candidate)
            prereq_list.append(unit_ids[index])
    # Keep order while removing duplicates.
    return list(dict.fromkeys(prereq_list))


def normalize_learning_units(
    units: List[Dict[str, Any]],
    max_units: int = 12,
) -> List[Dict[str, Any]]:
    """Normalize unit schema and enforce predictable fields."""
    normalized: List[Dict[str, Any]] = []
    for index, unit in enumerate(units[:max_units]):
        title = str(unit.get("title") or "").strip()
        if not title:
            continue
        unit_id = str(unit.get("id") or f"unit_{index + 1}").strip() or f"unit_{index + 1}"
        difficulty = str(unit.get("difficulty") or "intermediate").lower().strip()
        if difficulty not in DIFFICULTY_VALUES:
            difficulty = "intermediate"

        key_concepts = []
        for concept in _coerce_list(unit.get("key_concepts", unit.get("concepts", []))):
            if isinstance(concept, str) and concept.strip():
                key_concepts.append(concept.strip())

        estimated_time = unit.get("estimated_time")
        if not isinstance(estimated_time, int):
            estimated_time = None

        normalized.append(
            {
                "id": unit_id,
                "title": title,
                "content_summary": str(
                    unit.get("content_summary")
                    or unit.get("description")
                    or ""
                ).strip(),
                "key_concepts": key_concepts,
                "difficulty": difficulty,
                "estimated_time": estimated_time,
                "prerequisites": unit.get("prerequisites", []),
                "status": "draft",
            }
        )

    unit_ids = [unit["id"] for unit in normalized]
    unit_titles = [unit["title"] for unit in normalized]
    for unit in normalized:
        unit["prerequisites"] = _normalize_prerequisites(
            unit.get("prerequisites", []),
            unit_ids=unit_ids,
            unit_titles=unit_titles,
        )
        if unit["id"] in unit["prerequisites"]:
            unit["prerequisites"] = [
                prerequisite
                for prerequisite in unit["prerequisites"]
                if prerequisite != unit["id"]
            ]

    return normalized


def parse_learning_units_from_response(
    response: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Parse learning units from LLM response text."""
    parsed = safe_parse_llm_json(response, default={})
    units_raw: List[Dict[str, Any]] = []

    if isinstance(parsed, list):
        units_raw = [item for item in parsed if isinstance(item, dict)]
    elif isinstance(parsed, dict):
        for key in ("learning_units", "units", "chapters", "outline"):
            value = parsed.get(key)
            if isinstance(value, list):
                units_raw = [item for item in value if isinstance(item, dict)]
                break
        if not units_raw and {"id", "title"} & set(parsed.keys()):
            units_raw = [parsed]

    normalized = normalize_learning_units(units_raw)
    metadata = {
        "count": len(normalized),
        "raw_preview": response[:500] if response else "",
    }
    return normalized, metadata
