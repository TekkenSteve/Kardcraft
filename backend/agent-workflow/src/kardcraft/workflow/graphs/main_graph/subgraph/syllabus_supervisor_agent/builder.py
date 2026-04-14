"""Builder for syllabus supervisor agent."""

from langgraph.graph import END, StateGraph

from kardcraft.workflow.graphs.main_graph.state import Context
from .nodes import (
    prepare_syllabus_supervisor_inputs_node,
    route_after_syllabus_supervisor_validation,
    run_syllabus_supervisor_generate_node,
    validate_syllabus_supervisor_inputs_node,
)
from .state import State


def build_syllabus_supervisor_agent():
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("prepare_inputs", prepare_syllabus_supervisor_inputs_node)
    builder.add_node("validate_inputs", validate_syllabus_supervisor_inputs_node)
    builder.add_node("run_generate", run_syllabus_supervisor_generate_node)

    builder.set_entry_point("prepare_inputs")
    builder.add_edge("prepare_inputs", "validate_inputs")
    builder.add_conditional_edges(
        "validate_inputs",
        route_after_syllabus_supervisor_validation,
        {
            "run_generate": "run_generate",
            "done": END,
        },
    )
    builder.add_edge("run_generate", END)
    return builder
