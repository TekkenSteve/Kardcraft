"""State for syllabus supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class State(TypedDict, total=False):
    user_input: str
    message_knowledge: Optional[str]
    file_ids: List[str]
    driven_mode: Optional[str]
    file_tree_path_active: Optional[bool]
    query_scope: Optional[str]
    retrieval_budget: Dict[str, Any]
    document_trees: List[Dict[str, Any]]
    candidate_nodes: List[Dict[str, Any]]
    subject_domain: Optional[str]
    task_complexity: Optional[str]
    difficulty_level: Optional[str]
    language: Optional[str]

    status: str
    reason: str
    syllabus_status: str
    termination_reason: Optional[str]
    learning_units: List[Dict[str, Any]]
    syllabus_outline: List[Dict[str, Any]]
    outline_sources: List[Dict[str, Any]]
    evidence_items: List[Dict[str, Any]]
    pending_questions: List[Dict[str, Any]]
    clarification_responses: Dict[str, Any]
