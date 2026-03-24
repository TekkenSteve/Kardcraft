"""Builder for evidence supervisor agent."""

from langgraph.graph import END, StateGraph

from .nodes import run_evidence_supervisor
from .state import EvidenceSupervisorState


def build_evidence_supervisor_agent():
    builder = StateGraph(EvidenceSupervisorState)
    builder.add_node("run", run_evidence_supervisor)
    builder.set_entry_point("run")
    builder.add_edge("run", END)
    return builder
