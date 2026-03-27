"""State for evidence supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class EvidenceSupervisorState(TypedDict, total=False):
    user_input: str
    message_knowledge: Optional[str]
    synthesized_knowledge: str
    file_ids: List[str]
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
