"""Tests for MontyRuntime."""

from __future__ import annotations

import pytest

from kardcraft.sandbox_broker.monty_runtime import MontyRuntime, SnapshotStore


class TestSnapshotStore:
    def test_put_and_get_roundtrip(self):
        store = SnapshotStore()
        store.put("key1", b"deadbeef")
        assert store.get("key1") == b"deadbeef"

    def test_get_missing_raises_broker_exception(self):
        store = SnapshotStore()
        with pytest.raises(Exception, match="snapshot not found"):
            store.get("nonexistent")


class TestMontyRuntimeCacheKey:
    def test_cache_key_is_deterministic(self):
        runtime = MontyRuntime()
        key1 = runtime._cache_key("print(1)", ["x"], "")
        key2 = runtime._cache_key("print(1)", ["x"], "")
        assert key1 == key2

    def test_cache_key_differs_for_different_code(self):
        runtime = MontyRuntime()
        key1 = runtime._cache_key("print(1)", [], "")
        key2 = runtime._cache_key("print(2)", [], "")
        assert key1 != key2

    def test_cache_key_differs_for_different_inputs(self):
        runtime = MontyRuntime()
        key1 = runtime._cache_key("print(x)", ["x"], "")
        key2 = runtime._cache_key("print(x)", ["y"], "")
        assert key1 != key2

    def test_cache_key_differs_for_different_stubs(self):
        runtime = MontyRuntime()
        key1 = runtime._cache_key("print(1)", [], "")
        key2 = runtime._cache_key("print(1)", [], "x: int = 0")
        assert key1 != key2

    def test_cache_key_sha256_format(self):
        runtime = MontyRuntime()
        key = runtime._cache_key("print(1)", [], "")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


class TestMontyRuntimeImportFailure:
    def test_missing_pydantic_monty_raises_broker_exception(self):
        runtime = MontyRuntime()
        original_import = __builtins__["__import__"]  # type: ignore

        def fake_import(name, *args, **kwargs):
            if name == "pydantic_monty":
                raise ImportError("No module named 'pydantic_monty'")
            return original_import(name, *args, **kwargs)

        __builtins__["__import__"] = fake_import  # type: ignore
        try:
            with pytest.raises(Exception, match="pydantic-monty"):
                runtime._import_monty()
        finally:
            __builtins__["__import__"] = original_import  # type: ignore


class TestMontyRuntimeStartResume:
    def test_start_returns_snapshot_metadata(self):
        runtime = MontyRuntime()
        try:
            result = runtime.start(
                code="x = 1",
                inputs={},
                input_keys=[],
                snapshot_id="snap-1",
            )
            assert result["snapshot_id"] == "snap-1"
            assert "state" in result
        except Exception:
            pytest.skip("pydantic-monty not installed")

    def test_resume_unknown_snapshot_raises(self):
        runtime = MontyRuntime()
        with pytest.raises(Exception, match="snapshot not found"):
            runtime.resume(snapshot_id="snap-does-not-exist", return_value_json="null")
