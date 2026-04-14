"""Builder for card scope supervisor agent."""

from langgraph.graph import END, StateGraph

from kardcraft.workflow.graphs.main_graph.state import Context

from .nodes import run_card_scope_supervisor_node
from .state import State


def build_card_scope_supervisor_agent():
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("run", run_card_scope_supervisor_node)
    builder.set_entry_point("run")
    builder.add_edge("run", END)
    return builder
