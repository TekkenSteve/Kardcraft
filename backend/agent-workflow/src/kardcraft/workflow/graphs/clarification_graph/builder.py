"""Builder for clarification graph."""

from langgraph.graph import END, StateGraph

from .nodes import run_clarification
from .state import ClarificationGraphState


def build_clarification_graph():
    builder = StateGraph(ClarificationGraphState)
    builder.add_node("clarify", run_clarification)
    builder.set_entry_point("clarify")
    builder.add_edge("clarify", END)
    return builder.compile()

