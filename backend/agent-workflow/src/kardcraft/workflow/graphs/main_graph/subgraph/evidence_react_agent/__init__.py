"""Evidence ReAct agent."""

from .builder import build_evidence_react_agent

evidence_react_agent = build_evidence_react_agent().compile()
