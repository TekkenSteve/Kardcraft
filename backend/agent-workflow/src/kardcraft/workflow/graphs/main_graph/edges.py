"""Routing for thin main graph."""

from kardcraft.workflow.graphs.main_graph.state import MainState


def route_after_syllabus(state: MainState) -> str:
    if state.get("error"):
        return "finalize"
    status = state.get("syllabus_status")
    if status == "outline_ready":
        return "evidence_supervisor"
    return "finalize"


def route_after_evidence(state: MainState) -> str:
    if state.get("error"):
        return "finalize"
    status = state.get("evidence_status")
    if status == "evidence_ready":
        return "card_supervisor"
    return "finalize"


def route_after_card(state: MainState) -> str:
    # all paths finalize, status only affects payload semantics
    return "finalize"
