"""Canonical LLM usage event payload contract."""

from __future__ import annotations

from typing import Literal, TypedDict

LLM_USAGE_SCHEMA_VERSION = "1"


class LLMUsageEventPayload(TypedDict):
    schema_version: Literal["1"]
    idempotency_key: str
    task_id: str
    workflow_id: str
    session_id: str
    user_id: str
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
