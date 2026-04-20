"""Unified runtime LLM client facade."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional, TypeVar

import litellm

from .context import LLMRuntimeContext, get_runtime_context
from .discovery import detect_provider, get_completion_config, get_embed_model, get_rerank_model
from .usage_event import LLMUsageRecord

T = TypeVar("T")

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_RETRY_DELAY_SECONDS = 0.8
USD_QUANT = Decimal("0.00000001")


class LLMClientError(RuntimeError):
    """Normalized LLM boundary error."""


class LLMContextError(RuntimeError):
    """Missing runtime context for LLM invocation."""


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _quantize_usd(value: Any, field_name: str) -> float:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise LLMClientError(f"invalid {field_name}: {value!r}") from exc
    if dec.is_nan() or dec.is_infinite() or dec < 0:
        raise LLMClientError(f"invalid {field_name}: {value!r}")
    return float(dec.quantize(USD_QUANT, rounding=ROUND_HALF_UP))


def _read_usage_field(usage: Any, key: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return _coerce_int(usage.get(key))
    return _coerce_int(getattr(usage, key, 0))


def _resolve_provider(explicit_provider: Optional[str]) -> str:
    provider = str(explicit_provider or "").strip().lower()
    if provider:
        return provider
    return detect_provider()


def _normalize_error(operation: str, model_name: str, err: Exception) -> LLMClientError:
    provider = _resolve_provider(None)
    return LLMClientError(
        f"LLM {operation} failed provider={provider} model={model_name or '<unknown>'}: {type(err).__name__}: {err}"
    )


def _extract_request_id(response: Any) -> str:
    return str(getattr(response, "id", "") or "").strip()


def _read_usage_float(usage: Any, key: str) -> float:
    if usage is None:
        return 0.0
    if isinstance(usage, dict):
        return _coerce_float(usage.get(key), 0.0)
    return _coerce_float(getattr(usage, key, 0.0), 0.0)


def _extract_model_name(response: Any, fallback_model_name: str) -> str:
    response_model = str(getattr(response, "model", "") or "").strip()
    if response_model:
        return response_model
    model_name = str(fallback_model_name or "").strip()
    if model_name:
        return model_name
    raise LLMClientError("LLM response missing model name; cannot emit usage event")


def _extract_total_cost_usd(response: Any, usage: Any) -> float:
    candidate_keys = ("total_cost_usd", "total_cost", "response_cost", "cost")
    for key in candidate_keys:
        value = _read_usage_float(usage, key)
        if value > 0:
            return value

    hidden_params = getattr(response, "_hidden_params", None)
    if isinstance(hidden_params, dict):
        value = _coerce_float(hidden_params.get("response_cost"), 0.0)
        if value > 0:
            return value

    headers = getattr(response, "_response_headers", None)
    if isinstance(headers, dict):
        value = _coerce_float(headers.get("x-litellm-response-cost"), 0.0)
        if value > 0:
            return value

    raise LLMClientError(
        "LLM response missing authoritative cost field; ensure requests are routed through LiteLLM Proxy spend tracking"
    )


def _extract_proxy_markers(response: Any) -> dict[str, str]:
    markers: dict[str, str] = {}
    hidden_params = getattr(response, "_hidden_params", None)
    if isinstance(hidden_params, dict):
        _copy_non_empty(hidden_params, markers, "response_cost", "hidden_response_cost")
        _copy_non_empty(hidden_params, markers, "request_id", "hidden_request_id")
        _copy_non_empty(hidden_params, markers, "custom_llm_provider", "hidden_provider")

    headers = getattr(response, "_response_headers", None)
    if isinstance(headers, dict):
        _copy_non_empty(headers, markers, "x-litellm-response-cost", "header_response_cost")
        _copy_non_empty(headers, markers, "x-litellm-model-id", "header_model_id")
        _copy_non_empty(headers, markers, "x-request-id", "header_request_id")
    return markers


def _extract_observability_metadata(response: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    hidden_params = getattr(response, "_hidden_params", None)
    if isinstance(hidden_params, dict):
        _copy_non_empty(hidden_params, metadata, "trace_id", "langfuse_trace_id")
        _copy_non_empty(hidden_params, metadata, "observation_id", "langfuse_observation_id")
        _copy_non_empty(hidden_params, metadata, "generation_id", "langfuse_generation_id")
        _copy_non_empty(hidden_params, metadata, "request_id", "litellm_request_id")
        _copy_non_empty(hidden_params, metadata, "custom_llm_provider", "litellm_provider")

    headers = getattr(response, "_response_headers", None)
    if isinstance(headers, dict):
        _copy_non_empty(headers, metadata, "x-request-id", "response_header_request_id")
        _copy_non_empty(headers, metadata, "x-litellm-model-id", "litellm_model_id")

    return metadata


def _copy_non_empty(source: dict[str, Any], target: dict[str, Any], key: str, target_key: str) -> None:
    value = source.get(key)
    text = str(value or "").strip()
    if text:
        target[target_key] = text


def _require_runtime_context() -> LLMRuntimeContext:
    ctx = get_runtime_context()
    if ctx is None:
        raise LLMContextError("LLM runtime context missing: initialize context before invoking llm client")
    if not str(ctx.task_id or "").strip():
        raise LLMContextError("LLM runtime context missing required field: task_id")
    if not str(ctx.session_id or "").strip():
        raise LLMContextError("LLM runtime context missing required field: session_id")
    if not str(ctx.user_id or "").strip():
        raise LLMContextError("LLM runtime context missing required field: user_id")
    if ctx.usage_emitter is None:
        raise LLMContextError("LLM usage emitter missing in runtime context")
    return ctx


async def _emit_usage(
    *,
    operation: str,
    intent: str,
    model_name: str,
    response: Any,
) -> None:
    ctx = _require_runtime_context()
    usage = getattr(response, "usage", None)
    if usage is None:
        raise LLMClientError(
            "LLM response missing usage; cannot emit usage analytics without provider usage payload"
        )

    prompt_tokens = _read_usage_field(usage, "prompt_tokens")
    completion_tokens = _read_usage_field(usage, "completion_tokens")
    cache_read_tokens = _read_usage_field(usage, "cache_read_input_tokens")
    cache_write_tokens = _read_usage_field(usage, "cache_creation_input_tokens")
    total_tokens = _read_usage_field(usage, "total_tokens")
    estimated = _coerce_int(_read_usage_field(usage, "estimated")) > 0
    source = "litellm_proxy"

    if total_tokens == 0 and usage is not None:
        total_tokens = prompt_tokens + completion_tokens

    if total_tokens <= 0:
        raise LLMClientError(
            "LLM usage payload missing token counts; cannot emit usage analytics without prompt/completion tokens"
        )
    proxy_markers = _extract_proxy_markers(response)
    if not proxy_markers:
        raise LLMClientError(
            "LLM response missing LiteLLM Proxy markers; usage analytics requires LiteLLM Proxy authority"
        )

    external_request_id = _extract_request_id(response)
    if not external_request_id:
        external_request_id = uuid.uuid4().hex

    now_iso = datetime.now(timezone.utc).isoformat()
    provider = _resolve_provider(getattr(response, "provider", None))
    model_value = _extract_model_name(response, model_name)
    input_cost_usd = _quantize_usd(_read_usage_float(usage, "input_cost_usd"), "input_cost_usd")
    output_cost_usd = _quantize_usd(_read_usage_float(usage, "output_cost_usd"), "output_cost_usd")
    cache_cost_usd = _quantize_usd(_read_usage_float(usage, "cache_cost_usd"), "cache_cost_usd")
    total_cost_usd = _quantize_usd(_extract_total_cost_usd(response, usage), "total_cost_usd")
    if input_cost_usd + output_cost_usd + cache_cost_usd > total_cost_usd and total_cost_usd > 0:
        raise LLMClientError(
            "LLM usage cost payload inconsistent: component costs exceed total cost"
        )
    payload: LLMUsageRecord = {
        "idempotency_key": f"{ctx.task_id}:{external_request_id}",
        "operation": operation,
        "intent": intent,
        "provider": provider,
        "model": model_value,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": total_tokens,
        "input_cost_usd": input_cost_usd,
        "output_cost_usd": output_cost_usd,
        "cache_cost_usd": cache_cost_usd,
        "total_cost_usd": total_cost_usd,
        "estimated": estimated,
        "source": source,
        "external_request_id": external_request_id,
        "created_at": now_iso,
    }
    observability_metadata = _extract_observability_metadata(response)
    observability_metadata["proxy_markers"] = proxy_markers
    if observability_metadata:
        payload["metadata"] = observability_metadata
    await ctx.usage_emitter(payload)


async def _call_with_policy(
    *,
    operation: str,
    model_name: str,
    timeout_seconds: float,
    max_attempts: int,
    retry_delay_seconds: float,
    fn: Callable[[], Awaitable[T]],
) -> T:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be >= 1")

    attempt = 0
    while True:
        attempt += 1
        try:
            return await asyncio.wait_for(fn(), timeout=timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if attempt >= max_attempts:
                raise _normalize_error(operation, model_name, err) from err
            await asyncio.sleep(retry_delay_seconds)


async def acompletion(
    *,
    messages: list[dict[str, Any]],
    intent: str = "chat",
    temperature: Optional[float] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    **overrides: Any,
) -> Any:
    _require_runtime_context()
    cfg = get_completion_config(intent=intent, temperature=temperature, **overrides)
    model_name = str(cfg.get("model") or "").strip()

    async def _invoke() -> Any:
        return await litellm.acompletion(**cfg, messages=messages)

    response = await _call_with_policy(
        operation="acompletion",
        model_name=model_name,
        timeout_seconds=_coerce_float(timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
        max_attempts=max_attempts,
        retry_delay_seconds=_coerce_float(retry_delay_seconds, DEFAULT_RETRY_DELAY_SECONDS),
        fn=_invoke,
    )
    await _emit_usage(
        operation="acompletion",
        intent=intent,
        model_name=model_name,
        response=response,
    )
    return response


async def acompletion_stream(
    *,
    messages: list[dict[str, Any]],
    intent: str = "chat",
    temperature: Optional[float] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    **overrides: Any,
) -> AsyncIterator[Any]:
    _require_runtime_context()
    stream_options = dict(overrides.get("stream_options") or {})
    stream_options.setdefault("include_usage", True)
    cfg = get_completion_config(
        intent=intent,
        temperature=temperature,
        stream=True,
        stream_options=stream_options,
        **{k: v for k, v in overrides.items() if k != "stream_options"},
    )
    model_name = str(cfg.get("model") or "").strip()

    async def _invoke() -> Any:
        return await litellm.acompletion(**cfg, messages=messages)

    stream = await _call_with_policy(
        operation="acompletion_stream",
        model_name=model_name,
        timeout_seconds=_coerce_float(timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
        max_attempts=max_attempts,
        retry_delay_seconds=_coerce_float(retry_delay_seconds, DEFAULT_RETRY_DELAY_SECONDS),
        fn=_invoke,
    )

    async def _iterate() -> AsyncIterator[Any]:
        last_chunk = None
        async for chunk in stream:
            last_chunk = chunk
            yield chunk

        if last_chunk is None:
            raise LLMClientError(f"LLM acompletion_stream returned no chunks for model={model_name}")

        await _emit_usage(
            operation="acompletion_stream",
            intent=intent,
            model_name=model_name,
            response=last_chunk,
        )

    return _iterate()


async def chat_complete(
    *,
    messages: list[dict[str, Any]],
    intent: str = "chat",
    temperature: Optional[float] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    **overrides: Any,
) -> Any:
    return await acompletion(
        messages=messages,
        intent=intent,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        **overrides,
    )


async def aembedding(
    *,
    input: str | Iterable[str],
    model: Optional[str] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    **overrides: Any,
) -> Any:
    _require_runtime_context()
    model_name = str(model or get_embed_model()).strip()

    async def _invoke() -> Any:
        return await litellm.aembedding(model=model_name, input=input, **overrides)

    response = await _call_with_policy(
        operation="aembedding",
        model_name=model_name,
        timeout_seconds=_coerce_float(timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
        max_attempts=max_attempts,
        retry_delay_seconds=_coerce_float(retry_delay_seconds, DEFAULT_RETRY_DELAY_SECONDS),
        fn=_invoke,
    )
    await _emit_usage(
        operation="aembedding",
        intent="embedding",
        model_name=model_name,
        response=response,
    )
    return response


async def arerank(
    *,
    query: str,
    documents: list[str],
    model: Optional[str] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    **overrides: Any,
) -> Any:
    _require_runtime_context()
    model_name = str(model or get_rerank_model() or "").strip()
    if not model_name:
        raise LLMClientError("Rerank model is not configured")

    async def _invoke() -> Any:
        return await litellm.arerank(model=model_name, query=query, documents=documents, **overrides)

    response = await _call_with_policy(
        operation="arerank",
        model_name=model_name,
        timeout_seconds=_coerce_float(timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
        max_attempts=max_attempts,
        retry_delay_seconds=_coerce_float(retry_delay_seconds, DEFAULT_RETRY_DELAY_SECONDS),
        fn=_invoke,
    )
    await _emit_usage(
        operation="arerank",
        intent="rerank",
        model_name=model_name,
        response=response,
    )
    return response
