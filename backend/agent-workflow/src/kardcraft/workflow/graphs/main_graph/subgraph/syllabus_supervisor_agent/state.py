"""State for syllabus supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class SyllabusSupervisorState(TypedDict, total=False):
    user_input: str
    source_content: Optional[str]
    file_ids: List[str]
    session_id: Optional[str]
    user_id: Optional[str]
    subject_domain: Optional[str]
    task_complexity: Optional[str]
    difficulty_level: Optional[str]
    language: Optional[str]

    status: str
    reason: str
    learning_units: List[Dict[str, Any]]
    pending_questions: List[Dict[str, Any]]
    clarification_responses: Dict[str, Any]
