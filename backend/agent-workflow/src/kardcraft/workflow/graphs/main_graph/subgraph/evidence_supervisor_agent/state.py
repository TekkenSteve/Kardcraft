"""State for evidence supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class EvidenceSupervisorState(TypedDict, total=False):
    user_input: str
    source_content: Optional[str]
    synthesized_knowledge: str
    file_ids: List[str]
    session_id: Optional[str]
    user_id: Optional[str]
    subject_domain: Optional[str]
    difficulty_level: Optional[str]
    target_count: Optional[int]
    language: Optional[str]
    learning_units: List[Dict[str, Any]]

    status: str
    reason: str
    evidence_summary: str
    pending_questions: List[Dict[str, Any]]
    research_results: Dict[str, Any]
