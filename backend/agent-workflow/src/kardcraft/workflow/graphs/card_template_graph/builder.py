"""Builder for dedicated card_template_graph."""

from langgraph.graph import END, StateGraph

from .nodes import (
    initialize_template_flow,
    load_template_bundle,
    build_template_blueprint,
    finalize_template_flow,
)
from .state import CardTemplateState


def build_card_template_graph():
    """Build dedicated card template graph (independent of main_graph)."""
    workflow = StateGraph(CardTemplateState)

    workflow.add_node("initialize", initialize_template_flow)
    workflow.add_node("load_template", load_template_bundle)
    workflow.add_node("build_blueprint", build_template_blueprint)
    workflow.add_node("finalize", finalize_template_flow)

    workflow.set_entry_point("initialize")
    workflow.add_edge("initialize", "load_template")
    workflow.add_edge("load_template", "build_blueprint")
    workflow.add_edge("build_blueprint", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()
