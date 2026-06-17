"""Deep research graph entrypoint."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _deep_research_graph():
    from .builder import build_deep_research_graph

    return build_deep_research_graph()


def __getattr__(name: str) -> Any:
    if name == "build_deep_research_graph":
        from .builder import build_deep_research_graph

        return build_deep_research_graph
    if name == "deep_research_graph":
        return _deep_research_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["build_deep_research_graph", "deep_research_graph"]
