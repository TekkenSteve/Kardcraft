"""State for card scope supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class State(TypedDict, total=False):
    user_input: str
    file_ids: List[str]
    query_scope: Optional[str]
    retrieval_budget: Dict[str, Any]
    document_trees: List[Dict[str, Any]]
    candidate_nodes: List[Dict[str, Any]]
    learning_units: List[Dict[str, Any]]
    evidence_items: List[Dict[str, Any]]
    syllabus_status: Optional[str]

    card_scope_status: str
    card_scope_report: Dict[str, Any]
    message: Optional[str]
    error: Optional[str]
    scoped_learning_units: List[Dict[str, Any]]
    scope_chunks: List[Dict[str, Any]]
