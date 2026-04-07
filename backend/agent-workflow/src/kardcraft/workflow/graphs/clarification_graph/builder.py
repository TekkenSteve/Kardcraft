"""Builder for clarification graph."""

from langgraph.graph import END, StateGraph

from .nodes import run_clarification
from .state import State


def build_clarification_graph():
    builder = StateGraph(State)
    builder.add_node("clarify", run_clarification)
    builder.set_entry_point("clarify")
    builder.add_edge("clarify", END)
    return builder.compile()

