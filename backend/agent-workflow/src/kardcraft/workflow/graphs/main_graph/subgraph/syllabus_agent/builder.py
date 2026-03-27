"""Builder for Syllabus Agent.

Refactored per resumable_agent_design.md:
- Tool-based: knowledge_tools (RAG) + quick_research (web search)
- No external Agent routing - tools called directly within nodes
- State preserved within syllabus_agent
"""

from langgraph.graph import StateGraph, END
from kardcraft.workflow.graphs.main_graph.state import Context
from .state import State
from .nodes import (
    init_syllabus,
    generate_syllabus,
    request_feedback,
    finalize_syllabus,
)


def route_after_generation(state: State) -> str:
    """Route from generate_syllabus based on state content."""
    if state.get("error") or state.get("pending_questions"):
        return "finalize"
        
    if state.get("learning_units"):
        return "feedback"
        
    return "finalize"


def route_after_feedback(state: State) -> str:
    """Route from request_feedback based on iterations."""
    iteration = state.get("iteration_count", 0)
    max_iters = state.get("max_iterations", 3)
    
    if iteration >= max_iters or state.get("approved_unit_ids"):
        return "finalize"
        
    return "generate"


def build_syllabus_agent():
    """Build the syllabus agent graph with data-driven routing."""

    builder = StateGraph(State, context_schema=Context)

    builder.add_node("init_syllabus", init_syllabus)
    builder.add_node("generate_syllabus", generate_syllabus)
    builder.add_node("request_feedback", request_feedback)
    builder.add_node("finalize_syllabus", finalize_syllabus)

    builder.set_entry_point("init_syllabus")

    builder.add_edge("init_syllabus", "generate_syllabus")

    builder.add_conditional_edges(
        "generate_syllabus",
        route_after_generation,
        {
            "feedback": "request_feedback",
            "finalize": "finalize_syllabus",
        },
    )

    builder.add_conditional_edges(
        "request_feedback",
        route_after_feedback,
        {
            "generate": "generate_syllabus",
            "finalize": "finalize_syllabus",
        },
    )

    builder.add_edge("finalize_syllabus", END)

    return builder
