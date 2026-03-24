"""Builder for deep research graph."""

from langgraph.graph import END, START, MessagesState, StateGraph

from .nodes import run_deep_research


def build_deep_research_graph():
    builder = StateGraph(MessagesState)
    builder.add_node("deep_research", run_deep_research)
    builder.add_edge(START, "deep_research")
    builder.add_edge("deep_research", END)
    return builder.compile()

