"""Deep research graph entrypoint."""

from .builder import build_deep_research_graph

deep_research_graph = build_deep_research_graph()

__all__ = ["build_deep_research_graph", "deep_research_graph"]

