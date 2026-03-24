"""Real Monty runtime adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .errors import BrokerException
from .external_functions import ExternalFunctionRegistry


@dataclass
class SnapshotStore:
    _items: Dict[str, bytes] = field(default_factory=dict)

    def put(self, key: str, value: bytes) -> None:
        self._items[key] = value

    def get(self, key: str) -> bytes:
        if key not in self._items:
            raise BrokerException("BROKER_SNAPSHOT_NOT_FOUND", f"snapshot not found: {key}")
        return self._items[key]


class MontyRuntime:
    def __init__(
        self,
        *,
        function_registry: Optional[ExternalFunctionRegistry] = None,
        snapshot_store: Optional[SnapshotStore] = None,
    ):
        self.function_registry = function_registry or ExternalFunctionRegistry()
        self.snapshot_store = snapshot_store or SnapshotStore()
        self._compile_cache: Dict[str, bytes] = {}

    def _import_monty(self):
        try:
            import pydantic_monty as pydantic_monty  # type: ignore
        except Exception as exc:
            raise BrokerException(
                "BROKER_MONTY_UNAVAILABLE",
                "pydantic-monty is not installed or unavailable",
            ) from exc
        return pydantic_monty

    def _cache_key(self, code: str, inputs: list[str], type_check_stubs: str = "") -> str:
        raw = f"{code}\n{inputs}\n{type_check_stubs}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    async def run(
        self,
        *,
        code: str,
        inputs: dict[str, Any],
        input_keys: list[str],
        allow_functions: list[str],
        type_check_stubs: str = "",
    ) -> Any:
        monty_mod = self._import_monty()
        key = self._cache_key(code, input_keys, type_check_stubs)
        if key in self._compile_cache:
            monty_obj = monty_mod.Monty.load(self._compile_cache[key])
        else:
            monty_obj = monty_mod.Monty(
                code,
                inputs=input_keys,
                script_name="broker_exec.py",
                type_check=True,
                type_check_stubs=type_check_stubs,
            )
            self._compile_cache[key] = monty_obj.dump()

        callables = self.function_registry.build_callables(allow_functions)
        return await monty_mod.run_monty_async(
            monty_obj,
            inputs=inputs,
            external_functions=callables,
        )

    def start(
        self,
        *,
        code: str,
        inputs: dict[str, Any],
        input_keys: list[str],
        snapshot_id: str,
    ) -> dict[str, Any]:
        monty_mod = self._import_monty()
        monty_obj = monty_mod.Monty(code, inputs=input_keys, script_name="broker_exec.py")
        result = monty_obj.start(inputs=inputs)
        self.snapshot_store.put(snapshot_id, result.dump())
        return {
            "snapshot_id": snapshot_id,
            "state": type(result).__name__,
            "details_json": json.dumps({"function_name": getattr(result, "function_name", "")}),
        }

    def resume(self, *, snapshot_id: str, return_value_json: str) -> dict[str, Any]:
        monty_mod = self._import_monty()
        snapshot_data = self.snapshot_store.get(snapshot_id)
        snapshot = monty_mod.load_snapshot(snapshot_data)
        return_value = json.loads(return_value_json) if return_value_json else None
        result = snapshot.resume(return_value=return_value)
        if hasattr(result, "dump"):
            self.snapshot_store.put(snapshot_id, result.dump())
        return {
            "snapshot_id": snapshot_id,
            "state": type(result).__name__,
            "details_json": json.dumps({"output": getattr(result, "output", None)}, ensure_ascii=False),
        }
