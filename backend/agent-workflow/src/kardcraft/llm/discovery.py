"""Kardcraft LLM discovery - routing and model selection only."""

import os
from typing import Any, Dict, List, Optional
from .env_loader import bootstrap_llm_env

DEFAULT_PROVIDER = "openai"

# Provider 注册表（顺序即检测优先级）
PROVIDERS = [
    {"name": "openai", "api_key_env": "OPENAI_API_KEY", "model_env": "OPENAI_MODEL"},
    {"name": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "model_env": "ANTHROPIC_MODEL"},
    {"name": "google", "api_key_env": "GOOGLE_API_KEY", "model_env": "GOOGLE_MODEL"},
    {"name": "groq", "api_key_env": "GROQ_API_KEY", "model_env": "GROQ_MODEL"},
    {"name": "deepseek", "api_key_env": "DEEPSEEK_API_KEY", "model_env": "DEEPSEEK_MODEL"},
    {"name": "cohere", "api_key_env": "COHERE_API_KEY", "model_env": None},
    {"name": "ollama", "api_key_env": "OLLAMA_API_KEY", "model_env": "OLLAMA_MODEL"},
]
PROVIDER_BY_NAME = {p["name"]: p for p in PROVIDERS}

# 意图 → 模型映射
INTENT_MODELS = {
    # ===== 文本生成类 =====
    "chat": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "google": "gemini/gemini-1.5-flash-002",
        "groq": "groq/llama-3.1-70b-versatile",
        "deepseek": "deepseek/deepseek-chat",
        "ollama": "llama3.1",
    },
    "think": {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "deepseek": "deepseek-chat",
    },
    "reasoning": {
        "openai": "o1-mini",
        "anthropic": "claude-3-5-sonnet-20241022",
        "deepseek": "deepseek-chat",
    },
    "summarize": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "google": "gemini/gemini-1.5-flash-002",
    },
    "creative": {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
    },
    # ===== Classification/Recognition Category =====
    "classify": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "groq": "groq/llama-3.1-70b-versatile",
    },
    "extract": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-20241022",
    },
    "query_understand": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "groq": "groq/llama-3.1-70b-versatile",
    },
    "query_rewrite": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "groq": "groq/llama-3.1-70b-versatile",
    },
    # ===== 检索/搜索类 =====
    "search": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-20241022",
        "perplexity": "perplexity/llama-3.1-sonar-small-128k-online",
        "groq": "groq/llama-3.1-70b-versatile",
    },
    "retrieve": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
    },
    # ===== 工具/代理类 =====
    "tool_call": {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
    },
    "agent": {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
    },
    # ===== 多模态类 =====
    "vision": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
    },
    # ===== Special Scenarios =====
    "fast": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "groq": "groq/llama-3.1-70b-versatile",
    },
    "long_context": {
        "openai": "gpt-4o-32k",
        "anthropic": "claude-3-5-sonnet-20241022",
        "google": "gemini-1.5-pro",
    },
}

# Intent → Default temperature (higher for generative type, lower for judgment type)
INTENT_TEMPERATURES = {
    "chat": 0.4,
    "think": 0.3,
    "reasoning": 0.2,
    "summarize": 0.2,
    "creative": 0.8,
    "classify": 0.0,
    "extract": 0.0,
    "query_understand": 0.0,
    "query_rewrite": 0.0,
    "search": 0.2,
    "retrieve": 0.1,
    "tool_call": 0.1,
    "agent": 0.4,
    "vision": 0.2,
    "fast": 0.3,
    "long_context": 0.2,
}

# 嵌入模型
EMBED_MODELS = {
    "openai": "text-embedding-3-small",
    "cohere": "embed-english-v3.0",
    "ollama": "nomic-embed-text",
}

# 缓存
_cached_provider: Optional[str] = None
_env_bootstrapped = False
RERANK_MODEL_BY_KEY = {
    "COHERE_API_KEY": "cohere/rerank-english-v3.0",
    "VOYAGE_API_KEY": "voyageai/rerank-2",
}


