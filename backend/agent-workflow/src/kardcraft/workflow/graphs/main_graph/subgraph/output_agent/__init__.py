"""Output agent."""

from .builder import build_output_agent

output_agent = build_output_agent().compile()

__all__ = ["build_output_agent", "output_agent"]
