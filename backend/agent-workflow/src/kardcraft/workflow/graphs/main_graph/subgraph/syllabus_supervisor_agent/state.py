"""State for syllabus supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class State(TypedDict, total=False):
    user_input: str
    message_knowledge: Optional[str]
    file_ids: List[str]
    subject_domain: Optional[str]
    task_complexity: Optional[str]
    difficulty_level: Optional[str]
    language: Optional[str]

    status: str
    reason: str
    learning_units: List[Dict[str, Any]]
    pending_questions: List[Dict[str, Any]]
    clarification_responses: Dict[str, Any]
