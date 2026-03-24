"""Main graph builder (thin orchestrator, v3)."""

from langgraph.graph import END, StateGraph

from kardcraft.workflow.graphs.main_graph.edges import (
    route_after_card,
    route_after_evidence,
    route_after_syllabus,
)
from kardcraft.workflow.graphs.main_graph.nodes import (
    finalize_processing,
    initialize_processing,
    run_card_supervisor,
    run_evidence_supervisor,
    run_intent_classifier,
    run_syllabus_supervisor,
)
from kardcraft.workflow.graphs.main_graph.state import MainState


def build_main_graph():
    workflow = StateGraph(MainState)

    workflow.add_node("initialize", initialize_processing)
    workflow.add_node("intent_classifier", run_intent_classifier)
    workflow.add_node("syllabus_supervisor", run_syllabus_supervisor)
    workflow.add_node("evidence_supervisor", run_evidence_supervisor)
    workflow.add_node("card_supervisor", run_card_supervisor)
    workflow.add_node("finalize", finalize_processing)

    workflow.set_entry_point("initialize")
    workflow.add_edge("initialize", "intent_classifier")
    workflow.add_edge("intent_classifier", "syllabus_supervisor")
    workflow.add_conditional_edges(
        "syllabus_supervisor",
        route_after_syllabus,
        {
            "evidence_supervisor": "evidence_supervisor",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "evidence_supervisor",
        route_after_evidence,
        {
            "card_supervisor": "card_supervisor",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "card_supervisor",
        route_after_card,
        {
            "finalize": "finalize",
        },
    )

    workflow.add_edge("finalize", END)
    return workflow.compile()
