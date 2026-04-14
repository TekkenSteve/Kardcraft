"""State for evidence ReAct agent."""

from typing import Any, Dict, List, Optional, TypedDict


class State(TypedDict, total=False):
    user_input: str
    query_scope: Optional[str]
    retrieval_budget: Dict[str, Any]
    candidate_nodes: List[Dict[str, Any]]
    file_ids: List[str]
    file_tree_path_active: Optional[bool]

    evidence_status: Optional[str]
    pending_questions: List[Dict[str, Any]]
    evidence_items: List[Dict[str, Any]]
    selected_nodes: List[Dict[str, Any]]
    evidence_loop_report: Dict[str, Any]
    evidence_store: Dict[str, Any]
    coverage_state: Dict[str, Any]
    synthesized_knowledge: Optional[str]
    message_knowledge: Optional[str]
    research_results: Dict[str, Any]
    error: Optional[str]
