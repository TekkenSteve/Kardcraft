"""Unified runtime LLM client facade."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional, TypeVar

import litellm
from litellm import token_counter

from kardcraft.utils.logger import logger

from .context import LLMRuntimeContext, get_runtime_context
from .discovery import detect_provider, get_completion_config, get_embed_model, get_rerank_model
from .usage_event import LLMUsageEventPayload, LLM_USAGE_SCHEMA_VERSION

T = TypeVar("T")

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_RETRY_DELAY_SECONDS = 0.8


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


def _read_usage_field(usage: Any, key: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return _coerce_int(usage.get(key))
    return _coerce_int(getattr(usage, key, 0))


def _extract_completion_text(response: Any) -> str:
    if not response or not getattr(response, "choices", None):
        return ""
    choice = response.choices[0]
    message = getattr(choice, "message", None)
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _resolve_provider(model_name: str) -> str:
    model_name = str(model_name or "").strip()
    if "/" in model_name:
        prefix = model_name.split("/", 1)[0].strip().lower()
        if prefix:
            return prefix
    return detect_provider()


def _normalize_error(operation: str, model_name: str, err: Exception) -> LLMClientError:
    provider = _resolve_provider(model_name)
    return LLMClientError(
        f"LLM {operation} failed provider={provider} model={model_name or '<unknown>'}: {type(err).__name__}: {err}"
    )


def _extract_request_id(response: Any) -> str:
    return str(getattr(response, "id", "") or "").strip()


def _token_counter_safe(*, model_name: str, messages: Optional[list[dict[str, Any]]] = None, text: Optional[str] = None) -> int:
    try:
        if messages is not None:
            return _coerce_int(token_counter(model=model_name, messages=messages))
        if text is not None:
            return _coerce_int(token_counter(model=model_name, text=text))
        return 0
    except Exception:
        logger.warning(
            "llm usage estimation failed",
            model=model_name,
            has_messages=messages is not None,
            has_text=bool(text),
        )
        return 0


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
    messages: Optional[list[dict[str, Any]]] = None,
    input_text: Optional[str] = None,
    estimated_output_text: Optional[str] = None,
) -> None:
    ctx = _require_runtime_context()
    usage = getattr(response, "usage", None)

    prompt_tokens = _read_usage_field(usage, "prompt_tokens")
    completion_tokens = _read_usage_field(usage, "completion_tokens")
    cache_read_tokens = _read_usage_field(usage, "cache_read_input_tokens")
    cache_write_tokens = _read_usage_field(usage, "cache_creation_input_tokens")
    total_tokens = _read_usage_field(usage, "total_tokens")
    estimated = False
    source = "provider"

    if total_tokens == 0 and usage is not None:
        total_tokens = prompt_tokens + completion_tokens

    if usage is None:
        if messages is not None:
            prompt_tokens = _token_counter_safe(model_name=model_name, messages=messages)
            text = estimated_output_text if estimated_output_text is not None else _extract_completion_text(response)
            completion_tokens = _token_counter_safe(model_name=model_name, text=text)
            total_tokens = prompt_tokens + completion_tokens
            estimated = True
            source = "estimated_messages"
        elif input_text is not None:
            prompt_tokens = _token_counter_safe(model_name=model_name, text=input_text)
            completion_tokens = 0
            total_tokens = prompt_tokens
            estimated = True
            source = "estimated_input"

    external_request_id = _extract_request_id(response)
    if not external_request_id:
        external_request_id = uuid.uuid4().hex

    now_iso = datetime.now(timezone.utc).isoformat()
    payload: LLMUsageEventPayload = {
        "schema_version": LLM_USAGE_SCHEMA_VERSION,
        "idempotency_key": f"{ctx.task_id}:{external_request_id}",
        "task_id": ctx.task_id,
        "workflow_id": ctx.task_id,
        "session_id": ctx.session_id,
        "user_id": ctx.user_id,
        "operation": operation,
        "intent": intent,
        "provider": _resolve_provider(model_name),
        "model": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": total_tokens,
        "input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
        "cache_cost_usd": 0.0,
        "total_cost_usd": 0.0,
        "estimated": estimated,
        "source": source,
        "external_request_id": external_request_id,
        "created_at": now_iso,
    }
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
        messages=messages,
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
    cfg = get_completion_config(intent=intent, temperature=temperature, stream=True, **overrides)
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
        content_chunks: list[str] = []
        async for chunk in stream:
            last_chunk = chunk
            delta_text = ""
            try:
                choices = getattr(chunk, "choices", None)
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    delta_text = str(getattr(delta, "content", "") or "")
            except Exception:
                delta_text = ""
            if delta_text:
                content_chunks.append(delta_text)
            yield chunk

        if last_chunk is None:
            raise LLMClientError(f"LLM acompletion_stream returned no chunks for model={model_name}")

        await _emit_usage(
            operation="acompletion_stream",
            intent=intent,
            model_name=model_name,
            response=last_chunk,
            messages=messages,
            estimated_output_text="".join(content_chunks),
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
    input_text = input if isinstance(input, str) else "\n".join([str(item) for item in input])
    await _emit_usage(
        operation="aembedding",
        intent="embedding",
        model_name=model_name,
        response=response,
        input_text=input_text,
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
        input_text=query + "\n" + "\n".join(documents),
    )
    return response
