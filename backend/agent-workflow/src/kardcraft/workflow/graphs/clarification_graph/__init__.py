"""Clarification graph entrypoint and reusable tool."""

from .builder import build_clarification_graph
from .tool import clarify

clarification_graph = build_clarification_graph()

__all__ = ["build_clarification_graph", "clarification_graph", "clarify"]

