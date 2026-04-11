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
        if state.get("evidence_items"):
            return "card_supervisor"
        return "evidence_builder"
    return "finalize"


def route_after_evidence(state: State) -> str:
    if state.get("error"):
        return "finalize"
    status = state.get("evidence_status")
    if status == "evidence_ready":
        return "card_supervisor"
    return "finalize"


def route_after_card(state: State) -> str:
    reason = str(state.get("error") or "").strip()
    retry_count = int(state.get("evidence_retry_count") or 0)
    if reason in {"missing_file_tree_evidence", "missing_file_tree_evidence_items"} and retry_count <= 1:
        return "evidence_builder"
    return "finalize"
