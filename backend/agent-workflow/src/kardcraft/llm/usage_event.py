"""Canonical LLM usage event payload contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, NotRequired, TypedDict


class LLMUsageRecord(TypedDict):
    idempotency_key: str
    operation: str
    intent: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    cache_cost_usd: float
    total_cost_usd: float
    estimated: bool
    source: str
    external_request_id: str
    created_at: str
    metadata: NotRequired[dict[str, Any]]


class LLMUsageRecordedEventPayload(TypedDict):
    event_id: str
    occurred_at: str
    task_id: str
    workflow_id: str
    session_id: str
    user_id: str
    usage: LLMUsageRecord


def validate_usage_record(payload: dict[str, Any]) -> tuple[bool, str]:
    required_fields = (
        "idempotency_key",
        "operation",
        "intent",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
        "input_cost_usd",
        "output_cost_usd",
        "cache_cost_usd",
        "total_cost_usd",
        "estimated",
        "source",
        "external_request_id",
        "created_at",
    )
    for field in required_fields:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return False, f"missing_{field}"
    try:
        if float(payload.get("total_cost_usd", 0)) <= 0:
            return False, "missing_authoritative_cost"
    except Exception:
        return False, "invalid_total_cost_usd"
    if not _is_iso8601_with_timezone(payload.get("created_at")):
        return False, "invalid_created_at"
    return True, ""


def validate_usage_recorded_event(payload: dict[str, Any]) -> tuple[bool, str]:
    required_top = ("event_id", "occurred_at", "task_id", "workflow_id", "session_id", "user_id", "usage")
    for field in required_top:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return False, f"missing_{field}"
    if not _is_iso8601_with_timezone(payload.get("occurred_at")):
        return False, "invalid_occurred_at"
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return False, "invalid_usage_type"
    return validate_usage_record(usage)


def _is_iso8601_with_timezone(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None
