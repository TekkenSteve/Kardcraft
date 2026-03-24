"""Evidence supervisor agent."""

from .builder import build_evidence_supervisor_agent

evidence_supervisor_agent = build_evidence_supervisor_agent().compile()

__all__ = ["evidence_supervisor_agent", "build_evidence_supervisor_agent"]
