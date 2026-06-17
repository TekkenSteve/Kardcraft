"""Kardcraft LLM facade and model discovery."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .context import LLMRuntimeContext, get_runtime_context, reset_runtime_context, set_runtime_context
from .usage_event import LLMUsageRecord, LLMUsageRecordedEventPayload

_LAZY_EXPORTS = {
    "acompletion": (".client", "acompletion"),
    "acompletion_stream": (".client", "acompletion_stream"),
    "aembedding": (".client", "aembedding"),
    "arerank": (".client", "arerank"),
    "chat_complete": (".client", "chat_complete"),
    "configure_dspy_lm": (".config", "configure_dspy_lm"),
    "detect_provider": (".discovery", "detect_provider"),
    "get_available_providers": (".discovery", "get_available_providers"),
    "get_completion_config": (".discovery", "get_completion_config"),
    "get_temperature": (".discovery", "get_temperature"),
    "get_model": (".discovery", "get_model"),
    "get_embed_model": (".discovery", "get_embed_model"),
    "get_rerank_model": (".discovery", "get_rerank_model"),
    "reset_cache": (".discovery", "reset_cache"),
}

__all__ = [
    "acompletion",
    "acompletion_stream",
    "chat_complete",
    "aembedding",
    "arerank",
    "LLMRuntimeContext",
    "LLMUsageRecord",
    "LLMUsageRecordedEventPayload",
    "set_runtime_context",
    "reset_runtime_context",
    "get_runtime_context",
    "detect_provider",
    "get_available_providers",
    "get_completion_config",
    "get_temperature",
    "get_model",
    "get_embed_model",
    "get_rerank_model",
    "reset_cache",
    "configure_dspy_lm",
]


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
