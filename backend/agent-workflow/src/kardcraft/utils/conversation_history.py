"""Conversation history normalization and optional prompt fusion helpers."""

from __future__ import annotations

from typing import Any


def normalize_conversation_history(
    raw: Any,
    max_messages: int = 24,
) -> list[dict[str, str]]:
    """Normalize history payload into [{role, content}] shape."""
    if not isinstance(raw, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant", "system"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})

    if len(normalized) > max_messages:
        return normalized[-max_messages:]
    return normalized


def _build_user_input_with_history(
    current_query: str,
    conversation_history: list[dict[str, str]],
    max_turns: int = 8,
) -> str:
    """Build a merged prompt text from recent history + current query."""
    query = str(current_query or "").strip()
    if not conversation_history:
        return query

    max_messages = max_turns * 2
    recent = (
        conversation_history[-max_messages:]
        if len(conversation_history) > max_messages
        else conversation_history
    )

    lines = []
    for msg in recent:
        role = msg.get("role", "")
        content = msg.get("content", "").strip()
        if not content:
            continue
        prefix = "User" if role == "user" else "Assistant" if role == "assistant" else "System"
        lines.append(f"{prefix}: {content}")

    if not lines:
        return query

    history_block = "\n".join(lines)
    return (
        "[Recent conversation context]\n"
        f"{history_block}\n\n"
        "[Current user request]\n"
        f"{query}"
    ).strip()

