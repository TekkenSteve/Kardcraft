"""Kardcraft LLM facade and model discovery."""

from .client import acompletion, acompletion_stream, aembedding, arerank, chat_complete
from .discovery import (
    detect_provider,
    get_available_providers,
    get_completion_config,
    get_temperature,
    get_model,
    get_embed_model,
    get_rerank_model,
    reset_cache,
)
from .context import LLMRuntimeContext, get_runtime_context, reset_runtime_context, set_runtime_context
from .config import configure_dspy_lm
from .usage_event import LLMUsageRecord, LLMUsageRecordedEventPayload

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
