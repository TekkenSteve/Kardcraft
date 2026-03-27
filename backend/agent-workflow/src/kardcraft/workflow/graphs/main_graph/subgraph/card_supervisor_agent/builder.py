"""Builder for card supervisor agent."""

from langgraph.graph import END, StateGraph

from kardcraft.workflow.graphs.main_graph.state import Context
from .nodes import run_card_supervisor
from .state import CardSupervisorState


def build_card_supervisor_agent():
    builder = StateGraph(CardSupervisorState, context_schema=Context)
    builder.add_node("run", run_card_supervisor)
    builder.set_entry_point("run")
    builder.add_edge("run", END)
    return builder
