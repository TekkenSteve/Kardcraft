"""Main graph builder (thin orchestrator, v3)."""

from langgraph.graph import END, StateGraph

from kardcraft.workflow.graphs.main_graph.edges import (
    route_after_card_scope,
    route_after_document_tree_planner,
    route_after_preflight,
    route_after_syllabus,
    route_after_card_pipeline,
    route_after_evidence,
)
from kardcraft.workflow.graphs.main_graph.nodes import (
    run_document_tree_planner,
    run_evidence_builder,
    run_card_scope_planner,
    finalize_processing,
    initialize_processing,
    run_card_pipeline,
    run_intent_classifier,
    run_socratic_preflight,
)
from kardcraft.workflow.graphs.main_graph.subgraph.syllabus_supervisor_agent.nodes import (
    run_syllabus_supervisor_node,
)
from kardcraft.workflow.graphs.main_graph.state import Context, State


def build_main_graph():
    workflow = StateGraph(State, context_schema=Context)

    workflow.add_node("initialize", initialize_processing)
    workflow.add_node("intent_classifier", run_intent_classifier)
    workflow.add_node("socratic_preflight", run_socratic_preflight)
    workflow.add_node("document_tree_planner", run_document_tree_planner)
    workflow.add_node("syllabus_supervisor", run_syllabus_supervisor_node)
    workflow.add_node("card_scope_planner", run_card_scope_planner)
    workflow.add_node("evidence_builder", run_evidence_builder)
    workflow.add_node("card_pipeline", run_card_pipeline)
    workflow.add_node("finalize", finalize_processing)

    workflow.set_entry_point("initialize")
    workflow.add_edge("initialize", "intent_classifier")
    workflow.add_edge("intent_classifier", "socratic_preflight")
    workflow.add_conditional_edges(
        "socratic_preflight",
        route_after_preflight,
        {
            "document_tree_planner": "document_tree_planner",
            "syllabus_supervisor": "syllabus_supervisor",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "document_tree_planner",
        route_after_document_tree_planner,
        {
            "syllabus_supervisor": "syllabus_supervisor",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "syllabus_supervisor",
        route_after_syllabus,
        {
            "card_scope_planner": "card_scope_planner",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "card_scope_planner",
        route_after_card_scope,
        {
            "evidence_builder": "evidence_builder",
            "card_pipeline": "card_pipeline",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "evidence_builder",
        route_after_evidence,
        {
            "card_pipeline": "card_pipeline",
            "finalize": "finalize",
        },
    )
    workflow.add_conditional_edges(
        "card_pipeline",
        route_after_card_pipeline,
        {
            "evidence_builder": "evidence_builder",
            "finalize": "finalize",
        },
    )

    workflow.add_edge("finalize", END)
    return workflow.compile()
