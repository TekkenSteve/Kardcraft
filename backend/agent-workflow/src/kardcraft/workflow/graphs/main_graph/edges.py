"""Routing for thin main graph."""

from kardcraft.workflow.graphs.main_graph.state import State


def route_after_preflight(state: State) -> str:
    if state.get("error"):
        return "finalize"
    if state.get("preflight_status") == "need_user_input":
        return "finalize"
    if bool(state.get("file_tree_path_active")):
        return "document_tree_planner"
    return "syllabus_supervisor"


def route_after_document_tree_planner(state: State) -> str:
    if state.get("error"):
        return "finalize"
    return "syllabus_supervisor"


def route_after_syllabus(state: State) -> str:
    if state.get("error"):
        return "finalize"
    status = str(state.get("syllabus_status") or "").strip().lower()
    if status == "outline_ready":
        return "card_scope_planner"
    return "finalize"


def route_after_card_scope(state: State) -> str:
    if state.get("error"):
        return "finalize"
    scope_status = str(state.get("card_scope_status") or "").strip().lower()
    if scope_status != "scope_ready":
        return "finalize"
    if state.get("scope_chunks"):
        if state.get("evidence_items"):
            return "card_pipeline"
        if state.get("candidate_nodes"):
            return "evidence_builder"
        return "card_pipeline"
    if state.get("evidence_items"):
        return "card_pipeline"
    if state.get("candidate_nodes"):
        return "evidence_builder"
    return "finalize"


def route_after_evidence(state: State) -> str:
    if state.get("error"):
        return "finalize"
    status = state.get("evidence_status")
    if status == "evidence_ready":
        return "card_pipeline"
    return "finalize"


def route_after_card_pipeline(state: State) -> str:
    return "finalize"
