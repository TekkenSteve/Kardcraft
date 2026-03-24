"""External function registry for Monty."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Literal

from .errors import BrokerException

EffectLevel = Literal["pure", "read_only", "write", "network"]
FunctionImpl = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    version: str
    effect_level: EffectLevel
    timeout_ms: int
    idempotent: bool
    tenant_scope: Literal["workspace", "org", "global"]
    impl: FunctionImpl

    @property
    def fq_name(self) -> str:
        return f"{self.name}:{self.version}"


class ExternalFunctionRegistry:
    def __init__(self):
        self._functions: Dict[str, FunctionSpec] = {}

    def register(self, spec: FunctionSpec) -> None:
        self._functions[spec.fq_name] = spec

    def get(self, fq_name: str) -> FunctionSpec:
        if fq_name not in self._functions:
            raise BrokerException("BROKER_FUNC_NOT_ALLOWED", f"function not found: {fq_name}")
        return self._functions[fq_name]

    def build_callables(self, allowlist: list[str]) -> Dict[str, FunctionImpl]:
        callables: Dict[str, FunctionImpl] = {}
        for fq_name in allowlist:
            spec = self.get(fq_name)

            async def wrapper(*args, __spec: FunctionSpec = spec, **kwargs):
                try:
                    return await asyncio.wait_for(
                        __spec.impl(*args, **kwargs),
                        timeout=max(0.1, __spec.timeout_ms / 1000),
                    )
                except asyncio.TimeoutError as exc:
                    raise BrokerException(
                        "BROKER_FUNC_TIMEOUT",
                        f"external function timeout: {__spec.fq_name}",
                    ) from exc

            callables[spec.name] = wrapper
        return callables