def _ensure_env_bootstrapped() -> None:
    global _env_bootstrapped
    if _env_bootstrapped:
        return
    bootstrap_llm_env()
    _env_bootstrapped = True


def _default_chat_model() -> str:
    chat_map = INTENT_MODELS.get("chat", {})
    return str(chat_map.get(DEFAULT_PROVIDER, "gpt-4o-mini"))


def _default_embed_model() -> str:
    return str(EMBED_MODELS.get(DEFAULT_PROVIDER, "text-embedding-3-small"))


def _resolve_model_for_provider(provider: str, intent: str) -> str:
    intent_map = INTENT_MODELS.get(intent, INTENT_MODELS["chat"])
    provider_spec = PROVIDER_BY_NAME.get(provider, {})
    provider_model_env = provider_spec.get("model_env")
    if provider_model_env:
        provider_model = os.getenv(provider_model_env)
        if provider_model:
            return provider_model
    return intent_map.get(provider, _default_chat_model())


def detect_provider() -> str:
    """
    自动检测可用 provider，按优先级返回第一个

    Returns:
        provider 名称: "openai" / "anthropic" / "groq" / ...
    """
    global _cached_provider
    _ensure_env_bootstrapped()
    if _cached_provider:
        return _cached_provider

    for spec in PROVIDERS:
        if os.getenv(spec["api_key_env"]):
            _cached_provider = spec["name"]
            return spec["name"]

    return DEFAULT_PROVIDER


def get_available_providers() -> List[str]:
    """
    获取所有可用 providers

    Returns:
        可用 provider 列表
    """
    _ensure_env_bootstrapped()
    providers = [spec["name"] for spec in PROVIDERS if os.getenv(spec["api_key_env"])]
    return providers if providers else [DEFAULT_PROVIDER]


def get_model(intent: str = "chat", temperature: Optional[float] = None) -> tuple[str, float]:
    """
    根据意图获取最优模型

    Args:
        intent: 意图类型 (chat, think, reasoning, summarize, creative,
                 classify, extract, search, retrieve, tool_call, agent,
                 vision, fast, long_context)

    Returns:
        (模型名称, temperature)
    """
    provider = detect_provider()
    model_name = _resolve_model_for_provider(provider, intent)
    return model_name, get_temperature(intent, temperature)


def get_temperature(intent: str = "chat", override: Optional[float] = None) -> float:
    """
    获取推荐 temperature，支持调用方覆盖。

    Args:
        intent: 任务意图
        override: 可选覆盖值；会被夹紧到 [0.0, 2.0]

    Returns:
        temperature 数值
    """
    if override is not None:
        try:
            return min(2.0, max(0.0, float(override)))
        except Exception:
            pass

    return float(INTENT_TEMPERATURES.get(intent, 0.3))


def get_completion_config(
    intent: str = "chat",
    temperature: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    生成 completion 调用配置（由 llm client facade 消费）。
    """
    model_name, resolved_temperature = get_model(intent, temperature)
    sanitized_overrides = {k: v for k, v in overrides.items() if v is not None}
    return {"model": model_name, "temperature": resolved_temperature, **sanitized_overrides}


def get_embed_model() -> str:
    """
    获取嵌入模型

    Returns:
        嵌入模型名称
    """
    provider = detect_provider()
    return EMBED_MODELS.get(provider, _default_embed_model())


def get_rerank_model() -> Optional[str]:
    """
    获取重排模型

    Returns:
        重排模型名称，如果没有配置则返回 None
    """
    _ensure_env_bootstrapped()
    for env_key, model_name in RERANK_MODEL_BY_KEY.items():
        if os.getenv(env_key):
            return model_name
    return None


def reset_cache():
    """重置 provider 缓存"""
    global _cached_provider, _env_bootstrapped
    _cached_provider = None
    _env_bootstrapped = False
