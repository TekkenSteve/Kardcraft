"""Builder for card supervisor agent."""

from langgraph.graph import END, StateGraph

from .nodes import run_card_supervisor
from .state import CardSupervisorState


def build_card_supervisor_agent():
    builder = StateGraph(CardSupervisorState)
    builder.add_node("run", run_card_supervisor)
    builder.set_entry_point("run")
    builder.add_edge("run", END)
    return builder
