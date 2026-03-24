"""Builder for syllabus supervisor agent."""

from langgraph.graph import END, StateGraph

from .nodes import run_syllabus_supervisor
from .state import SyllabusSupervisorState


def build_syllabus_supervisor_agent():
    builder = StateGraph(SyllabusSupervisorState)
    builder.add_node("run", run_syllabus_supervisor)
    builder.set_entry_point("run")
    builder.add_edge("run", END)
    return builder
