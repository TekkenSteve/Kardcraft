"""Clarification graph entrypoint and reusable tool."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _clarification_graph():
    from .builder import build_clarification_graph

    return build_clarification_graph()


def __getattr__(name: str) -> Any:
    if name == "build_clarification_graph":
        from .builder import build_clarification_graph

        return build_clarification_graph
    if name == "clarification_graph":
        return _clarification_graph()
    if name == "clarify":
        from .tool import clarify

        return clarify
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["build_clarification_graph", "clarification_graph", "clarify"]
