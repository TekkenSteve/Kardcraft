"""State for clarification graph."""

from typing import Any, Dict, List, Optional, TypedDict


class State(TypedDict, total=False):
    user_input: str
    message_knowledge: Optional[str]
    file_ids: List[str]
    language: Optional[str]
    session_id: Optional[str]
    round_index: int
    asked_questions: List[str]
    pending_questions: List[Dict[str, Any]]

    status: str
    clarification_state: str
    termination_reason: Optional[str]
    message: Optional[str]
    reason: str
    missing_info: List[str]
