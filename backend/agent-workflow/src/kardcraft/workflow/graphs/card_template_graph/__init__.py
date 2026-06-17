"""Card template graph package."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "build_card_template_graph":
        from .builder import build_card_template_graph

        return build_card_template_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["build_card_template_graph"]
