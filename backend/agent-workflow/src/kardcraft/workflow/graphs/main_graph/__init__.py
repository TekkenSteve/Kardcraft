"""Main graph module."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "build_main_graph":
        from .builder import build_main_graph

        return build_main_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["build_main_graph"]
