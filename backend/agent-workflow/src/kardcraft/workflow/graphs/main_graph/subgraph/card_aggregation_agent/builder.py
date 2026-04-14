"""Builder for card aggregation agent."""

from langgraph.graph import END, StateGraph

from kardcraft.workflow.graphs.main_graph.state import Context

from .nodes import run_card_aggregation_node
from .state import State


def build_card_aggregation_agent():
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("run", run_card_aggregation_node)
    builder.set_entry_point("run")
    builder.add_edge("run", END)
    return builder
