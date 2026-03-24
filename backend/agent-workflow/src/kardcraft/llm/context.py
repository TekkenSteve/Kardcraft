"""Runtime context for unified LLM client calls."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


UsageEmitter = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class LLMRuntimeContext:
    task_id: str
    session_id: str
    user_id: str
    usage_emitter: Optional[UsageEmitter] = None


_runtime_context_var: ContextVar[Optional[LLMRuntimeContext]] = ContextVar(
    "kardcraft_llm_runtime_context",
    default=None,
)


def set_runtime_context(ctx: Optional[LLMRuntimeContext]) -> Token:
    return _runtime_context_var.set(ctx)


def reset_runtime_context(token: Token) -> None:
    _runtime_context_var.reset(token)


def get_runtime_context() -> Optional[LLMRuntimeContext]:
    return _runtime_context_var.get()
